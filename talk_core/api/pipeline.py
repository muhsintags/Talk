from __future__ import annotations

from typing import Optional, Tuple

from ..config import Config
from ..models import CommandSpec
from .credentials import CredentialStore, detect_key_provider
from .providers import call_gemini, call_groq, discover_gemini_models
from .registry import (
    get_model_candidates,
    normalize_model_name,
    provider_for_model,
    resolve_model_for_provider,
)
from .types import (
    ApiError,
    AuthApiError,
    ModelNotFoundApiError,
    Provider,
    TransientApiError,
)


class CommandApiPipeline:
    """
    Doğal dil → LLM → CommandSpec.

    Akış: kimlik çöz → sağlayıcı kilitle → model adayları → retry → parse.
    """

    def __init__(
        self,
        credentials: CredentialStore,
        *,
        timeout: int = 30,
    ):
        self.credentials = credentials
        self.timeout = timeout

    @classmethod
    def from_config(cls, cfg: Config) -> "CommandApiPipeline":
        return cls(CredentialStore(cfg), timeout=cfg.api_timeout)

    @classmethod
    def from_api_key(cls, api_key: str, *, timeout: int = 30) -> "CommandApiPipeline":
        return cls(CredentialStore.from_single_key(api_key), timeout=timeout)

    def _resolve_context(self, model: str) -> Tuple[Provider, str, str]:
        preferred = normalize_model_name(model or "auto")
        provider, api_key = self.credentials.resolve_any(model=preferred)

        if not api_key:
            raise ValueError(
                "API anahtarı bulunamadı. GEMINI_API_KEY / GROQ_API_KEY ortam değişkeni "
                "veya ~/.talk/config.json içinde anahtar tanımlayın."
            )

        key_provider = detect_key_provider(api_key)
        if key_provider and key_provider != provider:
            provider = key_provider

        discovered = []
        if provider == Provider.GEMINI:
            discovered = discover_gemini_models(api_key, timeout=min(self.timeout, 12))

        start_model = resolve_model_for_provider(preferred, provider, discovered)
        return provider, api_key, start_model

    def _resolve_context_for_provider(self, provider: Provider, model: str) -> Tuple[str, str]:
        preferred = normalize_model_name(model or "auto")
        api_key = self.credentials.for_provider(provider)
        if not api_key:
            raise ValueError(
                f"{provider.value.upper()}_API_KEY bulunamadı. "
                "Ortam değişkeni veya ~/.talk/config.json içinde anahtar tanımlayın."
            )

        discovered = []
        if provider == Provider.GEMINI:
            discovered = discover_gemini_models(api_key, timeout=min(self.timeout, 12))

        start_model = resolve_model_for_provider(preferred, provider, discovered)
        return api_key, start_model

    def _provider_order(self, preferred: Provider) -> list[Provider]:
        ordered = [preferred]
        for candidate in (Provider.GROQ, Provider.GEMINI):
            if candidate not in ordered and self.credentials.for_provider(candidate):
                ordered.append(candidate)
        return ordered

    def generate(self, prompt: str, model: str = "auto") -> CommandSpec:
        text = (prompt or "").strip()
        if not text:
            raise ValueError("Boş istek.")

        provider, api_key, start_model = self._resolve_context(model)
        provider_order = self._provider_order(provider)

        last_error: Optional[Exception] = None
        chosen_model = ""
        raw_text = ""

        for attempt_provider in provider_order:
            try:
                api_key, start_model = self._resolve_context_for_provider(attempt_provider, model)
            except ValueError:
                continue

            candidates = get_model_candidates(start_model, provider=attempt_provider)
            provider_error: Optional[Exception] = None

            for candidate in candidates:
                if provider_for_model(candidate) != attempt_provider:
                    continue
                try:
                    if attempt_provider == Provider.GROQ:
                        result = call_groq(api_key, candidate, text, self.timeout)
                    else:
                        result = call_gemini(api_key, candidate, text, self.timeout)
                    chosen_model = result.model
                    raw_text = result.raw_text
                    break
                except AuthApiError as exc:
                    provider_error = exc
                    break
                except ModelNotFoundApiError as exc:
                    last_error = exc
                    continue
                except TransientApiError as exc:
                    last_error = exc
                    continue
                except ApiError as exc:
                    last_error = exc
                    continue

            if chosen_model:
                break
            if provider_error is not None:
                last_error = provider_error
                continue

        if not chosen_model:
            if last_error:
                raise RuntimeError(str(last_error))
            raise RuntimeError("Hiçbir uygun model yanıt vermedi.")

        from ..llm import parse_response

        spec = parse_response(raw_text, default_prompt=text)
        spec.model = chosen_model
        return spec


def test_api_connection(api_key: str, model: str = "auto", timeout: int = 30) -> Tuple[bool, str]:
    try:
        pipe = CommandApiPipeline.from_api_key(api_key, timeout=timeout)
        res = pipe.generate("tarih ve saat", model=model)
        if res.command:
            return True, f"Bağlantı başarılı! Örnek çıktı: {res.command}"
        return False, "Modelden boş yanıt alındı."
    except Exception as exc:
        return False, str(exc)
