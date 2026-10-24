"""
TALK Core - Configuration Management
Yapılandırma yükleme, kaydetme, keyring entegrasyonu ve ortam değişkeni önceliklendirmesi.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path.home() / ".talk"
CONFIG_PATH = CONFIG_DIR / "config.json"
LEGACY_CONFIG_PATH = Path.home() / ".talk_gui.json"

from .api.registry import AVAILABLE_MODELS, DEFAULT_MODEL, SUPPORTED_MODEL_ALIASES, infer_provider_from_model

KEYRING_SERVICE = "talk-ai-cli"
KEYRING_USER = "gemini-api-key"

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_key": "",
    "api_keys": [],
    "api_credentials": [],
    "model": DEFAULT_MODEL,
    "api_timeout": 30,
    "exec_timeout": 60,
    "max_output_chars": 200_000,
    "theme": "tokyonight",
    "font_size": 11,
    "auto_copy": False,
    "safe_mode": True,
    "allow_high_risk_commands": False,
    "os_preset": "linux",
    "os_custom": "",
}


def _get_keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def _canonical_model_name(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if "/" in candidate:
        provider, suffix = candidate.split("/", 1)
        return f"{provider.strip().lower()}/{suffix.strip().lower()}"
    return candidate.lower()


def is_valid_api_key_format(key: str) -> bool:
    candidate = (key or "").strip()
    if len(candidate) < 20:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_\-\.]+", candidate))


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    return CONFIG_DIR


class Config:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self._data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        if data:
            self._data.update(data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    @property
    def model(self) -> str:
        env_model = _canonical_model_name(os.environ.get("TALK_MODEL") or "")
        if env_model in SUPPORTED_MODEL_ALIASES:
            return env_model

        current = _canonical_model_name(self._data.get("model") or "")
        if current in SUPPORTED_MODEL_ALIASES:
            return current

        self._data["model"] = DEFAULT_MODEL
        return DEFAULT_MODEL

    @model.setter
    def model(self, val: str) -> None:
        candidate = _canonical_model_name(val)
        if candidate in SUPPORTED_MODEL_ALIASES:
            self._data["model"] = candidate
        else:
            self._data["model"] = DEFAULT_MODEL

    @property
    def api_timeout(self) -> int:
        try:
            return int(os.environ.get("TALK_API_TIMEOUT") or self._data.get("api_timeout") or 30)
        except ValueError:
            return 30

    @property
    def exec_timeout(self) -> int:
        try:
            return int(os.environ.get("TALK_EXEC_TIMEOUT") or self._data.get("exec_timeout") or 60)
        except ValueError:
            return 60

    @property
    def max_output_chars(self) -> int:
        return int(self._data.get("max_output_chars") or 200_000)

    @property
    def theme(self) -> str:
        return str(self._data.get("theme") or "tokyonight")

    @property
    def font_size(self) -> int:
        return int(self._data.get("font_size") or 11)

    @property
    def auto_copy(self) -> bool:
        return bool(self._data.get("auto_copy", False))

    @property
    def safe_mode(self) -> bool:
        if "safe_mode" in self._data:
            return bool(self._data.get("safe_mode", True))
        return not bool(self._data.get("allow_high_risk_commands", False))

    @safe_mode.setter
    def safe_mode(self, value: bool) -> None:
        self._data["safe_mode"] = bool(value)
        self._data["allow_high_risk_commands"] = not bool(value)

    @property
    def allow_high_risk_commands(self) -> bool:
        if "allow_high_risk_commands" in self._data:
            return bool(self._data.get("allow_high_risk_commands", False))
        return not bool(self._data.get("safe_mode", True))

    @allow_high_risk_commands.setter
    def allow_high_risk_commands(self, value: bool) -> None:
        self._data["allow_high_risk_commands"] = bool(value)
        self._data["safe_mode"] = not bool(value)

    def get_os_label(self) -> str:
        preset = str(self._data.get("os_preset") or os.environ.get("TALK_OS_PRESET") or "linux").strip().lower()
        custom = str(self._data.get("os_custom") or os.environ.get("TALK_OS_CUSTOM") or "").strip()

        mapping = {
            "windows11": "Windows 11",
            "windows": "Windows 11",
            "macos": "macOS",
            "linux": "Linux Debian",
            "debian": "Linux Debian",
            "ubuntu": "Linux Debian",
        }

        label = mapping.get(preset, "Linux Debian")
        if custom:
            return f"{label} / {custom}"
        return label

    def apply_os_context(self) -> str:
        label = self.get_os_label()
        os.environ["TALK_OS_PRESET"] = str(self._data.get("os_preset") or "linux")
        os.environ["TALK_OS_CUSTOM"] = str(self._data.get("os_custom") or "")
        os.environ["TALK_OS_LABEL"] = label
        return label

    def get_api_credentials(self) -> list[dict[str, str]]:
        """Sağlayıcı etiketli anahtar listesi: [{provider, key}, ...]."""
        from .api.credentials import detect_key_provider

        raw = self._data.get("api_credentials")
        creds: list[dict[str, str]] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                provider = str(item.get("provider") or "").strip().lower()
                if provider not in ("gemini", "groq"):
                    hint = detect_key_provider(key)
                    provider = hint.value if hint is not None else "gemini"
                creds.append({"provider": provider, "key": key})

        if creds:
            return creds

        for key in self._legacy_api_key_strings():
            hint = detect_key_provider(key)
            provider = hint.value if hint is not None else "gemini"
            creds.append({"provider": provider, "key": key})
        return creds

    def set_api_credentials(self, credentials: list[dict[str, str]]) -> None:
        from .api.credentials import detect_key_provider

        cleaned: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in credentials or []:
            key = str((item or {}).get("key") or "").strip()
            if not key:
                continue
            provider = str((item or {}).get("provider") or "").strip().lower()
            if provider not in ("gemini", "groq"):
                hint = detect_key_provider(key)
                provider = hint.value if hint is not None else "gemini"
            token = (provider, key)
            if token in seen:
                continue
            seen.add(token)
            cleaned.append({"provider": provider, "key": key})

        self._data["api_credentials"] = cleaned
        self._data["api_keys"] = [c["key"] for c in cleaned]
        if cleaned:
            self._data["api_key"] = cleaned[0]["key"]
        else:
            self._data.pop("api_key", None)

    def _legacy_api_key_strings(self) -> list[str]:
        keys: list[str] = []
        raw_keys = self._data.get("api_keys") or []
        if isinstance(raw_keys, list):
            keys.extend(str(v).strip() for v in raw_keys if str(v).strip())
        legacy = str(self._data.get("api_key") or "").strip()
        if legacy and legacy not in keys:
            keys.append(legacy)
        deduped: list[str] = []
        for key in keys:
            if key not in deduped:
                deduped.append(key)
        return deduped

    def get_api_keys(self) -> list[str]:
        return [c["key"] for c in self.get_api_credentials()]

    def set_api_keys(self, keys: list[str]) -> None:
        from .api.credentials import detect_key_provider

        creds = []
        for key in keys or []:
            value = str(key).strip()
            if not value:
                continue
            hint = detect_key_provider(value)
            provider = hint.value if hint is not None else "gemini"
            creds.append({"provider": provider, "key": value})
        self.set_api_credentials(creds)

    def load_api_key(self, provider: str = "auto", model: Optional[str] = None) -> str:
        """Sağlayıcı / model bilincinde anahtar çözümü (CredentialStore)."""
        from .api.credentials import CredentialStore, _normalize_provider_hint
        from .api.types import Provider

        model_name = (model or self.model or "").strip()
        hint = _normalize_provider_hint(provider, model_name)
        store = CredentialStore(self)
        if hint == "gemini":
            return store.for_provider(Provider.GEMINI)
        if hint == "groq":
            return store.for_provider(Provider.GROQ)
        _, key = store.resolve_any(model=model_name, provider_hint=hint)
        return key

    def save_api_key(self, key: str) -> str:
        """
        Anahtarı saklar. Dönüş: 'keyring' | 'file' | 'cleared' | 'error'
        """
        kr = _get_keyring()
        clean_key = (key or "").strip()

        if not clean_key:
            self._data.pop("api_key", None)
            self._data["api_keys"] = []
            if kr is not None:
                try:
                    kr.delete_password(KEYRING_SERVICE, KEYRING_USER)
                except Exception:
                    pass
            return "cleared" if self.save() else "error"

        if kr is not None:
            try:
                kr.set_password(KEYRING_SERVICE, KEYRING_USER, clean_key)
                self._data["api_keys"] = [clean_key]
                self._data["api_key"] = clean_key
                self.save()
                return "keyring"
            except Exception:
                pass

        self._data["api_keys"] = [clean_key]
        self._data["api_key"] = clean_key
        return "file" if self.save() else "error"

    def save(self) -> bool:
        ensure_config_dir()
        try:
            CONFIG_PATH.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.chmod(CONFIG_PATH, 0o600)
            return True
        except OSError:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)


def load_config() -> Config:
    """Config dosyasını yükler, yoksa legacy dosyaları migrate eder."""
    ensure_config_dir()
    data: Dict[str, Any] = {}

    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    elif LEGACY_CONFIG_PATH.is_file():
        try:
            data = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = Config(data)
            cfg.save()
            return cfg
        except Exception:
            data = {}

    current_model = (data.get("model") or "").strip()
    if current_model not in SUPPORTED_MODEL_ALIASES:
        data["model"] = DEFAULT_MODEL

    cfg = Config(data)
    if not cfg.get("api_credentials") and cfg._legacy_api_key_strings():
        from .api.credentials import detect_key_provider

        migrated = []
        for key in cfg._legacy_api_key_strings():
            hint = detect_key_provider(key)
            migrated.append({"provider": hint.value if hint else "gemini", "key": key})
        cfg.set_api_credentials(migrated)
        cfg.save()
    return cfg