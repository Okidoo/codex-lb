from __future__ import annotations

from app.core.model_aliases import normalize_model_slug
from app.db.models import ModelAlias
from app.modules.model_aliases.repository import ModelAliasesRepository


class ModelAliasValidationError(ValueError):
    pass


class ModelAliasesService:
    def __init__(self, repository: ModelAliasesRepository) -> None:
        self._repository = repository

    async def list_aliases(self) -> list[ModelAlias]:
        return await self._repository.list_aliases()

    async def enabled_mapping(self) -> dict[str, str]:
        return await self._repository.list_enabled_mapping()

    async def upsert_alias(self, *, source_model: str, target_model: str, enabled: bool) -> ModelAlias:
        source = _normalize_user_model(source_model, field_name="source model")
        target = _normalize_user_model(target_model, field_name="target model")
        if source == target:
            raise ModelAliasValidationError("Source and target models must be different")
        return await self._repository.upsert(source_model=source, target_model=target, enabled=enabled)

    async def delete_alias(self, alias_id: str) -> bool:
        return await self._repository.delete(alias_id)


def _normalize_user_model(value: str, *, field_name: str) -> str:
    normalized = normalize_model_slug(value)
    if normalized is None:
        raise ModelAliasValidationError(f"{field_name.capitalize()} is required")
    if any(character.isspace() for character in normalized):
        raise ModelAliasValidationError(f"{field_name.capitalize()} must not contain whitespace")
    return normalized
