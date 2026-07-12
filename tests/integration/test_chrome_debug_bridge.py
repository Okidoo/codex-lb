from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any, cast

import pytest
from sqlalchemy import select

from app.db.models import ChromeDebugAuditEvent
from app.db.session import SessionLocal
from app.modules.chrome_debug.bridge import AgentConnection, ChromeDebugBridgeError, RelaySession, chrome_debug_hub
from app.modules.chrome_debug.repository import ChromeDebugRepository
from app.modules.chrome_debug.service import ChromeDebugService

pytestmark = pytest.mark.integration


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed: list[tuple[int, str]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


async def _create_api_key(async_client, *, name: str) -> dict[str, object]:
    response = await async_client.post("/api/api-keys/", json={"name": name})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["key"].startswith("sk-clb-")
    return payload


async def _set_grant(async_client, api_key_id: str, *, enabled: bool = True) -> None:
    response = await async_client.put(f"/api/chrome-debug/grants/{api_key_id}", json={"enabled": enabled})
    assert response.status_code == 204, response.text


def _auth_headers(api_key: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key['key']}"}


async def _register_browser(
    async_client,
    api_key: dict[str, object],
    *,
    browser_id: str,
    label: str,
) -> dict[str, object]:
    response = await async_client.post(
        "/api/chrome-debug/agent-token",
        headers=_auth_headers(api_key),
        json={
            "browserId": browser_id,
            "label": label,
            "userAgent": "Chrome/118 test",
            "extensionVersion": "0.1.0",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_chrome_debug_requires_explicit_api_key_grant(async_client):
    api_key = await _create_api_key(async_client, name="debug-disabled")

    blocked = await async_client.post(
        "/api/chrome-debug/agent-token",
        headers=_auth_headers(api_key),
        json={"browserId": "browser-disabled", "label": "Disabled browser"},
    )
    assert blocked.status_code == 403

    await _set_grant(async_client, str(api_key["id"]))

    created = await _register_browser(async_client, api_key, browser_id="browser-enabled", label="Enabled browser")
    assert created["browserId"] == "browser-enabled"
    websocket_url = created["websocketUrl"]
    assert isinstance(websocket_url, str)
    assert websocket_url.startswith("ws://testserver/api/chrome-debug/agent/ws?token=")

    listed = await async_client.get("/api/chrome-debug/browsers", headers=_auth_headers(api_key))
    assert listed.status_code == 200, listed.text
    browsers = listed.json()["browsers"]
    assert [browser["id"] for browser in browsers] == ["browser-enabled"]
    assert browsers[0]["label"] == "Enabled browser"


@pytest.mark.asyncio
async def test_chrome_debug_browser_listing_is_scoped_to_api_key(async_client):
    first_key = await _create_api_key(async_client, name="debug-first")
    second_key = await _create_api_key(async_client, name="debug-second")
    await _set_grant(async_client, str(first_key["id"]))
    await _set_grant(async_client, str(second_key["id"]))

    await _register_browser(async_client, first_key, browser_id="browser-first", label="First")
    await _register_browser(async_client, second_key, browser_id="browser-second", label="Second")

    first_list = await async_client.get("/api/chrome-debug/browsers", headers=_auth_headers(first_key))
    assert first_list.status_code == 200, first_list.text
    assert [browser["id"] for browser in first_list.json()["browsers"]] == ["browser-first"]

    dashboard_list = await async_client.get("/api/chrome-debug/browsers")
    assert dashboard_list.status_code == 200, dashboard_list.text
    assert {browser["id"] for browser in dashboard_list.json()["browsers"]} == {"browser-first", "browser-second"}


@pytest.mark.asyncio
async def test_chrome_debug_rejects_browser_id_takeover(async_client):
    first_key = await _create_api_key(async_client, name="debug-owner")
    second_key = await _create_api_key(async_client, name="debug-takeover")
    await _set_grant(async_client, str(first_key["id"]))
    await _set_grant(async_client, str(second_key["id"]))
    await _register_browser(async_client, first_key, browser_id="shared-browser", label="Owner")

    takeover = await async_client.post(
        "/api/chrome-debug/agent-token",
        headers=_auth_headers(second_key),
        json={"browserId": "shared-browser", "label": "Takeover"},
    )
    assert takeover.status_code == 403
    assert takeover.json()["error"]["code"] == "chrome_debug_browser_owner_mismatch"


@pytest.mark.asyncio
async def test_chrome_debug_agent_tokens_are_single_use(async_client):
    api_key = await _create_api_key(async_client, name="debug-agent-token")
    await _set_grant(async_client, str(api_key["id"]))
    created = await _register_browser(async_client, api_key, browser_id="browser-token", label="Token browser")

    async with SessionLocal() as session:
        service = ChromeDebugService(ChromeDebugRepository(session))
        first = await service.consume_agent_token(str(created["token"]))
        second = await service.consume_agent_token(str(created["token"]))

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_chrome_debug_relay_token_exposes_cdp_json_endpoints(async_client, monkeypatch):
    api_key = await _create_api_key(async_client, name="debug-relay")
    await _set_grant(async_client, str(api_key["id"]))
    await _register_browser(async_client, api_key, browser_id="browser-relay", label="Relay browser")

    async def fake_targets_for_browser(browser_id: str) -> list[dict[str, object]]:
        assert browser_id == "browser-relay"
        return [
            {
                "id": "target-1",
                "type": "page",
                "title": "Debug target",
                "url": "https://example.test/",
                "attached": False,
            }
        ]

    monkeypatch.setattr(chrome_debug_hub, "is_online", lambda browser_id: browser_id == "browser-relay")
    monkeypatch.setattr(chrome_debug_hub, "targets_for_browser", fake_targets_for_browser)

    relay = await async_client.post(
        "/api/chrome-debug/relay-token",
        headers=_auth_headers(api_key),
        json={"browserId": "browser-relay", "ttlSeconds": 120},
    )
    assert relay.status_code == 200, relay.text
    token = relay.json()["token"]

    version = await async_client.get(f"/chrome-debug/relay/{token}/json/version")
    assert version.status_code == 200, version.text
    assert version.json()["Browser"] == "Codex-LB Chrome Debug Bridge"
    assert version.json()["webSocketDebuggerUrl"].endswith(
        f"/chrome-debug/relay/{token}/devtools/browser/browser-relay"
    )

    targets = await async_client.get(f"/chrome-debug/relay/{token}/json/list")
    assert targets.status_code == 200, targets.text
    assert targets.json() == [
        {
            "id": "target-1",
            "type": "page",
            "title": "Debug target",
            "url": "https://example.test/",
            "attached": False,
            "webSocketDebuggerUrl": f"ws://testserver/chrome-debug/relay/{token}/devtools/page/target-1",
        }
    ]


@pytest.mark.asyncio
async def test_chrome_debug_relay_token_rejects_offline_browser(async_client, monkeypatch):
    api_key = await _create_api_key(async_client, name="debug-offline")
    await _set_grant(async_client, str(api_key["id"]))
    await _register_browser(async_client, api_key, browser_id="browser-offline", label="Offline browser")
    monkeypatch.setattr(chrome_debug_hub, "is_online", lambda _browser_id: False)

    relay = await async_client.post(
        "/api/chrome-debug/relay-token",
        headers=_auth_headers(api_key),
        json={"browserId": "browser-offline"},
    )
    assert relay.status_code == 400
    assert relay.json()["error"]["code"] == "chrome_debug_browser_offline"


@pytest.mark.asyncio
async def test_chrome_debug_extension_zip_contains_generated_manifest(async_client):
    response = await async_client.get("/api/chrome-debug/extension.zip")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))

    assert {"manifest.json", "service_worker.js", "popup.html", "popup.js", "popup.css"} <= names
    assert manifest["manifest_version"] == 3
    assert manifest["host_permissions"] == ["http://testserver/*"]
    assert "debugger" in manifest["permissions"]


@pytest.mark.asyncio
async def test_chrome_debug_audit_events_are_persisted(async_client):
    api_key = await _create_api_key(async_client, name="debug-audit")
    await _set_grant(async_client, str(api_key["id"]))

    async with SessionLocal() as session:
        service = ChromeDebugService(ChromeDebugRepository(session))
        await service.audit(
            "test_event",
            api_key_id=str(api_key["id"]),
            browser_id="browser-audit",
            details={"ok": True},
        )
        result = await session.execute(
            select(ChromeDebugAuditEvent).where(ChromeDebugAuditEvent.event_type == "test_event")
        )
        event = result.scalar_one()

    assert event.api_key_id == api_key["id"]
    assert event.browser_id == "browser-audit"
    assert event.details_json is not None
    assert json.loads(event.details_json) == {"ok": True}


@pytest.mark.asyncio
async def test_chrome_debug_bridge_allows_one_controller_per_target():
    agent = AgentConnection(
        browser_id="browser-bridge",
        api_key_id="key-bridge",
        websocket=cast(Any, FakeWebSocket()),
    )
    first_socket = FakeWebSocket()
    second_socket = FakeWebSocket()
    agent.targets = {"target-1": {"id": "target-1"}}
    agent.sessions["session-1"] = RelaySession(
        session_id="session-1",
        target_id="target-1",
        websocket=cast(Any, first_socket),
    )

    with pytest.raises(ChromeDebugBridgeError, match="active controller"):
        await agent.attach(
            RelaySession(session_id="session-2", target_id="target-1", websocket=cast(Any, second_socket))
        )


@pytest.mark.asyncio
async def test_chrome_debug_bridge_forwards_cdp_responses_to_relay_session():
    relay_socket = FakeWebSocket()
    agent = AgentConnection(
        browser_id="browser-bridge",
        api_key_id="key-bridge",
        websocket=cast(Any, FakeWebSocket()),
    )
    agent.sessions["session-1"] = RelaySession(
        session_id="session-1",
        target_id="target-1",
        websocket=cast(Any, relay_socket),
    )

    await agent.handle_agent_message(
        {
            "type": "cdp_response",
            "sessionId": "session-1",
            "requestId": 7,
            "ok": True,
            "result": {"frameTree": {"frame": {"id": "frame-1"}}},
        }
    )

    assert relay_socket.sent == [{"id": 7, "result": {"frameTree": {"frame": {"id": "frame-1"}}}}]
