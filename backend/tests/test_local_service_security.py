from pathlib import Path


def test_local_databases_are_not_published_and_credentials_are_required():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()
    databases = compose.split("  backend:")[0]
    assert "ports:" not in databases
    assert "POSTGRES_PASSWORD: finance" not in databases
    assert "${POSTGRES_PASSWORD:?" in databases
    assert "${REDIS_PASSWORD:?" in databases
    assert "start-private.sh" in databases
    assert "REDISCLI_AUTH" in databases
    script = root / "infrastructure/redis/start-private.sh"
    assert script.exists()
    contents = script.read_text()
    assert "umask 077" in contents
    assert "requirepass" in contents
    assert '--requirepass "$' not in contents
