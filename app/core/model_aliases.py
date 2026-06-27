from __future__ import annotations

from collections.abc import Mapping

ModelAliasMapping = Mapping[str, str]

DEFAULT_MODEL_ALIAS_SOURCE = "gpt-5.2"
DEFAULT_MODEL_ALIAS_TARGET = "glm-5.2"


def normalize_model_slug(model: str | None) -> str | None:
    if not isinstance(model, str):
        return None
    normalized = model.strip().lower()
    return normalized or None


def resolve_model_alias(model: str | None, aliases: ModelAliasMapping | None = None) -> str | None:
    current = normalize_model_slug(model)
    if current is None:
        return None
    if aliases is None:
        return current

    visited: set[str] = set()
    for _ in range(8):
        if current in visited:
            return current
        visited.add(current)
        target = normalize_model_slug(aliases.get(current))
        if target is None:
            return current
        current = target
    return current
