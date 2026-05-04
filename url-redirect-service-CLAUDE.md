# url-redirect-service — Repo Context

This is the FastAPI service that resolves short codes back to long URLs and returns HTTP 302 redirects. **All endpoints are publicly accessible** — this is the user-facing path; gating it behind auth would defeat the purpose of a URL shortener.

If you have not read the parent `swe455/CLAUDE.md`, do that first.

---

## Layout

```
url-redirect-service/
├── .github/workflows/deploy.yml      # CI: lint -> build -> push -> deploy -> smoke test
├── Dockerfile                        # Python 3.13-slim, exec uvicorn on $PORT
├── docker-compose.yml                # Local dev: app + Firestore emulator
├── .dockerignore
├── pyproject.toml                    # Ruff config
├── requirements.txt                  # Pinned: fastapi, uvicorn, google-cloud-firestore, etc.
├── openapi.yaml                      # API contract
└── app/
    ├── __init__.py
    ├── main.py                       # FastAPI app, route registration
    ├── config.py                     # pydantic-settings, env vars only
    ├── firestore_client.py           # asyncio-wrapped sync Firestore SDK
    ├── routes/
    │   ├── health.py                 # /livez, /readyz
    │   └── redirect.py               # GET /{code}
    └── utils/
        └── click_counter.py          # Atomic Firestore Increment(1) for click_count
```

---

## Critical gap

**This service has NO Redis cache integration in code.** The infra repo has provisioned Memorystore (Redis), the VPC connector, and wired `REDIS_HOST`, `REDIS_PORT`, and `REDIS_AUTH` env vars into the Cloud Run service. But the app code never reads these env vars. Currently every redirect goes straight to Firestore.

This is the highest-priority gap to close. Implementing it satisfies Factor 4 (backing services as attached resources) properly. Without the cache code, the report's claims about Redis are vacuous.

When implementing, follow these requirements strictly:

1. New file `app/cache.py` — async Redis client using the `redis` library (`redis[asyncio]>=5.0`).
2. Connection pool initialized in FastAPI lifespan (or lazy on first call).
3. Read-through caching in `app/routes/redirect.py`:
   - Check Redis first
   - On miss, hit Firestore
   - On Firestore hit, populate Redis with TTL=3600 seconds
   - Return 302 with Location header
4. **Graceful degradation is non-negotiable.** If Redis raises any exception (connection refused, auth failed, timeout), log a warning at WARNING level and fall through to Firestore. The redirect MUST still succeed. A cache failure must NEVER surface to the user.
5. The click counter increment (already in `app/utils/click_counter.py`) stays unchanged. It runs as a background task after the response is sent.
6. Update `/readyz` to also check Redis connectivity, but report it as a non-fatal `degraded` state rather than failing readiness — Redis going down should not take the service offline.
7. Update `openapi.yaml` to document the new `degraded` shape on `/readyz`.
8. Emit two metrics: `redirect/cache_hit_total` (counter) and `redirect/cache_miss_total` (counter). These tie into the Cloud Monitoring custom metrics work that's also on the gap list.

---

## Hot paths

- `GET /{code}` — looks up the long URL, returns 302 with `Location` header. Click counter increments asynchronously via FastAPI `BackgroundTasks` using `firestore.Increment(1)` for atomic concurrent-safe writes. The redirect response is sent BEFORE the counter update completes, preserving low latency.
- `GET /livez` — liveness only. Always 200 if process is up.
- `GET /readyz` — readiness. Today it only checks Firestore. Should be extended to check Redis (without making Redis a hard dependency).

The path `/{code}` is a catch-all — the FastAPI route registration order matters. **Health routes must be registered before the catch-all.** See `app/main.py` — health router is included before redirect router.

---

## Critical: do NOT use `/healthz`

Same Cloud Run edge-intercept issue as the shortener. Both services use `/livez` instead.

---

## Configuration

All config in `app/config.py`. Required env vars:

- `GCP_PROJECT_ID`
- `FIRESTORE_COLLECTION` (default `urls`)
- `LOG_LEVEL` (default `INFO`)
- `PORT`
- `OTEL_SERVICE_NAME` (default `redirect`)

Cache-related env vars (already wired by Terraform, ready for app code to consume):

- `REDIS_HOST` — Memorystore host IP (currently 10.96.122.171)
- `REDIS_PORT` — 6379
- `REDIS_AUTH` — auth string, mounted from Secret Manager `redis-auth-string`

Optional:
- `FIRESTORE_EMULATOR_HOST` — set locally only

When you add Redis to the app, update `app/config.py` to declare these env vars in the Settings class.

---

## Local development with Redis

`docker-compose.yml` currently has just the app and Firestore emulator. To test Redis integration locally without spinning up Memorystore, add a Redis service to docker-compose:

```yaml
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

And in the redirect service section:

```yaml
    environment:
      ...existing vars...
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      REDIS_AUTH: ""   # local Redis has no auth by default
```

The cache code's graceful-degradation pattern means the local app works whether or not Redis is running — useful for testing the fallback path. Stop the Redis container while the app is running and confirm redirects still succeed.

---

## Logging — current state

Same situation as the shortener: basic `logging.basicConfig`, will be upgraded to structured JSON. Same approach applies. Same trace ID extraction from `X-Cloud-Trace-Context` header.

---

## Lifespan / shutdown — current state

Same as the shortener: uses deprecated `@app.on_event` hooks, slated for replacement with the lifespan context manager pattern. When you add the Redis client, lifespan is the right place to:

- Initialize the connection pool on startup
- Close it cleanly on shutdown (otherwise Cloud Run's SIGTERM won't drain pending Redis ops)

---

## Tests

None today. Same situation as the shortener. If you add cache code, write at least one test for the graceful degradation path — the most important behavior to verify is that a Redis outage does not break redirects.

---

## Deploy flow

Identical to the shortener:

```
git push origin main
  -> .github/workflows/deploy.yml triggers
  -> Lint, build, push, deploy, smoke test
```

The deployer SA is `redirect-deployer-sa`. The runtime SA is `redirect-sa`. The Cloud Run service has a VPC connector attached (so it can reach Memorystore on the private network).

---

## Common operations

```cmd
:: Lint locally
python -m ruff check app/ --fix
python -m ruff check app/

:: View Cloud Run logs
gcloud run services logs read redirect --region=us-central1 --project=swe455-urlshortener-252 --limit=50

:: Get the Redis instance details (host, port)
gcloud redis instances describe redis-cache --region=us-central1 --project=swe455-urlshortener-252

:: Test the redirect end-to-end (after creating a short URL via the shortener)
curl -i https://redirect-142958366034.us-central1.run.app/<code>
```

---

## Things you must NOT do

- Do not gate any redirect endpoint behind authentication. The redirect is the user-facing path; it must remain public.
- Do not break the `/{code}` catch-all by registering routes after it. Health routes must come first in `app/main.py`.
- Do not let cache failures break the redirect. Graceful degradation is non-negotiable. If Redis is down, redirects MUST still succeed via Firestore.
- Do not change the OpenAPI contract in breaking ways.
- Do not introduce `:latest` image tags.
