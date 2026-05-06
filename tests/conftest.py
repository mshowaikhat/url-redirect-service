"""
Pytest configuration.

Set required environment variables before any app module is imported
during test collection. Settings() is a module-level singleton that reads
env vars at import time, so these must be set before the first `import app.*`.
"""

import os

os.environ.setdefault("GCP_PROJECT_ID", "test-project-id")
os.environ.setdefault("FIRESTORE_COLLECTION", "urls")
