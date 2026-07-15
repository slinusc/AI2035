"""Start a local Postgres Docker container matching DATABASE_URL.

Parses credentials from config and launches `postgres:16` without ever putting
secrets on the command line (docker reads them from the subprocess env).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

NAME = "vision2035-pg"


def main() -> None:
    url = config.DATABASE_URL  # postgresql+asyncpg://user:pass@host:port/db
    if not url:
        raise SystemExit("DATABASE_URL not set")

    parts = urlsplit(url.replace("+asyncpg", ""))
    user = unquote(parts.username or "postgres")
    password = unquote(parts.password or "postgres")
    db = (parts.path or "/postgres").lstrip("/") or "postgres"
    port = parts.port or 5432

    # Remove any prior container with this name.
    subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)

    env = dict(os.environ)
    env["POSTGRES_USER"] = user
    env["POSTGRES_PASSWORD"] = password
    env["POSTGRES_DB"] = db

    result = subprocess.run(
        [
            "docker", "run", "-d", "--name", NAME,
            "-p", f"{port}:5432",
            "-e", "POSTGRES_USER",       # value pulled from env, not argv
            "-e", "POSTGRES_PASSWORD",
            "-e", "POSTGRES_DB",
            "postgres:16",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    print(f"started container {NAME} for db '{db}' user '{user}' on port {port}")


if __name__ == "__main__":
    main()
