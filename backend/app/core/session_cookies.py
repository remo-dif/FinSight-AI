"""Browser session cookie identities and raw-header validation."""

import re

from fastapi import HTTPException, Request

from app.core.config import settings


def secure_cookies() -> bool:
    return settings.app_env != "development"


def cookie_name(name: str) -> str:
    return f"__Host-{name}" if secure_cookies() else name


def session_cookie_path() -> str:
    return "/" if secure_cookies() else "/api/auth"


def raw_cookies(request: Request):
    for header in request.headers.getlist("cookie"):
        for item in header.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator:
                yield name.strip(), value.strip()


def unique_cookie(request: Request, name: str) -> str | None:
    values = [value for key, value in raw_cookies(request) if key == name]
    if len(values) > 1:
        raise HTTPException(401, "Ambiguous session cookies")
    return values[0] if values else None


def session_binding(request: Request) -> str | None:
    binding = unique_cookie(request, cookie_name("finsight_session"))
    if binding is not None and not re.fullmatch(r"[0-9a-f]{32}", binding):
        raise HTTPException(401, "Invalid session selector")
    return binding
