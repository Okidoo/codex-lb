from __future__ import annotations

import logging
from collections.abc import Mapping

from app.modules.proxy.repo_bundle import ProxyRepositories


async def load_model_aliases(
    repos: ProxyRepositories,
    *,
    logger: logging.Logger | None = None,
) -> dict[str, str]:
    model_aliases_repo = getattr(repos, "model_aliases", None)
    if model_aliases_repo is None:
        return {}
    list_enabled_mapping = getattr(model_aliases_repo, "list_enabled_mapping", None)
    if not callable(list_enabled_mapping):
        return {}
    try:
        aliases = await list_enabled_mapping()
    except Exception:
        if logger is not None:
            logger.warning("Failed load model aliases; using direct model routing", exc_info=True)
        return {}
    if not isinstance(aliases, Mapping):
        return {}
    return {str(source): str(target) for source, target in aliases.items()}
