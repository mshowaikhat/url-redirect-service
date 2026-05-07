# url-redirect-service

FastAPI service that resolves a short code to its original URL and returns an HTTP 302 redirect. Part of the SWE 455 (Cloud Applications Engineering) URL shortener project at KFUPM.

The companion services live in:

- [`url-shortener-service`](https://github.com/mshowaikhat/url-shortener-service) — creates short codes
- [`url-shortener-infra`](https://github.com/mshowaikhat/url-shortener-infra) — Terraform for everything in GCP

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/{code}` | Resolve `code`, return **302** with `Location: <long_url>` |
| `GET` | `/livez` | Liveness probe (200 while process is up) |
| `GET` | `/readyz` | Readiness probe (200 if Firestore + Redis reachable; 200 with `status=degraded` if only Redis is down) |

Full schema: [`openapi.yaml`](./openapi.yaml).

> Cloud Run reserves `/healthz` at the edge — probes are `/livez` and `/readyz`.

---

## Read-through cache + graceful degradation

The redirect path is a **Redis read-through cache** with Firestore as the source of truth.

```
GET /{code}
  └─ Redis GET <code>
       ├─ HIT  → 302 Location: long_url   (then async background: increment click_count)
       └─ MISS → Firestore lookup
                  ├─ found    → populate Redis (background) → 302
                  └─ not found → 404
```

**Graceful-degradation contract:** every Redis exception is caught internally and treated as a cache miss. A Redis outage is indistinguishable from a cold cache from the user's perspective — it never causes a 5xx. This contract is enforced by 21 pytest tests (`tests/test_cache.py`, `tests/test_redirect_route.py`).

---

## Tech stack

- Python 3.13 + FastAPI 0.115 + Uvicorn
- Google Cloud Firestore (read-only from this service)
- Google Cloud Memorystore for Redis (BASIC tier, AUTH enabled, private VPC IP)
- VPC Serverless Connector (Cloud Run → Memorystore)
- Google Secret Manager (`redis-auth-string`)
- OpenTelemetry → Cloud Trace + Cloud Monitoring (incl. custom `cache.hits` / `cache.misses` counters)
- Structured JSON logging (Cloud Logging native fields)

---

## Local development

```bash
docker compose up --build
# Service on  http://localhost:8080
# Firestore emulator on  http://localhost:8085
# Redis on    localhost:6379
```

Run the test suite:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest
```

---

## Configuration (environment variables)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GCP_PROJECT_ID` | yes | — | GCP project hosting Firestore |
| `FIRESTORE_COLLECTION` | no | `urls` | |
| `FIRESTORE_EMULATOR_HOST` | no | — | Local dev only |
| `REDIS_HOST` | no | — | Memorystore private IP; injected by Terraform in production |
| `REDIS_PORT` | no | `6379` | |
| `REDIS_AUTH` | no | — | From Secret Manager (`redis-auth-string`) in production |
| `LOG_LEVEL` | no | `INFO` | |
| `OTEL_SERVICE_NAME` | no | `redirect` | |
| `PORT` | no | `8080` | Cloud Run sets this automatically |

If `REDIS_HOST` is unset or Redis is unreachable, the service falls through to Firestore for every request — correct behaviour, just slower.

---

## CI/CD

Every push to `main` runs `.github/workflows/deploy.yml`:

```
lint (ruff) → pytest → docker build → push to Artifact Registry (SHA tag) → Cloud Run deploy → smoke test
```

Authentication uses **Workload Identity Federation** — no service-account keys stored anywhere.

---

## Repository layout

```
app/
  main.py               # FastAPI app + lifespan (Factor 9)
  config.py             # Env-driven config (Factor 3)
  cache.py              # Redis read-through cache with graceful degradation
  firestore_client.py   # Firestore client wrapper
  logging_config.py     # JSON logging for Cloud Logging
  tracing.py            # OTel → Cloud Trace + Cloud Monitoring
  routes/
    health.py           # /livez, /readyz
    redirect.py         # /{code}
tests/
  test_cache.py         # 15 unit tests for graceful-degradation paths
  test_redirect_route.py # 6 route tests incl. broken-Redis → still-302
Dockerfile
docker-compose.yml      # Local dev with Firestore emulator + Redis
openapi.yaml            # Public API spec
```

---

## License & course context

KFUPM SWE 455 Term 252 course project.
