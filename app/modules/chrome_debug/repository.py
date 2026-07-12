from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.utils.time import utcnow
from app.db.models import (
    ApiKey,
    ChromeDebugAgentToken,
    ChromeDebugApiKeyGrant,
    ChromeDebugAuditEvent,
    ChromeDebugBrowser,
    ChromeDebugRelayToken,
    ChromeDebugSession,
)


class ChromeDebugRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_grants(self) -> list[tuple[ApiKey, ChromeDebugApiKeyGrant | None, int]]:
        browser_count = (
            select(
                ChromeDebugBrowser.api_key_id.label("api_key_id"),
                func.count(ChromeDebugBrowser.id).label("browser_count"),
            )
            .where(ChromeDebugBrowser.is_revoked.is_(False))
            .group_by(ChromeDebugBrowser.api_key_id)
            .subquery()
        )
        result = await self._session.execute(
            select(ApiKey, ChromeDebugApiKeyGrant, func.coalesce(browser_count.c.browser_count, 0))
            .outerjoin(ChromeDebugApiKeyGrant, ChromeDebugApiKeyGrant.api_key_id == ApiKey.id)
            .outerjoin(browser_count, browser_count.c.api_key_id == ApiKey.id)
            .order_by(ApiKey.created_at.desc())
        )
        return [(api_key, grant, int(count or 0)) for api_key, grant, count in result.all()]

    async def set_grant(self, api_key_id: str, *, enabled: bool) -> bool:
        api_key = await self._session.get(ApiKey, api_key_id)
        if api_key is None:
            return False
        grant = await self._session.get(ChromeDebugApiKeyGrant, api_key_id)
        if enabled and grant is None:
            self._session.add(ChromeDebugApiKeyGrant(api_key_id=api_key_id))
        elif not enabled and grant is not None:
            await self._session.delete(grant)
        await self._session.commit()
        return True

    async def has_grant(self, api_key_id: str) -> bool:
        return await self._session.get(ChromeDebugApiKeyGrant, api_key_id) is not None

    async def upsert_browser(
        self,
        *,
        browser_id: str,
        api_key_id: str,
        label: str,
        instance_id: str | None,
        user_agent: str | None,
        extension_version: str | None,
    ) -> ChromeDebugBrowser:
        now = utcnow()
        browser = await self._session.get(ChromeDebugBrowser, browser_id)
        if browser is None:
            browser = ChromeDebugBrowser(
                id=browser_id,
                api_key_id=api_key_id,
                label=label,
                instance_id=instance_id,
                user_agent=user_agent,
                extension_version=extension_version,
                last_seen_at=now,
                disconnected_at=None,
            )
            self._session.add(browser)
        else:
            browser.api_key_id = api_key_id
            browser.label = label
            browser.instance_id = instance_id
            browser.user_agent = user_agent
            browser.extension_version = extension_version
            browser.is_revoked = False
            browser.last_seen_at = now
            browser.disconnected_at = None
        await self._session.commit()
        await self._session.refresh(browser)
        return browser

    async def list_browsers(self, *, api_key_id: str | None = None) -> list[ChromeDebugBrowser]:
        stmt = (
            select(ChromeDebugBrowser)
            .options(selectinload(ChromeDebugBrowser.grant).selectinload(ChromeDebugApiKeyGrant.api_key))
            .where(ChromeDebugBrowser.is_revoked.is_(False))
            .order_by(ChromeDebugBrowser.last_seen_at.desc().nullslast(), ChromeDebugBrowser.created_at.desc())
        )
        if api_key_id is not None:
            stmt = stmt.where(ChromeDebugBrowser.api_key_id == api_key_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_browser(self, browser_id: str) -> ChromeDebugBrowser | None:
        return await self._session.get(ChromeDebugBrowser, browser_id)

    async def revoke_browser(self, browser_id: str) -> bool:
        browser = await self._session.get(ChromeDebugBrowser, browser_id)
        if browser is None:
            return False
        browser.is_revoked = True
        browser.disconnected_at = utcnow()
        await self._session.commit()
        return True

    async def mark_browser_seen(self, browser_id: str) -> None:
        await self._session.execute(
            update(ChromeDebugBrowser)
            .where(ChromeDebugBrowser.id == browser_id)
            .values(last_seen_at=utcnow(), disconnected_at=None)
        )
        await self._session.commit()

    async def mark_browser_disconnected(self, browser_id: str) -> None:
        await self._session.execute(
            update(ChromeDebugBrowser).where(ChromeDebugBrowser.id == browser_id).values(disconnected_at=utcnow())
        )
        await self._session.commit()

    async def create_agent_token(
        self,
        *,
        token_hash: str,
        browser_id: str,
        api_key_id: str,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            ChromeDebugAgentToken(
                token_hash=token_hash,
                browser_id=browser_id,
                api_key_id=api_key_id,
                expires_at=expires_at,
            )
        )
        await self._session.commit()

    async def consume_agent_token(self, token_hash: str) -> ChromeDebugAgentToken | None:
        token = await self._session.get(ChromeDebugAgentToken, token_hash)
        if token is None or token.used_at is not None or token.expires_at <= utcnow():
            return None
        token.used_at = utcnow()
        await self._session.commit()
        await self._session.refresh(token)
        return token

    async def create_relay_token(
        self,
        *,
        token_hash: str,
        browser_id: str,
        api_key_id: str,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            ChromeDebugRelayToken(
                token_hash=token_hash,
                browser_id=browser_id,
                api_key_id=api_key_id,
                expires_at=expires_at,
            )
        )
        await self._session.commit()

    async def get_valid_relay_token(self, token_hash: str) -> ChromeDebugRelayToken | None:
        token = await self._session.get(ChromeDebugRelayToken, token_hash)
        if token is None or token.revoked_at is not None or token.expires_at <= utcnow():
            return None
        token.last_used_at = utcnow()
        await self._session.commit()
        await self._session.refresh(token)
        return token

    async def create_session(
        self,
        *,
        session_id: str,
        browser_id: str,
        api_key_id: str,
        target_id: str,
    ) -> None:
        self._session.add(
            ChromeDebugSession(
                id=session_id,
                browser_id=browser_id,
                api_key_id=api_key_id,
                target_id=target_id,
            )
        )
        await self._session.commit()

    async def close_session(self, session_id: str) -> None:
        await self._session.execute(
            update(ChromeDebugSession)
            .where(ChromeDebugSession.id == session_id)
            .values(state="closed", closed_at=utcnow(), last_seen_at=utcnow())
        )
        await self._session.commit()

    async def audit(
        self,
        event_type: str,
        *,
        api_key_id: str | None = None,
        browser_id: str | None = None,
        session_id: str | None = None,
        target_id: str | None = None,
        actor_ip: str | None = None,
        details_json: str | None = None,
    ) -> None:
        self._session.add(
            ChromeDebugAuditEvent(
                event_type=event_type,
                api_key_id=api_key_id,
                browser_id=browser_id,
                session_id=session_id,
                target_id=target_id,
                actor_ip=actor_ip,
                details_json=details_json,
            )
        )
        await self._session.commit()

    async def purge_expired_tokens(self) -> None:
        now = utcnow()
        await self._session.execute(delete(ChromeDebugAgentToken).where(ChromeDebugAgentToken.expires_at <= now))
        await self._session.execute(
            delete(ChromeDebugRelayToken).where(ChromeDebugRelayToken.expires_at <= now)
        )
        await self._session.commit()
