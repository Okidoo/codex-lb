from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.codex_catalog import (
    build_codex_catalog_payload,
    build_codex_setup_summary,
    build_install_script,
    build_uninstall_script,
)

router = APIRouter(prefix="/codex", tags=["codex-setup"])
_ALLOWED_PUBLIC_ORIGIN_SCHEMES = frozenset({"http", "https"})
_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]+$")


@router.get("/catalog.json")
async def codex_catalog(request: Request) -> JSONResponse:
    public_origin = _public_origin(request)
    return JSONResponse(content=build_codex_catalog_payload(base_url=f"{public_origin}/backend-api/codex"))


@router.get("/setup")
async def codex_setup_summary(request: Request) -> JSONResponse:
    public_origin = _public_origin(request)
    return JSONResponse(content=build_codex_setup_summary(base_url=f"{public_origin}/backend-api/codex"))


@router.get("/setup/install.sh")
async def codex_setup_install_script(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        build_install_script(public_origin=_public_origin(request)),
        media_type="text/x-shellscript; charset=utf-8",
    )


@router.get("/setup/uninstall.sh")
async def codex_setup_uninstall_script() -> PlainTextResponse:
    return PlainTextResponse(
        build_uninstall_script(),
        media_type="text/x-shellscript; charset=utf-8",
    )


def _public_origin(request: Request) -> str:
    forwarded_proto = _first_header_value(request.headers.get("x-forwarded-proto"))
    forwarded_host = _first_header_value(request.headers.get("x-forwarded-host") or request.headers.get("host"))
    if forwarded_host:
        scheme = (forwarded_proto or request.url.scheme).lower()
        if scheme not in _ALLOWED_PUBLIC_ORIGIN_SCHEMES:
            raise HTTPException(status_code=400, detail="Invalid public origin scheme")
        if not _is_safe_public_host(forwarded_host):
            raise HTTPException(status_code=400, detail="Invalid public origin host")
        return f"{scheme}://{forwarded_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _first_header_value(value: str | None) -> str:
    return value.split(",", 1)[0].strip() if value else ""


def _is_safe_public_host(host: str) -> bool:
    if not host or not _SAFE_HOST_RE.fullmatch(host):
        return False
    try:
        parsed = urlsplit(f"//{host}")
        _ = parsed.port
    except ValueError:
        return False
    return bool(parsed.hostname) and not parsed.username and not parsed.password
