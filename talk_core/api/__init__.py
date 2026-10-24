"""TALK LLM API katmanı — kimlik bilgisi, yönlendirme, HTTP, komut üretimi."""

from importlib import import_module

__all__ = [
    "CredentialStore",
    "detect_key_provider",
    "CommandApiPipeline",
    "test_api_connection",
    "AVAILABLE_MODELS",
    "DEFAULT_MODEL",
    "get_model_candidates",
    "normalize_model_name",
    "provider_for_model",
    "resolve_model_for_provider",
]


def __getattr__(name: str):
    if name in {"CredentialStore", "detect_key_provider"}:
        module = import_module(".credentials", __name__)
        return getattr(module, name)
    if name in {"CommandApiPipeline", "test_api_connection"}:
        module = import_module(".pipeline", __name__)
        return getattr(module, name)
    if name in {
        "AVAILABLE_MODELS",
        "DEFAULT_MODEL",
        "get_model_candidates",
        "normalize_model_name",
        "provider_for_model",
        "resolve_model_for_provider",
    }:
        module = import_module(".registry", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
