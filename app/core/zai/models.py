from __future__ import annotations

from app.core.model_aliases import ModelAliasMapping, resolve_model_alias


def canonical_zai_model(model: str | None, aliases: ModelAliasMapping | None = None) -> str | None:
    resolved = resolve_model_alias(model, aliases)
    if resolved is None:
        return None
    if resolved.startswith("glm-"):
        return resolved
    return None


def is_zai_model(model: str | None, aliases: ModelAliasMapping | None = None) -> bool:
    return canonical_zai_model(model, aliases) is not None
