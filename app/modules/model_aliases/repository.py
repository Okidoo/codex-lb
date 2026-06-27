from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils.time import utcnow
from app.db.models import ModelAlias
from app.db.session import sqlite_writer_section


class ModelAliasesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def list_aliases(self) -> list[ModelAlias]:
        result = await self._session.execute(select(ModelAlias).order_by(ModelAlias.source_model))
        return list(result.scalars().all())

    async def list_enabled_mapping(self) -> dict[str, str]:
        result = await self._session.execute(
            select(ModelAlias).where(ModelAlias.enabled.is_(True)).order_by(ModelAlias.source_model)
        )
        return {row.source_model: row.target_model for row in result.scalars().all()}

    async def get_by_id(self, alias_id: str) -> ModelAlias | None:
        return await self._session.get(ModelAlias, alias_id)

    async def get_by_source(self, source_model: str) -> ModelAlias | None:
        result = await self._session.execute(
            select(ModelAlias).where(ModelAlias.source_model == source_model).limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert(self, *, source_model: str, target_model: str, enabled: bool) -> ModelAlias:
        async with sqlite_writer_section():
            row = await self.get_by_source(source_model)
            if row is None:
                row = ModelAlias(
                    id=str(uuid.uuid4()),
                    source_model=source_model,
                    target_model=target_model,
                    enabled=enabled,
                )
                self._session.add(row)
            else:
                row.target_model = target_model
                row.enabled = enabled
                row.updated_at = utcnow()
            await self._session.commit()
            await self._session.refresh(row)
            return row

    async def delete(self, alias_id: str) -> bool:
        async with sqlite_writer_section():
            row = await self.get_by_id(alias_id)
            if row is None:
                return False
            await self._session.delete(row)
            await self._session.commit()
            return True
