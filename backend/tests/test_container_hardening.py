"""Static runtime guards complemented by actual image startup validation."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_final_image_declares_dedicated_non_root_user(service):
    dockerfile = (ROOT / service / "Dockerfile").read_text()
    runtime = dockerfile.rsplit("FROM ", 1)[-1]
    assert "USER 10001:10001" in runtime
    assert runtime.index("USER 10001:10001") < runtime.index("CMD [")


def test_only_backend_upload_directory_is_prepared_for_runtime_writes():
    dockerfile = (ROOT / "backend/Dockerfile").read_text()
    assert "install -d -o 10001 -g 10001 -m 0700 /app/uploads" in dockerfile
    assert "pip uninstall --yes pip" in dockerfile
    assert '"--no-proxy-headers"' in dockerfile


def test_frontend_cache_is_writable_without_chowning_application_code():
    dockerfile = (ROOT / "frontend/Dockerfile").read_text()
    assert "mkdir -p /app/.next/cache" in dockerfile
    assert "chown -R 10001:10001 /app/.next/cache" in dockerfile
    assert "chown -R 10001:10001 /app " not in dockerfile


def test_compose_application_services_do_not_restore_root_privileges():
    compose = (ROOT / "docker-compose.yml").read_text()
    for service in ("backend", "frontend"):
        body = compose.split(f"  {service}:", 1)[1].split("\n  frontend:", 1)[0]
        assert 'user: "10001:10001"' in body
        assert "no-new-privileges:true" in body
        assert "cap_drop: [ALL]" in body
