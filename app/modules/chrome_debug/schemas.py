from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class ChromeDebugTarget(DashboardModel):
    id: str
    type: str | None = None
    title: str | None = None
    url: str | None = None
    attached: bool = False
    browser_context_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ChromeDebugBrowserResponse(DashboardModel):
    id: str
    api_key_id: str
    api_key_name: str | None = None
    label: str
    status: str
    target_count: int = 0
    targets: list[ChromeDebugTarget] = Field(default_factory=list)
    instance_id: str | None = None
    user_agent: str | None = None
    extension_version: str | None = None
    is_revoked: bool = False
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime | None = None
    disconnected_at: datetime | None = None


class ChromeDebugBrowsersResponse(DashboardModel):
    browsers: list[ChromeDebugBrowserResponse] = Field(default_factory=list)


class ChromeDebugGrantResponse(DashboardModel):
    api_key_id: str
    api_key_name: str
    key_prefix: str
    enabled: bool = False
    browser_count: int = 0
    online_browser_count: int = 0


class ChromeDebugGrantsResponse(DashboardModel):
    grants: list[ChromeDebugGrantResponse] = Field(default_factory=list)


class ChromeDebugGrantUpdateRequest(DashboardModel):
    enabled: bool


class ChromeDebugAgentTokenRequest(DashboardModel):
    browser_id: str | None = Field(default=None, min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    user_agent: str | None = None
    extension_version: str | None = Field(default=None, max_length=64)


class ChromeDebugAgentTokenResponse(DashboardModel):
    browser_id: str
    token: str
    expires_at: datetime
    websocket_url: str


class ChromeDebugRelayTokenRequest(DashboardModel):
    browser_id: str = Field(min_length=1)
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class ChromeDebugDashboardRelayTokenRequest(DashboardModel):
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class ChromeDebugRelayTokenResponse(DashboardModel):
    token: str
    browser_id: str
    expires_at: datetime
    relay_base_url: str
    json_version_url: str
    json_list_url: str
