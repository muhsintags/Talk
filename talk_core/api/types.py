from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Provider(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"


class ApiError(Exception):
    """Genel API hatası."""


class AuthApiError(ApiError):
    """401/403 — anahtar veya yetki sorunu."""


class ModelNotFoundApiError(ApiError):
    """404/410 — model mevcut değil."""


class TransientApiError(ApiError):
    """429/5xx veya zaman aşımı — başka model ile yeniden denenebilir."""


class EmptyResponseApiError(ApiError):
    """HTTP 200 ama boş veya parse edilemeyen gövde."""


@dataclass(frozen=True)
class ProviderCallResult:
    provider: Provider
    model: str
    raw_text: str
