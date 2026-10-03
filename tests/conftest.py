import os

# Set dummy credentials before any `app.*` module is imported, so app.config's
# fail-fast checks pass in tests without requiring a real .env file.
os.environ.setdefault("TMDB_API_KEY", "test-tmdb-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
