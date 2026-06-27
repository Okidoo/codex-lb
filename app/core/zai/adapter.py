from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

import aiohttp

from app.core.clients.proxy import ProxyResponseError
from app.core.errors import openai_error
from app.core.model_aliases import ModelAliasMapping
from app.core.openai.requests import ResponsesRequest
from app.core.types import JsonObject, JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping
from app.core.utils.sse import format_sse_event
from app.core.zai.models import canonical_zai_model
from app.core.zai.models import is_zai_model as _is_zai_model

ZAI_PROVIDER = "zai"
ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
ZAI_CHAT_COMPLETIONS_PATH = "/chat/completions"

_TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text", "refusal"})
_TOOL_OUTPUT_TYPES = frozenset(
    {
        "function_call_output",
        "custom_tool_call_output",
        "local_shell_call_output",
        "apply_patch_call_output",
    }
)
_TOOL_CALL_TYPES = frozenset(
    {
        "function_call",
        "custom_tool_call",
        "local_shell_call",
        "apply_patch_call",
        "tool_search_call",
    }
)

type MutableJsonObject = dict[str, Any]


def is_zai_model(model: str | None, model_aliases: ModelAliasMapping | None = None) -> bool:
    return _is_zai_model(model, model_aliases)


def responses_to_zai_chat(
    payload: ResponsesRequest | Mapping[str, JsonValue],
    *,
    model_aliases: ModelAliasMapping | None = None,
) -> JsonObject:
    payload_dict = _payload_to_dict(payload)
    model = payload_dict.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Z.AI requests require a model")
    canonical_model = canonical_zai_model(model, model_aliases)
    if canonical_model is None:
        raise ValueError("Z.AI requests require a GLM-compatible model")

    system_parts: list[str] = []
    instructions = payload_dict.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        system_parts.append(instructions.strip())

    messages = _messages_from_input(payload_dict.get("input"), system_parts)
    if system_parts:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system_parts)})

    chat_payload: MutableJsonObject = {
        "model": canonical_model,
        "messages": messages,
        "stream": True,
    }

    tools = _convert_tools(payload_dict.get("tools"))
    if tools:
        chat_payload["tools"] = tools
        tool_choice = _convert_tool_choice(payload_dict.get("tool_choice"))
        if tool_choice is not None:
            chat_payload["tool_choice"] = tool_choice

    _copy_if_present(payload_dict, chat_payload, "temperature")
    _copy_if_present(payload_dict, chat_payload, "top_p")
    max_output_tokens = payload_dict.get("max_output_tokens")
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        chat_payload["max_completion_tokens"] = max_output_tokens

    text_controls = payload_dict.get("text")
    if is_json_mapping(text_controls):
        text_format = text_controls.get("format")
        if is_json_mapping(text_format):
            response_format = _convert_response_format(text_format)
            if response_format is not None:
                chat_payload["response_format"] = response_format

    return chat_payload


async def stream_zai_responses(
    payload: ResponsesRequest | Mapping[str, JsonValue],
    *,
    api_key: str,
    base_url: str | None = None,
    session: aiohttp.ClientSession | None = None,
    timeout: aiohttp.ClientTimeout | None = None,
    raise_for_status: bool = True,
    model_aliases: ModelAliasMapping | None = None,
) -> AsyncIterator[str]:
    chat_payload = responses_to_zai_chat(payload, model_aliases=model_aliases)
    endpoint = f"{(base_url or ZAI_DEFAULT_BASE_URL).rstrip('/')}{ZAI_CHAT_COMPLETIONS_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    owns_session = session is None
    client = session or aiohttp.ClientSession()
    try:
        async with client.post(endpoint, json=chat_payload, headers=headers, timeout=timeout) as response:
            if response.status >= 400:
                failure_event = await _failure_event_from_response(response)
                if raise_for_status:
                    response_payload = failure_event.get("response")
                    error: Mapping[str, JsonValue] = {}
                    if is_json_mapping(response_payload):
                        maybe_error = response_payload.get("error")
                        if is_json_mapping(maybe_error):
                            error = maybe_error
                    raise ProxyResponseError(
                        response.status,
                        openai_error(
                            str(error.get("code") or "upstream_error"),
                            str(error.get("message") or "Z.AI upstream request failed"),
                            error_type=_error_type_for_status(response.status),
                        ),
                        failure_phase="status",
                        failure_detail=str(error.get("message") or ""),
                        upstream_status_code=response.status,
                        upstream_error_code=str(error.get("code") or "upstream_error"),
                    )
                yield format_sse_event(failure_event)
                return

            model_value = chat_payload.get("model")
            model = model_value if isinstance(model_value, str) else ""
            async for event in iter_zai_response_events(_iter_sse_data(response.content), model):
                yield format_sse_event(event)
    finally:
        if owns_session:
            await client.close()


async def iter_zai_response_events(
    upstream_data: AsyncIterator[str],
    model: str,
) -> AsyncIterator[JsonObject]:
    response_id = f"resp_{uuid4().hex}"
    created_at = int(time.time())
    text_item_id = f"msg_{uuid4().hex}"
    text_started = False
    text_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    output_items: list[Any] = []
    usage: JsonObject | None = None

    yield {
        "type": "response.created",
        "response": _response_object(
            response_id=response_id,
            created_at=created_at,
            model=model,
            status="in_progress",
            output=[],
            usage=None,
        ),
    }

    async for data in upstream_data:
        stripped = data.strip()
        if not stripped:
            continue
        if stripped == "[DONE]":
            break
        try:
            chunk = json.loads(stripped)
        except json.JSONDecodeError:
            yield _failed_event(
                response_id=response_id,
                created_at=created_at,
                model=model,
                code="upstream_error",
                message="Z.AI returned an invalid stream chunk.",
            )
            return
        if not is_json_mapping(chunk):
            continue

        chunk_usage = chunk.get("usage")
        if is_json_mapping(chunk_usage):
            usage = _convert_usage(chunk_usage)

        for choice in _json_list(chunk.get("choices")):
            if not is_json_mapping(choice):
                continue
            delta = choice.get("delta")
            if not is_json_mapping(delta):
                continue

            content = delta.get("content")
            if isinstance(content, str) and content:
                if not text_started:
                    text_started = True
                    yield {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {
                            "id": text_item_id,
                            "type": "message",
                            "status": "in_progress",
                            "role": "assistant",
                            "content": [],
                        },
                    }
                    yield {
                        "type": "response.content_part.added",
                        "item_id": text_item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []},
                    }
                text_parts.append(content)
                yield {
                    "type": "response.output_text.delta",
                    "item_id": text_item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": content,
                }

            for tool_delta in _json_list(delta.get("tool_calls")):
                if not is_json_mapping(tool_delta):
                    continue
                event = _accumulate_tool_call(tool_calls, tool_delta)
                if event is not None:
                    yield event

    if text_started:
        text = "".join(text_parts)
        text_item: MutableJsonObject = {
            "id": text_item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
        output_items.append(text_item)
        yield {
            "type": "response.output_text.done",
            "item_id": text_item_id,
            "output_index": 0,
            "content_index": 0,
            "text": text,
        }
        yield {
            "type": "response.content_part.done",
            "item_id": text_item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": text, "annotations": []},
        }
        yield {
            "type": "response.output_item.done",
            "output_index": len(output_items) - 1,
            "item": text_item,
        }

    for _, call_state in sorted(tool_calls.items()):
        item = _completed_tool_call_item(call_state)
        output_items.append(item)
        yield {
            "type": "response.function_call_arguments.done",
            "item_id": item["id"],
            "output_index": len(output_items) - 1,
            "arguments": item["arguments"],
        }
        yield {
            "type": "response.output_item.done",
            "output_index": len(output_items) - 1,
            "item": item,
        }

    yield {
        "type": "response.completed",
        "response": _response_object(
            response_id=response_id,
            created_at=created_at,
            model=model,
            status="completed",
            output=output_items,
            usage=usage,
        ),
    }


def _payload_to_dict(payload: ResponsesRequest | Mapping[str, JsonValue]) -> MutableJsonObject:
    if isinstance(payload, ResponsesRequest):
        return payload.model_dump(exclude_none=True)
    return dict(payload)


def _messages_from_input(input_value: JsonValue | None, system_parts: list[str]) -> list[JsonObject]:
    if input_value is None:
        return []
    if isinstance(input_value, str):
        return [{"role": "user", "content": input_value}]
    items = input_value if is_json_list(input_value) else [input_value]
    messages: list[JsonObject] = []
    for item in items:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not is_json_mapping(item):
            continue
        item_type = _str_or_empty(item.get("type"))
        role = _str_or_empty(item.get("role"))
        if item_type == "message" or role:
            _append_message_item(messages, item, system_parts)
        elif item_type in _TOOL_CALL_TYPES:
            messages.append(_tool_call_message(item, item_type=item_type))
        elif item_type in _TOOL_OUTPUT_TYPES:
            messages.append(_tool_output_message(item))
    return messages


def _append_message_item(messages: list[JsonObject], item: Mapping[str, JsonValue], system_parts: list[str]) -> None:
    role = _str_or_empty(item.get("role")) or "user"
    content = _content_to_text(item.get("content"))
    if not content:
        return
    if role in {"developer", "system"}:
        system_parts.append(content)
        return
    if role == "tool":
        messages.append(
            {
                "role": "tool",
                "tool_call_id": _str_or_empty(item.get("tool_call_id")) or _str_or_empty(item.get("call_id")),
                "content": content,
            }
        )
        return
    messages.append({"role": role if role in {"user", "assistant"} else "user", "content": content})


def _content_to_text(content: JsonValue | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if is_json_list(content):
        parts = [_content_to_text(part) for part in content]
        return "\n".join(part for part in parts if part)
    if is_json_mapping(content):
        part_type = _str_or_empty(content.get("type"))
        if part_type in _TEXT_PART_TYPES:
            text = content.get("text")
            if isinstance(text, str):
                return text
        for key in ("text", "output", "input"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return str(content)


def _tool_call_message(item: Mapping[str, JsonValue], *, item_type: str) -> JsonObject:
    call_id = _call_id(item)
    name = _tool_name(item, item_type=item_type)
    arguments = _tool_arguments(item, item_type=item_type)
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        ],
    }


def _tool_output_message(item: Mapping[str, JsonValue]) -> JsonObject:
    return {
        "role": "tool",
        "tool_call_id": _call_id(item),
        "content": _content_to_text(item.get("output") or item.get("content")),
    }


def _call_id(item: Mapping[str, JsonValue]) -> str:
    return (
        _str_or_empty(item.get("call_id"))
        or _str_or_empty(item.get("tool_call_id"))
        or _str_or_empty(item.get("id"))
        or f"call_{uuid4().hex}"
    )


def _tool_name(item: Mapping[str, JsonValue], *, item_type: str) -> str:
    if item_type == "local_shell_call":
        return "local_shell"
    if item_type == "tool_search_call":
        return "web_search"
    if item_type == "apply_patch_call":
        return "apply_patch"
    return _str_or_empty(item.get("name")) or _str_or_empty(item.get("tool_name")) or "tool"


def _tool_arguments(item: Mapping[str, JsonValue], *, item_type: str) -> str:
    arguments = item.get("arguments")
    if isinstance(arguments, str):
        return _normalize_json_arguments(arguments)
    if is_json_mapping(arguments) or is_json_list(arguments):
        return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    if item_type == "local_shell_call":
        action = item.get("action")
        if is_json_mapping(action):
            return json.dumps(action, ensure_ascii=False, separators=(",", ":"))
    if item_type == "tool_search_call":
        query = item.get("query") or item.get("action")
        return json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    return "{}"


def _convert_tools(value: JsonValue | None) -> list[JsonObject]:
    tools: list[JsonObject] = []
    for tool in _json_list(value):
        if not is_json_mapping(tool):
            continue
        if tool.get("type") != "function":
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        function: MutableJsonObject = {"name": name}
        description = tool.get("description")
        if isinstance(description, str):
            function["description"] = description
        parameters = tool.get("parameters")
        if is_json_mapping(parameters):
            function["parameters"] = dict(parameters)
        strict = tool.get("strict")
        if isinstance(strict, bool):
            function["strict"] = strict
        tools.append({"type": "function", "function": function})
    return tools


def _convert_tool_choice(value: JsonValue | None) -> JsonValue | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not is_json_mapping(value):
        return None
    if value.get("type") == "function":
        name = value.get("name")
        if isinstance(name, str) and name:
            return {"type": "function", "function": {"name": name}}
    return None


def _convert_response_format(text_format: Mapping[str, JsonValue]) -> JsonObject | None:
    format_type = text_format.get("type")
    if format_type in {"json_object", "json_schema"}:
        response_format: MutableJsonObject = {"type": format_type}
        if format_type == "json_schema":
            name = text_format.get("name")
            schema = text_format.get("schema")
            json_schema: MutableJsonObject = {}
            if isinstance(name, str):
                json_schema["name"] = name
            if is_json_mapping(schema):
                json_schema["schema"] = dict(schema)
            if json_schema:
                response_format["json_schema"] = json_schema
        return response_format
    return None


def _copy_if_present(source: Mapping[str, JsonValue], target: MutableJsonObject, key: str) -> None:
    value = source.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        target[key] = value


def _accumulate_tool_call(tool_calls: dict[int, dict[str, Any]], delta: Mapping[str, JsonValue]) -> JsonObject | None:
    index = delta.get("index")
    if not isinstance(index, int):
        index = len(tool_calls)
    state = tool_calls.setdefault(
        index,
        {
            "id": _str_or_empty(delta.get("id")) or f"call_{uuid4().hex}",
            "name": "",
            "arguments": [],
            "started": False,
        },
    )
    if isinstance(delta.get("id"), str):
        state["id"] = delta["id"]
    function = delta.get("function")
    if is_json_mapping(function):
        name = function.get("name")
        if isinstance(name, str) and name:
            state["name"] = name
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            state["arguments"].append(arguments)

    if state["started"]:
        return None
    state["started"] = True
    return {
        "type": "response.output_item.added",
        "output_index": index,
        "item": {
            "id": state["id"],
            "type": "function_call",
            "status": "in_progress",
            "call_id": state["id"],
            "name": state["name"] or "tool",
            "arguments": "",
        },
    }


def _completed_tool_call_item(state: Mapping[str, Any]) -> JsonObject:
    arguments = _normalize_json_arguments("".join(state.get("arguments") or []))
    item_id = str(state.get("id") or f"call_{uuid4().hex}")
    return {
        "id": item_id,
        "type": "function_call",
        "status": "completed",
        "call_id": item_id,
        "name": str(state.get("name") or "tool"),
        "arguments": arguments,
    }


def _normalize_json_arguments(raw: str) -> str:
    text = raw.strip()
    if not text:
        return "{}"
    parsed = _try_json_loads(text)
    if parsed is not None:
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    repaired = _repair_json_text(text)
    parsed = _try_json_loads(repaired)
    if parsed is not None:
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"_raw": raw}, ensure_ascii=False, separators=(",", ":"))


def _repair_json_text(text: str) -> str:
    repaired = text.rstrip()
    while repaired.endswith(","):
        repaired = repaired[:-1].rstrip()
    stack: list[str] = []
    in_string = False
    escape = False
    for char in repaired:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
    if in_string:
        repaired += '"'
    repaired += "".join(reversed(stack))
    repaired = repaired.replace(",}", "}").replace(",]", "]")
    return repaired


def _try_json_loads(text: str) -> JsonValue | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def _iter_sse_data(content: aiohttp.StreamReader) -> AsyncIterator[str]:
    buffer = ""
    async for raw_chunk in content.iter_chunked(4096):
        buffer += raw_chunk.decode("utf-8", errors="replace")
        while True:
            marker = _next_sse_separator(buffer)
            if marker is None:
                break
            index, size = marker
            block = buffer[:index]
            buffer = buffer[index + size :]
            data = _data_from_sse_block(block)
            if data is not None:
                yield data
    data = _data_from_sse_block(buffer)
    if data is not None:
        yield data


def _next_sse_separator(buffer: str) -> tuple[int, int] | None:
    candidates = [
        (idx, len(separator))
        for separator in ("\r\n\r\n", "\n\n", "\r\r")
        if (idx := buffer.find(separator)) >= 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


def _data_from_sse_block(block: str) -> str | None:
    lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip("\r")
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            lines.append(line[5:].lstrip())
    if not lines:
        return None
    return "\n".join(lines)


async def _failure_event_from_response(response: aiohttp.ClientResponse) -> JsonObject:
    message = "Z.AI upstream request failed."
    code = "upstream_error"
    try:
        payload = await response.json(content_type=None)
    except Exception:
        payload = None
    if is_json_mapping(payload):
        error = payload.get("error")
        if is_json_mapping(error):
            error_message = error.get("message")
            error_code = error.get("code") or error.get("type")
            if isinstance(error_message, str) and error_message.strip():
                message = error_message.strip()
            if isinstance(error_code, str) and error_code.strip():
                code = error_code.strip()
    if response.status == 429:
        code = "rate_limit_exceeded"
    elif response.status in {401, 403}:
        code = "authentication_error"
    return _failed_event(
        response_id=f"resp_{uuid4().hex}",
        created_at=int(time.time()),
        model="",
        code=code,
        message=message,
    )


def _failed_event(
    *,
    response_id: str,
    created_at: int,
    model: str,
    code: str,
    message: str,
) -> JsonObject:
    return {
        "type": "response.failed",
        "response": _response_object(
            response_id=response_id,
            created_at=created_at,
            model=model,
            status="failed",
            output=[],
            usage=None,
            error={"code": code, "message": message},
        ),
    }


def _response_object(
    *,
    response_id: str,
    created_at: int,
    model: str,
    status: str,
    output: list[Any],
    usage: JsonObject | None,
    error: JsonObject | None = None,
) -> JsonObject:
    response: MutableJsonObject = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "usage": usage,
    }
    if error is not None:
        response["error"] = error
    return response


def _convert_usage(usage: Mapping[str, JsonValue]) -> JsonObject:
    input_tokens = _int_or_zero(usage.get("prompt_tokens"))
    output_tokens = _int_or_zero(usage.get("completion_tokens"))
    total_tokens = _int_or_zero(usage.get("total_tokens")) or input_tokens + output_tokens
    converted: MutableJsonObject = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    completion_details = usage.get("completion_tokens_details")
    if is_json_mapping(completion_details):
        reasoning_tokens = _int_or_zero(completion_details.get("reasoning_tokens"))
        if reasoning_tokens:
            converted["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return converted


def _int_or_zero(value: JsonValue | None) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _json_list(value: JsonValue | None) -> list[JsonValue]:
    return list(value) if is_json_list(value) else []


def _str_or_empty(value: JsonValue | None) -> str:
    return value if isinstance(value, str) else ""


def _error_type_for_status(status: int) -> str:
    if status == 429:
        return "rate_limit_error"
    if status in {400, 422}:
        return "invalid_request_error"
    if status in {401, 403}:
        return "authentication_error"
    return "server_error"
