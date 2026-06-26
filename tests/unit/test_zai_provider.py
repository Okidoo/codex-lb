from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.core.openai.model_registry import ModelRegistry
from app.core.zai.adapter import iter_zai_response_events, responses_to_zai_chat
from app.db.models import Account, AccountProvider, AccountStatus
from app.modules.accounts.auth_manager import AuthManager
from app.modules.proxy.load_balancer import _filter_accounts_for_provider, _provider_for_model
from app.modules.usage import updater as usage_updater_module
from app.modules.usage.updater import UsageUpdater


def test_zai_request_translation_consolidates_developer_and_tools() -> None:
    chat_payload = responses_to_zai_chat(
        {
            "model": "glm-5.1",
            "instructions": "base instructions",
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "developer policy"}],
                },
                {"type": "message", "role": "user", "content": "hello"},
                {
                    "type": "function_call",
                    "call_id": "call_lookup",
                    "name": "lookup",
                    "arguments": '{"query":"codex"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_lookup",
                    "output": "found",
                },
                {
                    "type": "local_shell_call",
                    "call_id": "call_shell",
                    "action": {"command": "pwd"},
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "name": "lookup",
                    "description": "Lookup a value",
                    "parameters": {"type": "object"},
                    "strict": True,
                },
                {"type": "web_search_preview"},
            ],
            "reasoning": {"effort": "high"},
            "service_tier": "priority",
            "previous_response_id": "resp_previous",
            "prompt_cache_key": "cache-key",
        }
    )

    chat = cast(dict[str, Any], chat_payload)
    assert chat["model"] == "glm-5.1"
    assert chat["stream"] is True
    assert chat["messages"][0] == {
        "role": "system",
        "content": "base instructions\n\ndeveloper policy",
    }
    assert chat["messages"][1] == {"role": "user", "content": "hello"}
    assert chat["messages"][2]["tool_calls"][0]["function"] == {
        "name": "lookup",
        "arguments": '{"query":"codex"}',
    }
    assert chat["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call_lookup",
        "content": "found",
    }
    assert chat["messages"][4]["tool_calls"][0]["function"] == {
        "name": "local_shell",
        "arguments": '{"command":"pwd"}',
    }
    assert chat["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup a value",
                "parameters": {"type": "object"},
                "strict": True,
            },
        }
    ]
    for unsupported in ("reasoning", "service_tier", "previous_response_id", "prompt_cache_key"):
        assert unsupported not in chat


@pytest.mark.asyncio
async def test_zai_stream_translation_text_tool_usage_and_done() -> None:
    async def upstream() -> AsyncIterator[str]:
        yield json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Hel",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"query":"codex"'},
                                }
                            ],
                        }
                    }
                ]
            }
        )
        yield json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "lo",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": "}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 11,
                    "total_tokens": 18,
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            }
        )
        yield "[DONE]"

    events = cast(list[dict[str, Any]], [event async for event in iter_zai_response_events(upstream(), "glm-5.1")])
    event_types = [event["type"] for event in events]

    assert event_types[0] == "response.created"
    assert "response.output_text.delta" in event_types
    assert "response.function_call_arguments.done" in event_types
    assert event_types[-1] == "response.completed"
    assert [event["delta"] for event in events if event["type"] == "response.output_text.delta"] == [
        "Hel",
        "lo",
    ]
    tool_done = next(event for event in events if event["type"] == "response.function_call_arguments.done")
    assert tool_done["arguments"] == '{"query":"codex"}'
    completed = cast(dict[str, Any], events[-1]["response"])
    assert completed["usage"] == {
        "input_tokens": 7,
        "output_tokens": 11,
        "total_tokens": 18,
        "output_tokens_details": {"reasoning_tokens": 3},
    }


@pytest.mark.asyncio
async def test_glm_models_survive_registry_refresh() -> None:
    registry = ModelRegistry()
    assert "glm-5.1" in registry.get_models_with_fallback()
    assert registry.plan_types_for_model("glm-5.1") == frozenset({"zai"})
    assert registry.prefers_websockets("glm-5.1") is False

    await registry.update({"plus": []})

    assert "glm-5.1" in registry.get_models_with_fallback()
    assert registry.plan_types_for_model("glm-5.1") == frozenset({"zai"})


def test_provider_filtering_routes_glm_to_zai_accounts() -> None:
    openai_account = Account(
        id="openai",
        email="openai@example.com",
        provider=AccountProvider.OPENAI.value,
        plan_type="plus",
        status=AccountStatus.ACTIVE,
    )
    zai_account = Account(
        id="zai",
        email="zai@example.com",
        provider=AccountProvider.ZAI.value,
        plan_type="zai",
        status=AccountStatus.ACTIVE,
    )

    assert _provider_for_model("glm-5.1") == AccountProvider.ZAI.value
    assert _provider_for_model("gpt-5.1") == AccountProvider.OPENAI.value
    assert _filter_accounts_for_provider([openai_account, zai_account], AccountProvider.ZAI.value) == [
        zai_account
    ]
    assert _filter_accounts_for_provider([openai_account, zai_account], AccountProvider.OPENAI.value) == [
        openai_account
    ]


@pytest.mark.asyncio
async def test_zai_account_skips_openai_token_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _zai_account()
    manager = AuthManager(cast(Any, object()))
    run_refresh = AsyncMock()
    monkeypatch.setattr(manager, "_run_refresh", run_refresh)

    result = await manager.ensure_fresh(account, force=True)

    assert result is account
    run_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_zai_account_skips_openai_usage_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _zai_account()
    updater = UsageUpdater(cast(Any, object()))
    refresh_account = AsyncMock()
    fetch_usage = AsyncMock()
    monkeypatch.setattr(updater, "_refresh_account", refresh_account)
    monkeypatch.setattr(usage_updater_module, "fetch_usage", fetch_usage)

    refreshed = await updater.refresh_accounts([account], latest_usage={})

    assert refreshed is False
    refresh_account.assert_not_awaited()
    fetch_usage.assert_not_awaited()


def _zai_account() -> Account:
    return Account(
        id="zai",
        email="zai@example.com",
        provider=AccountProvider.ZAI.value,
        plan_type="zai",
        status=AccountStatus.ACTIVE,
        access_token_encrypted=b"placeholder",
        refresh_token_encrypted=b"placeholder",
        id_token_encrypted=b"placeholder",
        last_refresh=datetime(2026, 1, 1),
    )
