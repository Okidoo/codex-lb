from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)
AGENT_HEARTBEAT_TIMEOUT_SECONDS = 45
RELAY_IDLE_TIMEOUT_SECONDS = 300


class ChromeDebugBridgeError(RuntimeError):
    pass


@dataclass(slots=True)
class RelaySession:
    session_id: str
    target_id: str
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send_cdp(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(payload)


class AgentConnection:
    def __init__(self, *, browser_id: str, api_key_id: str, websocket: WebSocket) -> None:
        self.browser_id = browser_id
        self.api_key_id = api_key_id
        self.websocket = websocket
        self.targets: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, RelaySession] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()
        self._closed = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set()

    async def close(self, *, code: int = 1000, reason: str = "replaced") -> None:
        self._closed.set()
        for session in list(self.sessions.values()):
            with contextlib.suppress(Exception):
                await session.websocket.close(code=1011, reason="Chrome debug agent disconnected")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ChromeDebugBridgeError(reason))
        self._pending.clear()
        with contextlib.suppress(Exception):
            await self.websocket.close(code=code, reason=reason)

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def request_control(
        self,
        message_type: str,
        *,
        timeout: float = 10.0,
        **payload: Any,
    ) -> dict[str, Any]:
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self.send_json({"type": message_type, "id": request_id, **payload})
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def refresh_targets(self) -> list[dict[str, Any]]:
        try:
            response = await self.request_control("list_targets", timeout=5.0)
        except Exception:
            return list(self.targets.values())
        targets = response.get("targets")
        if isinstance(targets, list):
            self.update_targets(targets)
        return list(self.targets.values())

    def update_targets(self, targets: list[Any]) -> None:
        normalized: dict[str, dict[str, Any]] = {}
        for item in targets:
            if not isinstance(item, dict):
                continue
            target_id = str(item.get("id") or item.get("targetId") or item.get("tabId") or "").strip()
            if not target_id:
                continue
            normalized[target_id] = {**item, "id": target_id}
        self.targets = normalized

    async def attach(self, session: RelaySession) -> None:
        if any(existing.target_id == session.target_id for existing in self.sessions.values()):
            raise ChromeDebugBridgeError("Target already has an active controller")
        if session.target_id not in self.targets:
            await self.refresh_targets()
        if session.target_id not in self.targets:
            raise ChromeDebugBridgeError("Target is not available")
        await self.request_control(
            "attach",
            sessionId=session.session_id,
            targetId=session.target_id,
            timeout=10.0,
        )
        self.sessions[session.session_id] = session

    async def detach(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        with contextlib.suppress(Exception):
            await self.request_control("detach", sessionId=session_id, targetId=session.target_id, timeout=5.0)

    async def send_command(self, *, session_id: str, message: dict[str, Any]) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            raise ChromeDebugBridgeError("CDP session is no longer attached")
        await self.send_json(
            {
                "type": "cdp_command",
                "sessionId": session_id,
                "targetId": session.target_id,
                "requestId": message.get("id"),
                "method": message.get("method"),
                "params": message.get("params") or {},
            }
        )

    async def handle_agent_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "heartbeat":
            return
        if message_type == "targets":
            targets = message.get("targets")
            if isinstance(targets, list):
                self.update_targets(targets)
            return
        if message_type == "control_response":
            request_id = str(message.get("id") or "")
            future = self._pending.get(request_id)
            if future is None or future.done():
                return
            if message.get("ok") is False:
                future.set_exception(ChromeDebugBridgeError(str(message.get("error") or "Chrome agent error")))
            else:
                future.set_result(message)
            return
        if message_type == "cdp_response":
            session = self.sessions.get(str(message.get("sessionId") or ""))
            if session is None:
                return
            response_id = message.get("requestId")
            if message.get("ok") is False:
                await session.send_cdp(
                    {
                        "id": response_id,
                        "error": message.get("error")
                        if isinstance(message.get("error"), dict)
                        else {"code": -32000, "message": str(message.get("error") or "Chrome agent error")},
                    }
                )
            else:
                await session.send_cdp({"id": response_id, "result": message.get("result") or {}})
            return
        if message_type == "cdp_event":
            session = self.sessions.get(str(message.get("sessionId") or ""))
            if session is None:
                return
            method = message.get("method")
            if not isinstance(method, str) or not method:
                return
            await session.send_cdp({"method": method, "params": message.get("params") or {}})
            return
        logger.debug("Ignoring unknown chrome debug agent message type=%r", message_type)


class ChromeDebugHub:
    def __init__(self) -> None:
        self._agents: dict[str, AgentConnection] = {}
        self._lock = asyncio.Lock()

    async def register_agent(self, *, browser_id: str, api_key_id: str, websocket: WebSocket) -> AgentConnection:
        agent = AgentConnection(browser_id=browser_id, api_key_id=api_key_id, websocket=websocket)
        async with self._lock:
            previous = self._agents.get(browser_id)
            self._agents[browser_id] = agent
        if previous is not None:
            await previous.close(code=4000, reason="browser reconnected")
        return agent

    async def unregister_agent(self, browser_id: str, agent: AgentConnection) -> None:
        async with self._lock:
            if self._agents.get(browser_id) is agent:
                self._agents.pop(browser_id, None)
        await agent.close(reason="agent disconnected")

    def get_agent(self, browser_id: str) -> AgentConnection | None:
        agent = self._agents.get(browser_id)
        if agent is None or agent.is_closed:
            return None
        return agent

    def is_online(self, browser_id: str) -> bool:
        return self.get_agent(browser_id) is not None

    async def targets_for_browser(self, browser_id: str) -> list[dict[str, Any]]:
        agent = self.get_agent(browser_id)
        if agent is None:
            return []
        return await agent.refresh_targets()

    async def run_agent(self, agent: AgentConnection) -> None:
        try:
            while True:
                message = await asyncio.wait_for(
                    agent.websocket.receive_json(),
                    timeout=AGENT_HEARTBEAT_TIMEOUT_SECONDS,
                )
                if isinstance(message, dict):
                    await agent.handle_agent_message(message)
        except TimeoutError:
            logger.warning("Chrome debug agent heartbeat timed out browser_id=%s", agent.browser_id)
            with contextlib.suppress(Exception):
                await agent.close(code=4002, reason="heartbeat timeout")
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Chrome debug agent crashed browser_id=%s", agent.browser_id)
        finally:
            await self.unregister_agent(agent.browser_id, agent)

    async def run_relay(self, *, browser_id: str, session_id: str, target_id: str, websocket: WebSocket) -> None:
        agent = self.get_agent(browser_id)
        if agent is None:
            await websocket.close(code=1013, reason="Chrome debug browser is offline")
            return
        session = RelaySession(session_id=session_id, target_id=target_id, websocket=websocket)
        try:
            await agent.attach(session)
            while True:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=RELAY_IDLE_TIMEOUT_SECONDS,
                )
                if not isinstance(message, dict):
                    continue
                method = message.get("method")
                if not isinstance(method, str) or not method:
                    await session.send_cdp(
                        {
                            "id": message.get("id"),
                            "error": {"code": -32600, "message": "Invalid CDP request"},
                        }
                    )
                    continue
                await agent.send_command(session_id=session_id, message=message)
        except TimeoutError:
            with contextlib.suppress(Exception):
                await websocket.close(code=1000, reason="Chrome debug relay idle timeout")
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {
                        "error": {
                            "code": -32000,
                            "message": str(exc),
                        }
                    }
                )
        finally:
            await agent.detach(session_id)


chrome_debug_hub = ChromeDebugHub()
