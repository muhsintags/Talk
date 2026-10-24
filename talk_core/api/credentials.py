from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from typing import TYPE_CHECKING

from .registry import infer_provider_from_model, provider_for_model

if TYPE_CHECKING:
    from ..config import Config
from .types import Provider

_GEMINI_KEY = re.compile(r"^(?:AIza|AQ\.)[0-9A-Za-z._-]{20,}$")
_GROQ_KEY = re.compile(r"^(?:gsk|sk|xai)_[A-Za-z0-9_-]+$")


def detect_key_provider(key: str) -> Optional[Provider]:
    value = (key or "").strip()
    if not value:
        return None
    if _GEMINI_KEY.match(value):
        return Provider.GEMINI
    if _GROQ_KEY.match(value):
        return Provider.GROQ
    if value.startswith(("AIza", "AQ.")):
        return Provider.GEMINI
    if value.startswith(("gsk_", "sk-", "xai_")):
        return Provider.GROQ
    return None


def _normalize_provider_hint(provider: str = "", model: str = "") -> str:
    """provider argümanı model adı gelse bile doğru sağlayıcıyı döndür."""
    raw = (provider or "").strip().lower()
    if raw in ("gemini", "google"):
        return "gemini"
    if raw == "groq":
        return "groq"
    if raw in ("", "auto"):
        return infer_provider_from_model(model) or "auto"
    inferred = infer_provider_from_model(raw)
    if inferred != "auto":
        return inferred
    return infer_provider_from_model(model) or "auto"


class CredentialStore:
    """Keyring, config ve ortam değişkenlerinden sağlayıcıya göre anahtar çözümü."""

    def __init__(self, cfg: Optional["Config"] = None, fallback_key: str = ""):
        self.cfg = cfg
        self._fallback = (fallback_key or "").strip()

    @classmethod
    def from_single_key(cls, api_key: str) -> "CredentialStore":
        return cls(cfg=None, fallback_key=api_key)

    def _config_keys(self, provider: Optional[Provider] = None) -> List[str]:
        if self.cfg is None:
            return []
        creds = self.cfg.get_api_credentials()
        if provider is None:
            return [c["key"] for c in creds]
        want = provider.value
        matched = [c["key"] for c in creds if c.get("provider") == want]
        if matched:
            return matched
        return [c["key"] for c in creds]

    def _env_keys(self, provider: Provider) -> List[str]:
        if provider == Provider.GROQ:
            names = ("GROQ_API_KEY", "OPENAI_API_KEY", "TALK_API_KEY", "API_KEY")
        else:
            names = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TALK_API_KEY", "API_KEY")
        out: List[str] = []
        for name in names:
            val = (os.environ.get(name) or "").strip()
            if val:
                out.append(val)

        for path in self._dotenv_candidates():
            for name in names:
                val = self._dotenv_value(path, name)
                if val:
                    out.append(val)
        return out

    def _dotenv_candidates(self) -> List[Path]:
        roots: List[Path] = []
        for raw in (os.getcwd(), str(Path.home()), str(Path.home() / ".talk")):
            candidate = Path(raw)
            if candidate not in roots:
                roots.append(candidate)

        out: List[Path] = []
        for base in roots:
            for name in (".env", ".env.local", ".talk/.env"):
                p = (base / name).resolve()
                if p.exists() and p not in out:
                    out.append(p)
        return out

    def _dotenv_value(self, path: Path, key_name: str) -> str:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            env_key, env_value = line.split("=", 1)
            if env_key.strip() != key_name:
                continue
            value = env_value.strip().strip("\"'")
            return value
        return ""

    def _keyring_key(self) -> str:
        if self.cfg is None:
            return ""
        try:
            from ..config import KEYRING_SERVICE, KEYRING_USER, _get_keyring

            kr = _get_keyring()
            if kr is None:
                return ""
            return (kr.get_password(KEYRING_SERVICE, KEYRING_USER) or "").strip()
        except Exception:
            return ""

    def for_provider(self, provider: Provider) -> str:
        candidates: List[str] = []

        ring = self._keyring_key()
        if ring:
            candidates.append(ring)

        candidates.extend(self._config_keys(provider))
        candidates.extend(self._env_keys(provider))

        if self._fallback:
            candidates.append(self._fallback)

        for key in candidates:
            hint = detect_key_provider(key)
            if hint == provider:
                return key
        return ""

    def for_model(self, model: str) -> str:
        prov = provider_for_model(model) if normalize_model_pref(model) != "auto" else None
        if prov is not None:
            key = self.for_provider(prov)
            if key:
                return key
        return self.resolve_any(model=model)[1]

    def resolve_any(self, model: str = "auto", provider_hint: str = "") -> Tuple[Provider, str]:
        """Model/tercihe göre kullanılacak sağlayıcı ve anahtar."""
        hint = _normalize_provider_hint(provider_hint, model)

        if hint == "groq":
            key = self.for_provider(Provider.GROQ)
            if key:
                return Provider.GROQ, key

        if hint == "gemini":
            key = self.for_provider(Provider.GEMINI)
            if key:
                return Provider.GEMINI, key

        if normalize_model_pref(model) != "auto":
            prov = provider_for_model(model)
            key = self.for_provider(prov)
            if key:
                return prov, key

        for prov in (Provider.GEMINI, Provider.GROQ):
            key = self.for_provider(prov)
            if key:
                return prov, key

        return Provider.GEMINI, ""


def normalize_model_pref(model: str) -> str:
    return (model or "").strip().lower() or "auto"
