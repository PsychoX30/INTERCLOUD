"""Shared pytest configuration — loads env vars from /app/backend/.env if not already set."""
import os
from pathlib import Path


def _load_env_from_file() -> None:
    env_path = Path("/app/backend/.env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_env_from_file()

# Force PORTAL_API_BASE to the public frontend URL (test what the user sees)
if os.environ.get("REACT_APP_BACKEND_URL") and not os.environ.get("PORTAL_API_BASE"):
    os.environ["PORTAL_API_BASE"] = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api/portal"
