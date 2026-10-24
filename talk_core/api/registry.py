from __future__ import annotations

import re
from typing import List, Optional

from .types import Provider

DEFAULT_MODEL = "auto"

GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

GROQ_MODELS = [
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-8b-instant",
    "groq/meta-llama/llama-4-scout-17b-16e-instruct",
]

# UI listesi (auto + bilinen modeller)
AVAILABLE_MODELS = [DEFAULT_MODEL, *GEMINI_MODELS, *GROQ_MODELS]
SUPPORTED_MODEL_ALIASES = set(AVAILABLE_MODELS)

# Geriye dönük test / keşif uyumu
LEGACY_GEMINI_ALIASES = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]


def infer_provider_from_model(model: str) -> str:
    value = (model or "").strip().lower()
    if not value or value == "auto":
        return "auto"
    if value.startswith("groq/") or value == "groq":
        return "groq"
    if value.startswith(("gemini/", "google/", "gemini", "google")):
        return "gemini"
    return "gemini"


def normalize_model_name(name: str) -> str:
    candidate = (name or "").strip()
    candidate = candidate.replace("models/", "").replace("model/", "")
    if "/" in candidate:
        provider, suffix = candidate.split("/", 1)
        return f"{provider.strip().lower()}/{suffix.strip().lower()}"
    return candidate.lower()


def provider_for_model(model: str) -> Provider:
    normalized = normalize_model_name(model)
    if normalized.startswith("groq/"):
        return Provider.GROQ
    return Provider.GEMINI


def get_model_candidates(preferred: str, provider: Optional[Provider] = None) -> List[str]:
    """Seçilen modele göre aynı sağlayıcı içinde yedek sırası."""
    requested = normalize_model_name(preferred)
    ordered: List[str] = []

    if requested and requested.lower() != DEFAULT_MODEL:
        ordered.append(requested)

    if requested.lower() == DEFAULT_MODEL:
        if provider == Provider.GROQ:
            ordered.extend(GROQ_MODELS)
        elif provider == Provider.GEMINI:
            ordered.extend(GEMINI_MODELS)
        else:
            ordered.extend(GEMINI_MODELS)
            ordered.extend(GROQ_MODELS)
    else:
        prov = provider or provider_for_model(requested)
        if prov == Provider.GROQ:
            ordered.extend(m for m in GROQ_MODELS if m != requested)
        else:
            ordered.extend(m for m in GEMINI_MODELS if m != requested)
            ordered.extend(m for m in LEGACY_GEMINI_ALIASES if m != requested)

    seen = set()
    out: List[str] = []
    for item in ordered:
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def resolve_model_for_provider(
    preferred: str,
    provider: Provider,
    discovered_gemini: Optional[List[str]] = None,
) -> str:
    """Sağlayıcı + tercih ile tek bir başlangıç modeli seç."""
    pref = normalize_model_name(preferred)
    if pref and pref.lower() != DEFAULT_MODEL:
        if provider == Provider.GROQ and pref.startswith("groq/"):
            return pref
        if provider == Provider.GEMINI and not pref.startswith("groq/"):
            return pref

    if provider == Provider.GROQ:
        return GROQ_MODELS[0]

    if discovered_gemini:
        for name in discovered_gemini:
            cleaned = normalize_model_name(name)
            if cleaned and not cleaned.startswith("groq/"):
                if re.match(r"gemini-", cleaned):
                    return cleaned
                return cleaned

    return GEMINI_MODELS[0]
