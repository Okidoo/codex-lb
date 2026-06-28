def canonical_zai_model(model: str | None) -> str | None:
    if not isinstance(model, str):
        return None
    candidate = model.strip().lower()
    if candidate.startswith("glm-"):
        return candidate
    return None


def is_zai_model(model: str | None) -> bool:
    return canonical_zai_model(model) is not None
