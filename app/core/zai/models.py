ZAI_MODEL_ALIASES: dict[str, str] = {
    # Codex Desktop and the VS Code extension currently hide model slugs that are
    # not present in OpenAI's remote allowlist. Keep one allowlisted slug mapped
    # to GLM-5.2 so those clients can select the Z.AI route without app patches.
    "gpt-5.2": "glm-5.2",
}


def canonical_zai_model(model: str | None) -> str | None:
    if not isinstance(model, str):
        return None
    candidate = model.strip().lower()
    alias = ZAI_MODEL_ALIASES.get(candidate)
    if alias is not None:
        return alias
    if candidate.startswith("glm-"):
        return candidate
    return None


def is_zai_model(model: str | None) -> bool:
    return canonical_zai_model(model) is not None
