import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_alembic_upgrade_downgrade_upgrade_smoke():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for migration smoke testing")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("Migration smoke testing requires PostgreSQL with pgvector")

    backend_dir = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": database_url}

    for command in (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        [sys.executable, "-m", "alembic", "upgrade", "head"],
    ):
        result = subprocess.run(
            command,
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
