from __future__ import annotations

import pytest

from app.core.codex_catalog import (
    CODEX_LB_ENV_KEY,
    build_codex_catalog_payload,
    build_codex_setup_summary,
    build_install_script,
    build_uninstall_script,
)


def _catalog_model(slug: str) -> dict:
    payload = build_codex_catalog_payload(base_url="https://codex.okidoo.co/backend-api/codex")
    models = payload["models"]
    assert isinstance(models, list)
    for model in models:
        if isinstance(model, dict) and model.get("slug") == slug:
            return model
    raise AssertionError(f"missing model {slug}")


def test_codex_catalog_includes_glm_52_with_strict_fields() -> None:
    glm = _catalog_model("glm-5.2")

    assert glm["display_name"] == "GLM-5.2"
    assert glm["input_modalities"] == ["text"]
    assert glm["available_in_plans"] == ["zai"]
    assert glm["visibility"] == "list"
    assert glm["shell_type"] == "shell_command"
    assert glm["apply_patch_tool_type"] == "freeform"
    assert glm["context_window"] >= 1_000_000
    assert glm["max_context_window"] == glm["context_window"]
    assert "additional_speed_tiers" not in glm
    assert "service_tier" not in glm
    assert "service_tiers" not in glm
    assert "default_service_tier" not in glm


def test_codex_setup_summary_and_scripts_emit_no_secret() -> None:
    summary = build_codex_setup_summary(base_url="https://codex.okidoo.co/backend-api/codex")
    install_script = build_install_script(public_origin="https://codex.okidoo.co")
    uninstall_script = build_uninstall_script()

    assert summary["provider"] == "codex-lb"
    assert summary["env_key"] == CODEX_LB_ENV_KEY
    assert summary["model_count"] > 0
    assert summary["install_command"] == "curl -fsSL 'https://codex.okidoo.co/codex/setup/install.sh' | sh"
    assert summary["uninstall_command"] == "curl -fsSL 'https://codex.okidoo.co/codex/setup/uninstall.sh' | sh"
    assert "model_catalog_json" in install_script
    assert "models_cache.json" in install_script
    assert "requires_openai_auth = true" in install_script
    assert "supports_websockets = true" in install_script
    assert "sk-clb-..." in install_script
    assert "sk-clb-" not in uninstall_script


@pytest.mark.asyncio
async def test_codex_setup_routes_are_public(async_client) -> None:
    catalog_response = await async_client.get(
        "/codex/catalog.json",
        headers={"host": "codex.okidoo.co", "x-forwarded-proto": "https"},
    )
    setup_response = await async_client.get(
        "/codex/setup",
        headers={"host": "codex.okidoo.co", "x-forwarded-proto": "https"},
    )
    install_response = await async_client.get(
        "/codex/setup/install.sh",
        headers={"host": "codex.okidoo.co", "x-forwarded-proto": "https"},
    )

    assert catalog_response.status_code == 200
    assert setup_response.status_code == 200
    assert install_response.status_code == 200
    assert "glm-5.2" in {model["slug"] for model in catalog_response.json()["models"]}
    assert setup_response.json()["install_command"] == (
        "curl -fsSL 'https://codex.okidoo.co/codex/setup/install.sh' | sh"
    )
    assert 'model_provider = "codex-lb"' in install_response.text


@pytest.mark.asyncio
async def test_codex_setup_rejects_unsafe_forwarded_host(async_client) -> None:
    response = await async_client.get(
        "/codex/setup",
        headers={"host": "codex.okidoo.co;touch /tmp/codex-lb-pwn", "x-forwarded-proto": "https"},
    )

    assert response.status_code == 400
