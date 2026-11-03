"""Real HTTP headers, real browser cookies, and real PostgreSQL authentication."""

import asyncio
import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import create_app
from tests import test_case_workflow_postgres as pg_fixtures

case_pg = pg_fixtures.case_pg


@pytest.fixture
def cookie_server(case_pg, monkeypatch):
    engine, _ = case_pg
    monkeypatch.setattr("app.main.settings.rate_limit_backend", "memory")
    # Control/probe requests are additional to the auth journey, not a rate-limit test.
    monkeypatch.setattr("app.main.settings.rate_limit_per_minute", 100)
    monkeypatch.setattr("app.api.routes.auth.settings.app_env", "development")
    app = create_app()

    def database():
        with Session(engine, autoflush=False) as db:
            yield db

    app.dependency_overrides[get_db] = database
    ready, release = threading.Event(), threading.Event()
    cross_site = {"cookie_sent": None}

    @app.get("/__cookie-test", response_class=HTMLResponse)
    def document():
        return """<html><body><p id='identity'>loading</p><script>
        const headers={'Content-Type':'application/json','X-FinSight-Cookie-Session':'true'};
        window.boot=fetch('/api/auth/refresh',{method:'POST',headers,body:'{}'})
        .then(async r=>{if(!r.ok){document.querySelector('#identity').textContent='anonymous';return;}
        const token=await r.json();const me=await fetch('/api/auth/me',{headers:{Authorization:'Bearer '+token.access_token}});
        document.querySelector('#identity').textContent=me.ok?(await me.json()).email:'anonymous';});
        </script></body></html>"""

    @app.get("/__held")
    async def held():
        return {"ready": await asyncio.to_thread(ready.wait, 8)}

    @app.post("/__release")
    def unlock():
        release.set()
        return {"released": True}

    @app.post("/api/auth/__cookie-echo")
    def cookie_echo(request: Request):
        cross_site["cookie_sent"] = any(name.startswith("finsight_") for name in request.cookies)
        return {"ok": True}

    @app.get("/__cookie-observed")
    def observed():
        return cross_site

    class DelayHeaders:
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http" or scope.get("query_string") != b"hold=1":
                return await app(scope, receive, send)
            messages = []

            async def capture(message):
                messages.append(message)

            # The transaction and real Set-Cookie generation finish before B's login.
            # Buffer bytes outside production auth; never use route.fetch (it mutates cookies).
            await app(scope, receive, capture)
            ready.set()
            await asyncio.to_thread(release.wait, 15)
            for message in messages:
                await send(message)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(DelayHeaders(), log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    import time

    deadline = time.monotonic() + 5
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Cookie integration HTTP server did not start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        release.set()
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.mark.parametrize(
    "scenario",
    [
        "switch",
        "cross-tab",
        "logout",
        "rotation",
        "stale-failure",
        "concurrent-replay",
        "stale-logout",
    ],
)
def test_real_browser_cookie_ordering(cookie_server, scenario):
    node = shutil.which("node")
    if not node and os.getenv("COOKIE_BROWSER_REQUIRED") == "1":
        pytest.fail("Node is required for mandatory browser cookie integration tests")
    if not node:
        pytest.skip("Node and the frontend Playwright installation are required")
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    if not (frontend / "node_modules" / "playwright").is_dir():
        if os.getenv("COOKIE_BROWSER_REQUIRED") == "1":
            pytest.fail("Required frontend Playwright installation is missing")
        pytest.skip("Frontend Playwright installation is required for real browser cookie tests")
    result = subprocess.run(
        [node, "tests/integration/auth-cookie-ordering.mjs", scenario],
        cwd=frontend,
        env={**os.environ, "COOKIE_TEST_ORIGIN": cookie_server},
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
