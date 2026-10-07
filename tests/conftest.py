import os

# Settings are read at import time; integration tests swap the database
# for a testcontainers instance via dependency overrides.
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "unused")
os.environ.setdefault("POSTGRES_PASSWORD", "unused")
os.environ.setdefault("POSTGRES_DB", "unused")
os.environ.setdefault("API_KEY", "test-api-key")
