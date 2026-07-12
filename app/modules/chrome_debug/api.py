from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, Security, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import (
    require_dashboard_write_access,
    set_dashboard_error_format,
    validate_dashboard_session,
    validate_usage_api_key,
)
from app.db.session import get_session
from app.modules.api_keys.service import ApiKeyData
from app.modules.chrome_debug.bridge import chrome_debug_hub
from app.modules.chrome_debug.repository import ChromeDebugRepository
from app.modules.chrome_debug.schemas import (
    ChromeDebugAgentTokenRequest,
    ChromeDebugAgentTokenResponse,
    ChromeDebugBrowsersResponse,
    ChromeDebugDashboardRelayTokenRequest,
    ChromeDebugGrantsResponse,
    ChromeDebugGrantUpdateRequest,
    ChromeDebugRelayTokenRequest,
    ChromeDebugRelayTokenResponse,
)
from app.modules.chrome_debug.service import ChromeDebugService

dashboard_router = APIRouter(
    prefix="/api/chrome-debug",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)

client_router = APIRouter(prefix="/api/chrome-debug", tags=["chrome-debug"])
relay_router = APIRouter(prefix="/chrome-debug/relay", tags=["chrome-debug"])
_optional_bearer = HTTPBearer(auto_error=False)


def _service(session: AsyncSession) -> ChromeDebugService:
    return ChromeDebugService(ChromeDebugRepository(session))


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@dashboard_router.get("/grants", response_model=ChromeDebugGrantsResponse)
async def list_chrome_debug_grants(session: AsyncSession = Depends(get_session)) -> ChromeDebugGrantsResponse:
    service = _service(session)
    return ChromeDebugGrantsResponse(grants=await service.list_grants())


@dashboard_router.put("/grants/{api_key_id}", status_code=204)
async def update_chrome_debug_grant(
    api_key_id: str,
    payload: ChromeDebugGrantUpdateRequest = Body(...),
    _write_access=Depends(require_dashboard_write_access),
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = _service(session)
    await service.set_grant(api_key_id, enabled=payload.enabled)
    return Response(status_code=204)


@dashboard_router.delete("/browsers/{browser_id}", status_code=204)
async def revoke_dashboard_chrome_debug_browser(
    browser_id: str,
    _write_access=Depends(require_dashboard_write_access),
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = _service(session)
    await service.revoke_browser(browser_id)
    return Response(status_code=204)


@dashboard_router.post("/browsers/{browser_id}/relay-token", response_model=ChromeDebugRelayTokenResponse)
async def create_dashboard_chrome_debug_relay_token(
    request: Request,
    browser_id: str,
    payload: ChromeDebugDashboardRelayTokenRequest | None = Body(default=None),
    _write_access=Depends(require_dashboard_write_access),
    session: AsyncSession = Depends(get_session),
) -> ChromeDebugRelayTokenResponse:
    service = _service(session)
    return await service.mint_dashboard_relay_token(
        browser_id=browser_id,
        ttl_seconds=payload.ttl_seconds if payload is not None else 300,
        request_base_url=_base_url(request),
    )


@dashboard_router.get("/extension.zip")
async def download_chrome_debug_extension(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = _service(session)
    data = service.build_extension_zip(request_base_url=_base_url(request))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="codex-lb-chrome-debug-extension.zip"'},
    )


@client_router.get("/browsers", response_model=ChromeDebugBrowsersResponse)
async def list_chrome_debug_browsers(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_optional_bearer),
    session: AsyncSession = Depends(get_session),
) -> ChromeDebugBrowsersResponse:
    service = _service(session)
    if credentials is not None:
        api_key = await validate_usage_api_key(request, credentials)
        await service.require_api_key_grant(api_key)
        return ChromeDebugBrowsersResponse(browsers=await service.list_browsers(api_key_id=api_key.id))

    set_dashboard_error_format(request)
    await validate_dashboard_session(request)
    return ChromeDebugBrowsersResponse(browsers=await service.list_browsers())


@client_router.post("/relay-token", response_model=ChromeDebugRelayTokenResponse)
async def create_client_chrome_debug_relay_token(
    request: Request,
    payload: ChromeDebugRelayTokenRequest,
    api_key: ApiKeyData = Security(validate_usage_api_key),
    session: AsyncSession = Depends(get_session),
) -> ChromeDebugRelayTokenResponse:
    service = _service(session)
    return await service.mint_relay_token(
        api_key=api_key,
        browser_id=payload.browser_id,
        ttl_seconds=payload.ttl_seconds,
        request_base_url=_base_url(request),
    )


@client_router.post("/agent-token", response_model=ChromeDebugAgentTokenResponse)
async def create_chrome_debug_agent_token(
    request: Request,
    payload: ChromeDebugAgentTokenRequest,
    api_key: ApiKeyData = Security(validate_usage_api_key),
    session: AsyncSession = Depends(get_session),
) -> ChromeDebugAgentTokenResponse:
    service = _service(session)
    return await service.mint_agent_token(api_key=api_key, payload=payload, request_base_url=_base_url(request))


@client_router.websocket("/agent/ws")
async def chrome_debug_agent_ws(
    websocket: WebSocket,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    service = _service(session)
    agent_token = await service.consume_agent_token(token)
    if agent_token is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    agent = await chrome_debug_hub.register_agent(
        browser_id=agent_token.browser_id,
        api_key_id=agent_token.api_key_id,
        websocket=websocket,
    )
    await service.mark_browser_seen(agent.browser_id)
    await service.audit("agent_connected", api_key_id=agent.api_key_id, browser_id=agent.browser_id)
    try:
        await chrome_debug_hub.run_agent(agent)
    finally:
        await service.mark_browser_disconnected(agent.browser_id)
        await service.audit("agent_disconnected", api_key_id=agent.api_key_id, browser_id=agent.browser_id)


@relay_router.get("/{token}/json/version")
async def chrome_debug_json_version(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
):
    service = _service(session)
    payload = await service.cdp_json_version(token=token, request_base_url=_base_url(request))
    if payload is None:
        raise HTTPException(status_code=404, detail="Chrome debug relay token not found")
    return payload


@relay_router.get("/{token}/json")
@relay_router.get("/{token}/json/list")
async def chrome_debug_json_list(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
):
    service = _service(session)
    payload = await service.cdp_json_list(token=token, request_base_url=_base_url(request))
    if payload is None:
        raise HTTPException(status_code=404, detail="Chrome debug relay token not found")
    return payload


@relay_router.websocket("/{token}/devtools/browser/{browser_id}")
async def chrome_debug_browser_ws(
    websocket: WebSocket,
    token: str,
    browser_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    service = _service(session)
    relay_token = await service.get_relay_context(token)
    if relay_token is None or relay_token.browser_id != browser_id:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            request_id = message.get("id") if isinstance(message, dict) else None
            method = message.get("method") if isinstance(message, dict) else None
            if method == "Target.getTargets":
                targets = await chrome_debug_hub.targets_for_browser(browser_id)
                await websocket.send_json({"id": request_id, "result": {"targetInfos": targets}})
            elif method == "Browser.getVersion":
                await websocket.send_json(
                    {
                        "id": request_id,
                        "result": {
                            "protocolVersion": "1.3",
                            "product": "Codex-LB Chrome Debug Bridge",
                            "userAgent": "codex-lb",
                            "jsVersion": "",
                        },
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Unsupported browser-level method: {method}"},
                    }
                )
    except Exception:
        return


@relay_router.websocket("/{token}/devtools/page/{target_id:path}")
async def chrome_debug_page_ws(
    websocket: WebSocket,
    token: str,
    target_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    service = _service(session)
    relay_token = await service.get_relay_context(token)
    if relay_token is None:
        await websocket.close(code=1008)
        return
    browser = await ChromeDebugRepository(session).get_browser(relay_token.browser_id)
    if browser is None or browser.is_revoked:
        await websocket.close(code=1008)
        return
    if not chrome_debug_hub.is_online(browser.id):
        await websocket.close(code=1013)
        return
    await websocket.accept()
    session_id = f"chr_sess_{uuid4().hex}"
    await service.create_session(
        session_id=session_id,
        browser_id=browser.id,
        api_key_id=relay_token.api_key_id,
        target_id=target_id,
    )
    await service.audit(
        "relay_connected",
        api_key_id=relay_token.api_key_id,
        browser_id=browser.id,
        session_id=session_id,
        target_id=target_id,
    )
    try:
        await chrome_debug_hub.run_relay(
            browser_id=browser.id,
            session_id=session_id,
            target_id=target_id,
            websocket=websocket,
        )
    finally:
        await service.close_session(session_id)
        await service.audit(
            "relay_disconnected",
            api_key_id=relay_token.api_key_id,
            browser_id=browser.id,
            session_id=session_id,
            target_id=target_id,
        )
