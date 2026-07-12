from __future__ import annotations

import hashlib
import io
import json
import secrets
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

from app.core.config.settings import get_settings
from app.core.exceptions import DashboardBadRequestError, DashboardNotFoundError, DashboardPermissionError
from app.core.utils.time import utcnow
from app.db.models import ChromeDebugBrowser
from app.modules.api_keys.service import ApiKeyData
from app.modules.chrome_debug.bridge import chrome_debug_hub
from app.modules.chrome_debug.repository import ChromeDebugRepository
from app.modules.chrome_debug.schemas import (
    ChromeDebugAgentTokenRequest,
    ChromeDebugAgentTokenResponse,
    ChromeDebugBrowserResponse,
    ChromeDebugGrantResponse,
    ChromeDebugRelayTokenResponse,
    ChromeDebugTarget,
)

AGENT_TOKEN_TTL_SECONDS = 600


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _server_base_url(request_base_url: str) -> str:
    return request_base_url.rstrip("/")


def _ws_base_url(http_base_url: str) -> str:
    parsed = urlparse(http_base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return parsed._replace(scheme=scheme).geturl().rstrip("/")


def _chrome_origin(http_base_url: str) -> str:
    parsed = urlparse(http_base_url)
    return parsed._replace(path="", params="", query="", fragment="").geturl().rstrip("/")


class ChromeDebugService:
    def __init__(self, repository: ChromeDebugRepository) -> None:
        self._repository = repository

    async def require_api_key_grant(self, api_key: ApiKeyData) -> None:
        if not await self._repository.has_grant(api_key.id):
            raise DashboardPermissionError(
                "API key is not allowed to use Chrome Debug",
                code="chrome_debug_not_allowed",
            )

    async def list_grants(self) -> list[ChromeDebugGrantResponse]:
        rows = await self._repository.list_grants()
        responses: list[ChromeDebugGrantResponse] = []
        for api_key, grant, browser_count in rows:
            browsers = await self._repository.list_browsers(api_key_id=api_key.id)
            online_count = sum(1 for browser in browsers if chrome_debug_hub.is_online(browser.id))
            responses.append(
                ChromeDebugGrantResponse(
                    api_key_id=api_key.id,
                    api_key_name=api_key.name,
                    key_prefix=api_key.key_prefix,
                    enabled=grant is not None,
                    browser_count=browser_count,
                    online_browser_count=online_count,
                )
            )
        return responses

    async def set_grant(self, api_key_id: str, *, enabled: bool) -> None:
        if not await self._repository.set_grant(api_key_id, enabled=enabled):
            raise DashboardNotFoundError("API key not found")

    async def list_browsers(self, *, api_key_id: str | None = None) -> list[ChromeDebugBrowserResponse]:
        browsers = await self._repository.list_browsers(api_key_id=api_key_id)
        return [await self._browser_response(browser) for browser in browsers]

    async def revoke_browser(self, browser_id: str) -> None:
        if not await self._repository.revoke_browser(browser_id):
            raise DashboardNotFoundError("Chrome debug browser not found")
        agent = chrome_debug_hub.get_agent(browser_id)
        if agent is not None:
            await agent.close(code=4001, reason="browser revoked")

    async def mint_agent_token(
        self,
        *,
        api_key: ApiKeyData,
        payload: ChromeDebugAgentTokenRequest,
        request_base_url: str,
    ) -> ChromeDebugAgentTokenResponse:
        await self.require_api_key_grant(api_key)
        browser_id = payload.browser_id or f"chr_{uuid4().hex}"
        existing_browser = await self._repository.get_browser(browser_id)
        if existing_browser is not None and existing_browser.api_key_id != api_key.id:
            raise DashboardPermissionError(
                "Chrome debug browser is registered to a different API key",
                code="chrome_debug_browser_owner_mismatch",
            )
        settings = get_settings()
        instance_id = getattr(settings, "http_responses_session_bridge_instance_id", None) or "local"
        browser = await self._repository.upsert_browser(
            browser_id=browser_id,
            api_key_id=api_key.id,
            label=payload.label.strip(),
            instance_id=instance_id,
            user_agent=payload.user_agent,
            extension_version=payload.extension_version,
        )
        token = _new_secret("clb_chr_agent")
        expires_at = utcnow() + timedelta(seconds=AGENT_TOKEN_TTL_SECONDS)
        await self._repository.create_agent_token(
            token_hash=_hash_token(token),
            browser_id=browser.id,
            api_key_id=api_key.id,
            expires_at=expires_at,
        )
        ws_url = f"{_ws_base_url(_server_base_url(request_base_url))}/api/chrome-debug/agent/ws?token={quote(token)}"
        return ChromeDebugAgentTokenResponse(
            browser_id=browser.id,
            token=token,
            expires_at=expires_at,
            websocket_url=ws_url,
        )

    async def consume_agent_token(self, token: str):
        return await self._repository.consume_agent_token(_hash_token(token))

    async def mint_relay_token(
        self,
        *,
        api_key: ApiKeyData,
        browser_id: str,
        ttl_seconds: int,
        request_base_url: str,
    ) -> ChromeDebugRelayTokenResponse:
        await self.require_api_key_grant(api_key)
        browser = await self._repository.get_browser(browser_id)
        if browser is None or browser.is_revoked or browser.api_key_id != api_key.id:
            raise DashboardNotFoundError("Chrome debug browser not found")
        if not chrome_debug_hub.is_online(browser.id):
            raise DashboardBadRequestError("Chrome debug browser is offline", code="chrome_debug_browser_offline")
        token = _new_secret("clb_chr_relay")
        expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        await self._repository.create_relay_token(
            token_hash=_hash_token(token),
            browser_id=browser.id,
            api_key_id=api_key.id,
            expires_at=expires_at,
        )
        relay_base = f"{_server_base_url(request_base_url)}/chrome-debug/relay/{quote(token)}"
        return ChromeDebugRelayTokenResponse(
            token=token,
            browser_id=browser.id,
            expires_at=expires_at,
            relay_base_url=relay_base,
            json_version_url=f"{relay_base}/json/version",
            json_list_url=f"{relay_base}/json/list",
        )

    async def mint_dashboard_relay_token(
        self,
        *,
        browser_id: str,
        ttl_seconds: int,
        request_base_url: str,
    ) -> ChromeDebugRelayTokenResponse:
        browser = await self._repository.get_browser(browser_id)
        if browser is None or browser.is_revoked:
            raise DashboardNotFoundError("Chrome debug browser not found")
        if not await self._repository.has_grant(browser.api_key_id):
            raise DashboardPermissionError("Browser API key is not allowed to use Chrome Debug")
        if not chrome_debug_hub.is_online(browser.id):
            raise DashboardBadRequestError("Chrome debug browser is offline", code="chrome_debug_browser_offline")
        token = _new_secret("clb_chr_relay")
        expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        await self._repository.create_relay_token(
            token_hash=_hash_token(token),
            browser_id=browser.id,
            api_key_id=browser.api_key_id,
            expires_at=expires_at,
        )
        relay_base = f"{_server_base_url(request_base_url)}/chrome-debug/relay/{quote(token)}"
        return ChromeDebugRelayTokenResponse(
            token=token,
            browser_id=browser.id,
            expires_at=expires_at,
            relay_base_url=relay_base,
            json_version_url=f"{relay_base}/json/version",
            json_list_url=f"{relay_base}/json/list",
        )

    async def get_relay_context(self, token: str):
        relay_token = await self._repository.get_valid_relay_token(_hash_token(token))
        if relay_token is None:
            return None
        return relay_token

    async def create_session(self, *, session_id: str, browser_id: str, api_key_id: str, target_id: str) -> None:
        await self._repository.create_session(
            session_id=session_id,
            browser_id=browser_id,
            api_key_id=api_key_id,
            target_id=target_id,
        )

    async def close_session(self, session_id: str) -> None:
        await self._repository.close_session(session_id)

    async def mark_browser_seen(self, browser_id: str) -> None:
        await self._repository.mark_browser_seen(browser_id)

    async def mark_browser_disconnected(self, browser_id: str) -> None:
        await self._repository.mark_browser_disconnected(browser_id)

    async def audit(self, event_type: str, **kwargs: Any) -> None:
        details = kwargs.pop("details", None)
        await self._repository.audit(
            event_type,
            details_json=json.dumps(details, sort_keys=True) if details is not None else None,
            **kwargs,
        )

    async def cdp_json_version(self, *, token: str, request_base_url: str) -> dict[str, Any] | None:
        relay_token = await self.get_relay_context(token)
        if relay_token is None:
            return None
        browser_ws = (
            f"{_ws_base_url(_server_base_url(request_base_url))}"
            f"/chrome-debug/relay/{quote(token)}/devtools/browser/{quote(relay_token.browser_id)}"
        )
        return {
            "Browser": "Codex-LB Chrome Debug Bridge",
            "Protocol-Version": "1.3",
            "User-Agent": "codex-lb",
            "V8-Version": "",
            "WebKit-Version": "",
            "webSocketDebuggerUrl": browser_ws,
        }

    async def cdp_json_list(self, *, token: str, request_base_url: str) -> list[dict[str, Any]] | None:
        relay_token = await self.get_relay_context(token)
        if relay_token is None:
            return None
        targets = await chrome_debug_hub.targets_for_browser(relay_token.browser_id)
        ws_base = f"{_ws_base_url(_server_base_url(request_base_url))}/chrome-debug/relay/{quote(token)}/devtools/page"
        return [self._target_to_cdp(target, ws_base=ws_base) for target in targets]

    def build_extension_zip(self, *, request_base_url: str) -> bytes:
        extension_dir = Path(__file__).parent / "extension"
        chrome_origin = _chrome_origin(_server_base_url(request_base_url))
        manifest = json.loads((extension_dir / "manifest.template.json").read_text(encoding="utf-8"))
        manifest["host_permissions"] = [f"{chrome_origin}/*"]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            for path in extension_dir.iterdir():
                if path.name == "manifest.template.json" or not path.is_file():
                    continue
                archive.write(path, path.name)
        return buffer.getvalue()

    async def _browser_response(self, browser: ChromeDebugBrowser) -> ChromeDebugBrowserResponse:
        targets = await chrome_debug_hub.targets_for_browser(browser.id)
        api_key_name = (
            browser.grant.api_key.name if browser.grant is not None and browser.grant.api_key is not None else None
        )
        online = chrome_debug_hub.is_online(browser.id)
        return ChromeDebugBrowserResponse(
            id=browser.id,
            api_key_id=browser.api_key_id,
            api_key_name=api_key_name,
            label=browser.label,
            status="online" if online else "offline",
            target_count=len(targets),
            targets=[self._target_response(target) for target in targets],
            instance_id=browser.instance_id,
            user_agent=browser.user_agent,
            extension_version=browser.extension_version,
            is_revoked=browser.is_revoked,
            created_at=browser.created_at,
            updated_at=browser.updated_at,
            last_seen_at=browser.last_seen_at,
            disconnected_at=browser.disconnected_at,
        )

    @staticmethod
    def _target_response(target: dict[str, Any]) -> ChromeDebugTarget:
        raw = dict(target)
        target_id = str(raw.pop("id", "") or raw.get("targetId") or raw.get("tabId"))
        return ChromeDebugTarget(
            id=target_id,
            type=str(raw.get("type")) if raw.get("type") is not None else None,
            title=str(raw.get("title")) if raw.get("title") is not None else None,
            url=str(raw.get("url")) if raw.get("url") is not None else None,
            attached=bool(raw.get("attached")),
            browser_context_id=str(raw.get("browserContextId")) if raw.get("browserContextId") is not None else None,
            raw=raw,
        )

    @staticmethod
    def _target_to_cdp(target: dict[str, Any], *, ws_base: str) -> dict[str, Any]:
        target_id = str(target.get("id") or target.get("targetId") or target.get("tabId"))
        target_type = target.get("type") or "page"
        return {
            "id": target_id,
            "type": target_type,
            "title": target.get("title") or "",
            "url": target.get("url") or "",
            "attached": bool(target.get("attached")),
            "webSocketDebuggerUrl": f"{ws_base}/{quote(target_id, safe='')}",
        }
