"""
TALK Core - LLM Client (Google Gemini)
Yapay zeka ile doğal dili güvenli ve tek satırlık Bash komutuna çeviren istemci.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
from typing import Optional, Tuple

from .api.credentials import CredentialStore, detect_key_provider
from .api.pipeline import CommandApiPipeline, test_api_connection
from .api.providers import discover_gemini_models
from .api.registry import (
    get_model_candidates as _registry_model_candidates,
    normalize_model_name,
    provider_for_model,
    resolve_model_for_provider,
)
from .api.types import Provider
from .models import CommandSpec

SYSTEM_INSTRUCTION = (
    "You are TALK (Terminal Assistant via Language Knowledge), an expert Linux/Bash systems assistant.\n"
    "Your sole duty is to translate natural language user requests into a single, exact, safe Bash command.\n\n"
    "RULES:\n"
    "1. Respond ONLY with a valid JSON object matching this schema:\n"
    "   {\n"
    '     "command": "<single-line bash command>",\n'
    '     "explanation": "<short explanation in the same language as the user>",\n'
    '     "unsupported": false\n'
    "   }\n"
    "2. The command MUST be a single line. NEVER include newline characters inside the command.\n"
    "3. NEVER use sudo unless the user explicitly asks for elevated/root privileges.\n"
    "4. Never generate commands that delete, overwrite, reformat, or destroy critical system files or system directories such as /, /etc, /boot, /usr, /var, /System32, or Windows system folders.\n"
    "5. If the user request cannot be translated into a terminal/shell command, set:\n"
    '   "unsupported": true, "command": "echo \'UNSUPPORTED_REQUEST\'", "explanation": "<reason>"\n'
    "6. Tailor the command to the user's OS and environment provided in the prompt."
)


def get_environment_context() -> str:
    label = os.environ.get("TALK_OS_LABEL")
    if not label:
        preset = (os.environ.get("TALK_OS_PRESET") or "").strip().lower()
        custom = (os.environ.get("TALK_OS_CUSTOM") or "").strip()
        if preset in {"windows11", "windows"}:
            label = "Windows 11"
        elif preset in {"macos", "mac"}:
            label = "macOS"
        elif preset in {"linux", "debian", "ubuntu"}:
            label = "Linux Debian"
        else:
            label = f"{platform.system()} {platform.release()} ({platform.machine()})"
        if custom:
            label = f"{label} / {custom}"
    return (
        f"Context: OS={label}, "
        f"Shell=bash, CWD={os.getcwd()}"
    )


def _normalize_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if value is None:
        return default
    return bool(value)


def _safe_unicode_unescape(value: str) -> str:
    """Sadece geçerli unicode kaçışlarını çözer, hatalı kabuk kaçışlarını temizler.

    Bu fonksiyon bir metnin zaten UTF-8 olarak kodlanmış gerçek karakterlerini yeniden
    kodlamaz; sadece \\uXXXX, \\UXXXXXXXX ve \\xNN biçimlerini uygun şekilde çözer.
    """
    if not value:
        return value

    text = value

    def _decode_hex(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    text = re.sub(r"\\u([0-9a-fA-F]{4})", _decode_hex, text)
    text = re.sub(r"\\U([0-9a-fA-F]{8})", _decode_hex, text)
    text = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)

    # JS/JSON çıktılarında kaçışlı tırnaklar ve kabuk karakterleri temizlenir.
    text = text.replace('\\"', '"').replace("\\'", "'").replace("\\`", "`")
    text = text.replace('\\(', '(').replace('\\)', ')').replace('\\[', '[').replace('\\]', ']')
    text = text.replace('\\{', '{').replace('\\}', '}').replace('\\*', '*').replace('\\?', '?')
    text = text.replace('\\$', '$').replace('\\&', '&').replace('\\|', '|').replace('\\;', ';')

    # Kabuk komutlarında yaygın olan \(, \*, \- gibi hatalı/yanlış kaçışları temizle,
    # fakat geçerli JSON unicode kaçışları korunur.
    text = re.sub(r'\\(?!["\\/bfnrtuU])', '', text)
    return text


def _normalize_command_text(raw: str) -> str:
    cmd = (raw or "").strip()
    cmd = re.sub(r"^(?:js|javascript)\s*[:=]\s*", "", cmd, flags=re.IGNORECASE)
    cmd = re.sub(r"^(?:const|let|var)\s*(?:cmd|command)\s*[:=]\s*", "", cmd, flags=re.IGNORECASE)
    cmd = re.sub(r"^(?:cmd|command)\s*[:=]\s*", "", cmd, flags=re.IGNORECASE)
    cmd = _safe_unicode_unescape(cmd)
    cmd = re.sub(r"\s*(?:~\d+|\"\"|''|``)\s*(?:[\"'`]+\s*)*;?\s*$", "", cmd)
    cmd = re.sub(r"^\s*[\"'`]+|[\"'`]+\s*$", "", cmd)
    cmd = re.sub(r"(?:\s+;\s*)+$", "", cmd)
    cmd = cmd.replace("\\n", " ").replace("\\t", " ")
    cmd = " ".join(cmd.splitlines()).strip()
    if cmd.count('"') % 2 == 1 and not cmd.endswith('"'):
        cmd = cmd + '"'
    if cmd.count("'") % 2 == 1 and not cmd.endswith("'"):
        cmd = cmd + "'"
    while len(cmd) >= 2 and cmd[0] == cmd[-1] and cmd[0] in {'"', "'", "`"}:
        cmd = cmd[1:-1].strip()
    return cmd.strip()


def _repair_json_escapes(text: str) -> str:
    """JSON içinde geçersiz kaçışlar (`\(`, `\*`, `\.` gibi) temizlenir; geçerli `\n`, `\"`, `\\` korunur."""
    return re.sub(r'\\(?!["\\/bfnrtu])', '', text)


def _extract_command_literal(raw: str) -> Optional[str]:
    lower = raw.lower()
    for key in ("command", "cmd"):
        idx = lower.find(f'"{key}"')
        if idx == -1:
            idx = lower.find(f"'{key}'")
        if idx == -1:
            idx = lower.find(f"{key}")
        if idx == -1:
            continue

        i = idx + len(key)
        while i < len(raw) and raw[i] not in {':', '='}:
            i += 1
        if i >= len(raw):
            continue
        i += 1
        while i < len(raw) and raw[i].isspace():
            i += 1
        if i >= len(raw):
            continue
        delim = raw[i]
        if delim not in {'"', "'", "`"}:
            continue

        close_idx = len(raw)
        for marker in ("}\n", "}\r", "}\n\n", "}\r\n", "}", "\n", "\r"):
            pos = raw.find(marker, i + 1)
            if pos != -1:
                close_idx = min(close_idx, pos)

        end = raw.rfind(delim, i + 1, close_idx)
        if end != -1:
            candidate = raw[i + 1:end]
            return _normalize_command_text(candidate)

        candidate = raw[i + 1:close_idx]
        if candidate.strip():
            return _normalize_command_text(candidate)
    return None


def _extract_json(raw: str) -> Optional[dict]:
    """Çeşitli Markdown veya kirli çıktı kalıplarından JSON'ı çıkarır."""
    text = raw.strip()
    code_fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_fence:
        text = code_fence.group(1).strip()

    for candidate in (text, _repair_json_escapes(text)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        repaired = _repair_json_escapes(match.group(1).strip())
        try:
            data = json.loads(repaired)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def _is_user_desktop_cleanup(command: str) -> bool:
    """Kullanıcı masaüstündeki medya ve döküman dosyalarını hedefleyen toplu silme komutlarına özel izin verir."""
    cmd = (command or "").strip()
    if not cmd:
        return False

    desktop_path_regex = re.compile(
        r"(?:\$HOME|~|%USERPROFILE%|HOME)/Desktop|/home/[^/\s]+/Desktop|[A-Za-z]:[/\\]Users[/\\][^/\\\s]+[/\\]Desktop",
        re.IGNORECASE,
    )
    if not desktop_path_regex.search(cmd):
        return False

    if re.search(r"(?:/(?:etc|boot|usr|var|root)(?:/|$)|/System32(?:/|$)|C:[\\/]Windows[\\/]System32(?:/|$))", cmd, re.IGNORECASE):
        return False

    extensions = "ipynb|mp4|png|pdf|json|zip|7z"
    if not re.search(rf"(?:\.(?:{extensions})|\*\.(?:{extensions})|(?:-name|-iname)\s+['\"]?\*\.(?:{extensions})['\"]?)", cmd, re.IGNORECASE):
        return False

    if re.search(r"\b(?:sudo|curl|wget|bash\s+-c|sh\s+-c|\|\s*(?:sudo\s+)?(?:ba|z)?sh)\b", cmd, re.IGNORECASE):
        return False

    return True


def validate_generated_command(command: str) -> Tuple[bool, str]:
    """Üretilen komutun boş, çok satırlı, eksik/yanlış program çağrısı veya açık güvenlik riski taşıyan biçimde olup olmadığını doğrular."""
    cmd = (command or "").strip()
    if _is_user_desktop_cleanup(cmd):
        return True, ""
    if not cmd:
        return False, "Boş komut üretildi."
    if "\n" in cmd:
        return False, "Komut birden fazla satır içeriyor; tek satırlık komut gerekli."
    if "\x00" in cmd:
        return False, "Komut geçersiz karakterler içeriyor."
    if "UNSUPPORTED_REQUEST" in cmd.upper():
        return False, "İstek kabuk komutu olarak yorumlanamadı."
    if cmd.lower().startswith(("önerilen komut", "command", "cmd", "why", "here is", "json", "{\"command\"")):
        return False, "Komut metni, kabuk komutundan önce açıklama kapsayıcısı içeriyor; yarım/yanlış JSON reddedildi."
    if re.search(r"(?:\|\s*$|&&\s*$|\|\|\s*$|;\s*$|\\\s*$|>\s*$|<\s*$|\$\(\s*$|\{\s*$|\(\s*$)", cmd):
        return False, "Komut yarım kalmış görünüyor; tamamlanmamış kabuk ifadesi reddedildi."

    shell_builtins = {
        "cd", "echo", "printf", "pwd", "export", "unset", "readonly", "local", "read",
        "test", "[", "alias", "unalias", "source", ".", "eval", "exec", "exit",
        "return", "true", "false", "type", "command", "builtin", "hash", "jobs",
        "fg", "bg", "wait", "umask", "ulimit", "set", "shift", "trap", "help",
        "break", "continue", "declare", "typeset", "let", "time", "times", "dirs",
        "popd", "pushd", "kill", "suspend", "disown", "enable", "compgen", "complete",
        "caller", "bind", "coproc", "history", "mapfile", "readarray", "select",
        "logout",
    }

    def _first_command_name(command_text: str) -> Optional[str]:
        text = command_text.strip()
        for prefix in ("sudo ", "sudo -n ", "time ", "env ", "nohup ", "setsid ", "stdbuf ", "nice ", "ionice "):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].lstrip()
                break
        try:
            tokens = shlex.split(text, posix=True)
        except ValueError:
            return None
        if not tokens:
            return None
        first = tokens[0]
        if not first or first.startswith("$"):
            return None
        return first

    first = _first_command_name(cmd)
    if first is not None:
        if first in shell_builtins:
            pass
        elif first.startswith(("/", "./", "~/", "../")):
            if not os.path.exists(first):
                return False, f"Komut bulunamadı: '{first}' mevcut değil."
        elif not shutil.which(first):
            return False, f"Komut bulunamadı: '{first}' PATH içinde yok."

    quote_state = None
    escaped = False
    paren_stack = []
    for ch in cmd:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in {"'", '"'}:
            if quote_state == ch:
                quote_state = None
            elif quote_state is None:
                quote_state = ch
            continue
        if quote_state is not None:
            continue
        if ch in "([{":
            paren_stack.append(ch)
        elif ch in ")]}":
            if not paren_stack:
                return False, "Komutun parantezleri kapatılmamış; hatalı kabuk komutu reddedildi."
            open_ch = paren_stack.pop()
            if (open_ch, ch) not in {('(', ')'), ('[', ']'), ('{', '}')}:
                return False, "Komutun parantez yapısı bozuk; hatalı kabuk komutu reddedildi."
    if quote_state is not None or paren_stack:
        return False, "Komutun tırnakları veya parantezleri kapatılmamış; hatalı kabuk komutu reddedildi."

    if re.search(r"\$\([^\n]*\b(rm|sudo|mkfs|dd|curl|wget|chmod|chown|shutdown|reboot|mount|umount|kill|pkill|killall)\b[^\n]*\)", cmd, re.IGNORECASE):
        return False, "Komut yerleşiminde tehlikeli kabuk işlemi tespit edildi."
    if re.search(r"`[^`\n]*(rm|sudo|mkfs|dd|curl|wget|chmod|chown|shutdown|reboot|mount|umount|kill|pkill|killall)[^`\n]*`", cmd, re.IGNORECASE):
        return False, "Backtick komut yürütme tehlikeli olarak tespit edildi."
    if re.search(r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b", cmd, re.IGNORECASE):
        return False, "Uzak betik doğrudan kabukta çalıştırılmaya çalışılıyor."
    if re.search(
        r"\b(?:ba|z)?sh\s+-c\s+['\"][^'\"]*\b(rm\s+-|mkfs|dd\s+|curl\s+|wget\s+|sudo\s+)[^'\"]*['\"]",
        cmd,
        re.IGNORECASE,
    ):
        return False, "bash -c içinde açık tehlikeli işlem tespit edildi."
    if re.search(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(?:/|/\s*$|/\*|/\s*&&)", cmd, re.IGNORECASE):
        return False, "Kök dizini silme / sistemin en kritik bölümünü temizleme işlemi reddedildi."
    if re.search(r"(?:/System32|C:\\Windows\\System32|/etc/|/boot/|/usr/|/var/|/root/|/bin/|/sbin/|~/.ssh|\$HOME/\.ssh)", cmd, re.IGNORECASE):
        if re.search(r"(?:rm\s+-rf|mkfs|dd\s+if=|dd\s+of=|truncate\s+|chmod\s+\d+\s+|chown\s+|>\s*(?:/etc/|/boot/|/usr/|/var/|/root/|/System32|C:\\Windows\\System32))", cmd, re.IGNORECASE):
            return False, "Kritik sistem dizinlerine veya Windows sistem dosyalarına doğrudan yazma/temizleme izni yok."
    return True, ""


def parse_response(raw: str, default_prompt: str = "") -> CommandSpec:
    """Model çıktısını JSON veya geriye dönük uyumlu CMD/WHY formatından ayıklar."""
    parsed_json = _extract_json(raw)
    if parsed_json:
        cmd = _normalize_command_text(str(parsed_json.get("command") or "").strip())
        exp = str(parsed_json.get("explanation") or "").strip()
        unsupported = _normalize_bool(parsed_json.get("unsupported", False), default=False)

        cmd = " ".join(cmd.splitlines()).strip()
        ok, reason = validate_generated_command(cmd)
        if not ok:
            unsupported = True
            exp = exp or reason

        if not cmd or "UNSUPPORTED_REQUEST" in cmd:
            unsupported = True

        return CommandSpec(
            prompt=default_prompt,
            command=cmd,
            explanation=exp,
            unsupported=unsupported,
            raw_response=raw,
        )

    # Geriye dönük (Fallback) CMD / WHY veya serbest metin
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    cmd = ""
    why = ""
    extra = []

    for ln in lines:
        if ln.lower().startswith("cmd:"):
            cmd = ln[4:].strip()
        elif ln.lower().startswith("why:"):
            why = ln[4:].strip()
        else:
            extra.append(ln)

    if not cmd:
        cmd = _extract_command_literal(raw) or ""

    if not cmd and lines:
        candidate = lines[0].strip()
        if candidate.lower().startswith(("önerilen komut", "command", "cmd", "why", "here is", "json", "{\"command\"")):
            cmd = ""
            why = " ".join(lines[1:]).strip()
        elif candidate.startswith('"command"') or candidate.lower().startswith("'command'") or candidate.lower().startswith("command"):
            extracted = _extract_command_literal(raw)
            if extracted:
                cmd = extracted
            else:
                cmd = candidate.split(":", 1)[-1].strip().strip('"\'`') if ":" in candidate else candidate
            why = " ".join(lines[1:]).strip()
        else:
            cmd = candidate
            why = " ".join(lines[1:]).strip()
    elif not why and extra:
        why = " ".join(extra).strip()

    cmd = re.sub(r"^```[a-zA-Z]*", "", cmd).strip("`").strip()
    cmd = _normalize_command_text(cmd)

    ok, reason = validate_generated_command(cmd)
    unsupported = ("UNSUPPORTED_REQUEST" in cmd or not cmd or not ok)
    if not ok:
        if cmd and re.search(r"(?:\:$|\\$|\|\s*$|&&\s*$|\|\|\s*$|\(\s*$|\{\s*$|\[\s*$|^.*\b(?:grep|cut|find)\b.*\s(?:\|\s*|\&\&\s*|\|\|\s*)?$)", cmd.strip()):
            cmd = ""
        why = why or reason
    return CommandSpec(
        prompt=default_prompt,
        command=cmd,
        explanation=why,
        unsupported=unsupported,
        raw_response=raw,
    )


def get_model_provider(model: str) -> str:
    return provider_for_model(model).value


def get_api_key_provider_hint(api_key: str) -> str:
    prov = detect_key_provider(api_key)
    return prov.value if prov else ""


def discover_available_models(api_key: str, timeout: int = 10) -> list[str]:
    return discover_gemini_models(api_key, timeout=timeout)


def get_model_candidates(model: str) -> list[str]:
    requested = normalize_model_name(model)
    provider = None
    if requested.lower() != "auto":
        provider = provider_for_model(requested)
    return _registry_model_candidates(requested, provider=provider)


def resolve_model_name(api_key: str, preferred_model: str = "auto", timeout: int = 10) -> str:
    store = CredentialStore.from_single_key(api_key)
    provider, key = store.resolve_any(model=preferred_model)
    if not key:
        return normalize_model_name(preferred_model) or "auto"
    discovered = (
        discover_gemini_models(key, timeout=timeout)
        if provider == Provider.GEMINI
        else []
    )
    return resolve_model_for_provider(preferred_model, provider, discovered)


def generate_command(
    prompt: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout: int = 30,
) -> CommandSpec:
    if not api_key:
        raise ValueError("API anahtarı bulunamadı. Lütfen Ayarlar üzerinden veya uygun ortam değişkenini tanımlayın.")
    return CommandApiPipeline.from_api_key(api_key, timeout=timeout).generate(prompt, model=model)