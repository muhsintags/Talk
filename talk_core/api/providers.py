from __future__ import annotations

import json
from typing import Any, Dict, List

from . import http as api_http
from .prompts import SYSTEM_INSTRUCTION, get_environment_context
from .registry import normalize_model_name
from .types import (
    AuthApiError,
    EmptyResponseApiError,
    ModelNotFoundApiError,
    Provider,
    ProviderCallResult,
    TransientApiError,
)

GEMINI_GENERATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_LIST = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_CHAT = "https://api.groq.com/openai/v1/chat/completions"


def _classify_http(status: int, message: str) -> Exception:
    if status in (401, 403):
        return AuthApiError(message or f"Yetkilendirme hatası ({status})")
    if status in (404, 410):
        return ModelNotFoundApiError(message or f"Model bulunamadı ({status})")
    if status in (408, 429, 500, 502, 503, 504) or status == 0:
        return TransientApiError(message or f"Geçici API hatası ({status})")
    return TransientApiError(message or f"API hatası ({status})")


def discover_gemini_models(api_key: str, timeout: int = 10) -> List[str]:
    status, body, err = api_http.get_json(
        GEMINI_LIST,
        headers={"x-goog-api-key": api_key},
        timeout=timeout,
    )
    if status != 200:
        return []
    models = body.get("models") or []
    out: List[str] = []
    seen = set()
    for item in models:
        name = normalize_model_name(item.get("name") if isinstance(item, dict) else item)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _build_user_prompt(nl_prompt: str) -> str:
    return (
        f"{get_environment_context()}\n"
        f"Kullanıcı İsteği: {nl_prompt}\n"
        "Lütfen istenen JSON formatında yanıt ver."
    )


def call_gemini(api_key: str, model: str, nl_prompt: str, timeout: int) -> ProviderCallResult:
    url = GEMINI_GENERATE.format(model=model)
    payload: Dict[str, Any] = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [
            {"role": "user", "parts": [{"text": _build_user_prompt(nl_prompt)}]},
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 800,
            "responseMimeType": "application/json",
        },
    }
    status, data, err = api_http.post_json(
        url,
        payload,
        headers={"x-goog-api-key": api_key},
        timeout=timeout,
    )
    if status != 200:
        raise _classify_http(status, err)

    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        reason = data.get("promptFeedback", {}).get("blockReason", "Bilinmiyor")
        raise EmptyResponseApiError(f"Gemini yanıtı boş (engel: {reason})") from exc

    return ProviderCallResult(Provider.GEMINI, model, raw)


def call_groq(api_key: str, model: str, nl_prompt: str, timeout: int) -> ProviderCallResult:
    base = model.split("/", 1)[1] if model.startswith("groq/") else model
    payload = {
        "model": base,
        "messages": [{"role": "user", "content": _build_user_prompt(nl_prompt)}],
        "temperature": 0.0,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }
    status, data, err = api_http.post_json(
        GROQ_CHAT,
        payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    if status != 200:
        raise _classify_http(status, err)

    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        reason = data.get("error", {}).get("message", "Bilinmiyor")
        raise EmptyResponseApiError(f"Groq yanıtı boş ({reason})") from exc

    return ProviderCallResult(Provider.GROQ, model, raw)
