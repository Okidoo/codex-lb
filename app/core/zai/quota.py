from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from app.core.clients.usage import UsageFetchError
from app.core.usage.models import RateLimitPayload, UsagePayload, UsageWindow

ZAI_DEFAULT_QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
ZAI_CN_QUOTA_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
ZAI_QUOTA_PATH = "/api/monitor/usage/quota/limit"

_TOKEN_LIMIT = "TOKENS_LIMIT"
_FIVE_HOUR_UNIT = 3
_FIVE_HOUR_NUMBER = 5
_WEEKLY_UNIT = 6
_WEEKLY_NUMBER = 1
_FIVE_HOUR_SECONDS = 5 * 60 * 60
_WEEKLY_SECONDS = 7 * 24 * 60 * 60


async def fetch_zai_usage(
    *,
    api_key: str,
    base_url: str | None = None,
    session: aiohttp.ClientSession | None = None,
    timeout_seconds: float = 10.0,
) -> UsagePayload:
    """Fetch Z.AI quota limits and map them to codex-lb primary/secondary windows."""

    url = _quota_url_for_base_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with client.get(url, headers=headers, timeout=timeout) as response:
            data = await _safe_json(response)
            if response.status >= 400:
                code = _extract_error_code(data)
                message = _extract_error_message(data) or f"Z.AI usage fetch failed ({response.status})"
                raise UsageFetchError(response.status, message, code=code)
            if data.get("success") is False:
                code = _extract_error_code(data)
                message = _extract_error_message(data) or "Z.AI usage fetch failed"
                status = 401 if "auth" in message.lower() else 502
                raise UsageFetchError(status, message, code=code)
            return usage_payload_from_zai_quota(data)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise UsageFetchError(0, f"Z.AI usage fetch failed: {exc}") from exc
    finally:
        if owns_session:
            await client.close()


def usage_payload_from_zai_quota(data: dict[str, Any]) -> UsagePayload:
    raw = data.get("data", data)
    if not isinstance(raw, dict):
        raise UsageFetchError(502, "Invalid Z.AI usage payload")
    limits = raw.get("limits")
    if not isinstance(limits, list):
        raise UsageFetchError(502, "Invalid Z.AI usage payload")

    primary_window: UsageWindow | None = None
    secondary_window: UsageWindow | None = None
    for limit in limits:
        if not isinstance(limit, dict) or limit.get("type") != _TOKEN_LIMIT:
            continue
        unit = _as_int(limit.get("unit"))
        number = _as_int(limit.get("number"))
        if unit == _FIVE_HOUR_UNIT and number == _FIVE_HOUR_NUMBER:
            primary_window = _usage_window(limit, window_seconds=_FIVE_HOUR_SECONDS)
        elif unit == _WEEKLY_UNIT and number == _WEEKLY_NUMBER:
            secondary_window = _usage_window(limit, window_seconds=_WEEKLY_SECONDS)

    return UsagePayload(
        plan_type="zai",
        rate_limit=RateLimitPayload(
            primary_window=primary_window,
            secondary_window=secondary_window,
        ),
    )


def _usage_window(limit: dict[str, Any], *, window_seconds: int) -> UsageWindow:
    used_percent = _as_float(limit.get("percentage"))
    reset_at = _reset_at_seconds(limit.get("nextResetTime"))
    return UsageWindow(
        used_percent=_clamp_percent(used_percent),
        reset_at=reset_at,
        limit_window_seconds=window_seconds,
    )


def _quota_url_for_base_url(base_url: str | None) -> str:
    if not base_url:
        return ZAI_DEFAULT_QUOTA_URL
    split = urlsplit(base_url)
    if not split.scheme or not split.netloc:
        return ZAI_DEFAULT_QUOTA_URL
    if split.netloc == "open.bigmodel.cn":
        return ZAI_CN_QUOTA_URL
    return urlunsplit((split.scheme, split.netloc, ZAI_QUOTA_PATH, "", ""))


async def _safe_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    try:
        data = await response.json(content_type=None)
    except Exception as exc:
        text = await response.text()
        message = text.strip() or f"Z.AI usage fetch failed ({response.status})"
        raise UsageFetchError(response.status, message) from exc
    if not isinstance(data, dict):
        raise UsageFetchError(response.status, "Invalid Z.AI usage payload")
    return data


def _extract_error_code(data: dict[str, Any]) -> str | None:
    value = data.get("code")
    if value is not None:
        return str(value)
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return str(code) if code is not None else None
    return None


def _extract_error_message(data: dict[str, Any]) -> str | None:
    for key in ("msg", "message", "error_description"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = data.get("error")
    if isinstance(error, dict):
        value = error.get("message")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(error, str) and error.strip():
        return error.strip()
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _reset_at_seconds(value: Any) -> int | None:
    reset_ms = _as_int(value)
    if reset_ms is None:
        return None
    return max(0, reset_ms // 1000)


def _clamp_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(100.0, value))
