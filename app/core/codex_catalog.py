from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from app.core.config.settings import get_settings
from app.core.openai.model_registry import UpstreamModel, get_model_registry, is_public_model
from app.core.types import JsonValue

CODEX_LB_CATALOG_FILENAME = "codex-lb-catalog.json"
CODEX_LB_MODELS_CACHE_FILENAME = "models_cache.json"
CODEX_LB_PROVIDER_NAME = "codex-lb"
CODEX_LB_PROVIDER_DISPLAY_NAME = "Codex LB"
CODEX_LB_DEFAULT_BASE_URL = "https://codex.okidoo.co/backend-api/codex"

_CATALOG_FAST_TIER_KEYS = {
    "additional_speed_tiers",
    "service_tier",
    "service_tiers",
    "default_service_tier",
}

_CODEX_CATALOG_EXCLUDED_MODEL_SLUGS = {
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
}

_CATALOG_SKIP_KEYS = {
    "slug",
    "display_name",
    "description",
    "base_instructions",
    "default_reasoning_level",
    "supported_reasoning_levels",
    "supported_in_api",
    "priority",
    "minimal_client_version",
    "supports_reasoning_summaries",
    "support_verbosity",
    "default_verbosity",
    "supports_parallel_tool_calls",
    "context_window",
    "input_modalities",
    "available_in_plans",
    "prefer_websockets",
    "visibility",
}


@dataclass(frozen=True)
class CodexSetupConfig:
    base_url: str = CODEX_LB_DEFAULT_BASE_URL
    provider_name: str = CODEX_LB_PROVIDER_NAME
    provider_display_name: str = CODEX_LB_PROVIDER_DISPLAY_NAME
    catalog_filename: str = CODEX_LB_CATALOG_FILENAME
    models_cache_filename: str = CODEX_LB_MODELS_CACHE_FILENAME


def build_codex_catalog_payload(*, base_url: str | None = None) -> dict[str, JsonValue]:
    registry = get_model_registry()
    models: list[dict[str, JsonValue]] = [
        _to_catalog_entry(model)
        for model in registry.get_models_with_fallback().values()
        if is_public_model(model, None) and model.slug not in _CODEX_CATALOG_EXCLUDED_MODEL_SLUGS
    ]
    models.sort(key=lambda item: (str(item.get("display_name", "")), str(item.get("slug", ""))))
    return {"models": cast(JsonValue, models)}


def build_codex_catalog_json(*, base_url: str | None = None) -> str:
    return json.dumps(build_codex_catalog_payload(base_url=base_url), ensure_ascii=False, indent=2) + "\n"


def build_codex_setup_summary(*, base_url: str | None = None) -> dict[str, JsonValue]:
    payload = build_codex_catalog_payload(base_url=base_url)
    models = payload.get("models")
    model_count = len(models) if isinstance(models, list) else 0
    origin = _origin_from_backend_base_url(base_url or CODEX_LB_DEFAULT_BASE_URL)
    return {
        "provider": CODEX_LB_PROVIDER_NAME,
        "base_url": base_url or CODEX_LB_DEFAULT_BASE_URL,
        "catalog_path": f"$CODEX_HOME/{CODEX_LB_CATALOG_FILENAME}",
        "models_cache_path": f"$CODEX_HOME/{CODEX_LB_MODELS_CACHE_FILENAME}",
        "model_count": model_count,
        "install_command": f"curl -fsSL {shell_quote(f'{origin}/codex/setup/install.sh')} | sh",
        "uninstall_command": f"curl -fsSL {shell_quote(f'{origin}/codex/setup/uninstall.sh')} | sh",
    }


def build_install_script(*, public_origin: str, config: CodexSetupConfig | None = None) -> str:
    cfg = config or CodexSetupConfig(base_url=f"{public_origin.rstrip('/')}/backend-api/codex")
    catalog_url = f"{public_origin.rstrip('/')}/codex/catalog.json"
    return f"""#!/bin/sh
set -eu

CODEX_HOME="${{CODEX_HOME:-$HOME/.codex}}"
CONFIG_PATH="$CODEX_HOME/config.toml"
CATALOG_PATH="$CODEX_HOME/{cfg.catalog_filename}"
CACHE_PATH="$CODEX_HOME/{cfg.models_cache_filename}"
BACKUP_PATH="$CONFIG_PATH.backup-codex-lb-$(date +%Y%m%d%H%M%S)"

mkdir -p "$CODEX_HOME"
touch "$CONFIG_PATH"
cp "$CONFIG_PATH" "$BACKUP_PATH"

tmp_config="$(mktemp)"
tmp_catalog="$(mktemp)"
curl -fsSL {shell_quote(catalog_url)} -o "$tmp_catalog"

python3 - "$CONFIG_PATH" "$tmp_config" "$CATALOG_PATH" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
catalog_path = sys.argv[3]
content = config_path.read_text() if config_path.exists() else ""
lines = content.splitlines()

def strip_managed(lines):
    first_table = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
    out = []
    in_managed = False
    in_codex_lb_provider = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# Auto-injected by codex-lb":
            in_managed = True
            continue
        if stripped == "[model_providers.codex-lb]":
            in_codex_lb_provider = True
            continue
        if in_codex_lb_provider and stripped.startswith("["):
            in_codex_lb_provider = False
        if in_managed and stripped.startswith("[") and stripped != "[model_providers.codex-lb]":
            in_managed = False
        if in_managed or in_codex_lb_provider:
            continue
        if index < first_table and (
            stripped.startswith("model_provider =") or stripped.startswith("model_catalog_json =")
        ):
            continue
        out.append(line)
    return out

lines = strip_managed(lines)
first_table = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
root = [
    'model_provider = "{cfg.provider_name}"',
    f'model_catalog_json = "{{catalog_path}}"',
]
lines[first_table:first_table] = root + ([""] if first_table < len(lines) else [])
block = [
    "",
    "# Auto-injected by codex-lb",
    "[model_providers.codex-lb]",
    f'name = "{cfg.provider_display_name}"',
    f'base_url = "{cfg.base_url}"',
    'wire_api = "responses"',
    "supports_websockets = true",
    "requires_openai_auth = true",
]
out_path.write_text("\\n".join(lines).rstrip() + "\\n" + "\\n".join(block) + "\\n")
PY

mv "$tmp_config" "$CONFIG_PATH"
mv "$tmp_catalog" "$CATALOG_PATH"
rm -f "$CACHE_PATH"

cat <<EOF
Codex LB config installed.
Backup: $BACKUP_PATH
Catalog: $CATALOG_PATH
EOF
"""


def build_uninstall_script(config: CodexSetupConfig | None = None) -> str:
    cfg = config or CodexSetupConfig()
    return f"""#!/bin/sh
set -eu

CODEX_HOME="${{CODEX_HOME:-$HOME/.codex}}"
CONFIG_PATH="$CODEX_HOME/config.toml"
CATALOG_PATH="$CODEX_HOME/{cfg.catalog_filename}"
CACHE_PATH="$CODEX_HOME/{cfg.models_cache_filename}"
BACKUP_PATH="$CONFIG_PATH.backup-before-codex-lb-uninstall-$(date +%Y%m%d%H%M%S)"

if [ -f "$CONFIG_PATH" ]; then
  cp "$CONFIG_PATH" "$BACKUP_PATH"
  tmp_config="$(mktemp)"
  python3 - "$CONFIG_PATH" "$tmp_config" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
lines = config_path.read_text().splitlines()
out = []
in_managed = False
in_codex_lb_provider = False
for line in lines:
    stripped = line.strip()
    if stripped == "# Auto-injected by codex-lb":
        in_managed = True
        continue
    if stripped == "[model_providers.codex-lb]":
        in_codex_lb_provider = True
        continue
    if in_codex_lb_provider and stripped.startswith("["):
        in_codex_lb_provider = False
    if in_managed and stripped.startswith("[") and stripped != "[model_providers.codex-lb]":
        in_managed = False
    if in_managed or in_codex_lb_provider:
        continue
    if stripped == 'model_provider = "codex-lb"':
        continue
    if stripped.startswith("model_catalog_json =") and "codex-lb-catalog.json" in stripped:
        continue
    out.append(line)
out_path.write_text("\\n".join(out).rstrip() + "\\n")
PY
  mv "$tmp_config" "$CONFIG_PATH"
  echo "Codex LB config removed. Backup: $BACKUP_PATH"
fi

rm -f "$CATALOG_PATH" "$CACHE_PATH"
"""


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _origin_from_backend_base_url(base_url: str) -> str:
    return base_url.rstrip("/").rsplit("/backend-api/codex", 1)[0]


def _to_catalog_entry(model: UpstreamModel) -> dict[str, JsonValue]:
    entry = cast(dict[str, JsonValue], {
        "slug": model.slug,
        "display_name": model.display_name,
        "description": model.description,
        "base_instructions": model.base_instructions,
        "default_reasoning_level": model.default_reasoning_level,
        "supported_reasoning_levels": [
            {"effort": level.effort, "description": level.description}
            for level in model.supported_reasoning_levels
        ],
        "supported_in_api": model.supported_in_api,
        "priority": model.priority,
        "minimal_client_version": model.minimal_client_version,
        "supports_reasoning_summaries": model.supports_reasoning_summaries,
        "support_verbosity": model.support_verbosity,
        "default_verbosity": model.default_verbosity,
        "supports_parallel_tool_calls": model.supports_parallel_tool_calls,
        "context_window": _effective_context_window(model),
        "input_modalities": list(model.input_modalities),
        "available_in_plans": sorted(model.available_in_plans),
        "prefer_websockets": model.prefer_websockets,
        "visibility": _model_visibility(model),
        "shell_type": "shell_command",
        "availability_nux": None,
        "max_context_window": _effective_context_window(model),
        "auto_compact_token_limit": int(_effective_context_window(model) * 0.9),
        "supports_image_detail_original": False,
        "experimental_supported_tools": [],
        "apply_patch_tool_type": "freeform",
        "truncation_policy": {"mode": "tokens", "limit": 10000},
    })
    for key, value in model.raw.items():
        if key in _CATALOG_SKIP_KEYS:
            continue
        if _is_zai_catalog_model(model) and key in _CATALOG_FAST_TIER_KEYS:
            continue
        if _is_json_like(value):
            entry[key] = value
    if _is_zai_catalog_model(model):
        for key in _CATALOG_FAST_TIER_KEYS:
            entry.pop(key, None)
    return entry


def _effective_context_window(model: UpstreamModel) -> int:
    return get_settings().model_context_window_overrides.get(model.slug, model.context_window)


def _model_visibility(model: UpstreamModel) -> str:
    visibility = model.raw.get("visibility")
    return visibility if isinstance(visibility, str) else "list"


def _is_zai_catalog_model(model: UpstreamModel) -> bool:
    return model.raw.get("provider") == "zai" or model.slug.startswith("glm-")


def _is_json_like(value: object) -> bool:
    if isinstance(value, bool | int | float | str) or value is None:
        return True
    if isinstance(value, list):
        return all(_is_json_like(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_json_like(item) for key, item in value.items())
    return False
