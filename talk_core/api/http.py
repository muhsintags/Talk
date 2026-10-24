from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


def post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
) -> Tuple[int, Dict[str, Any], str]:
    """
    JSON POST; dönüş: (status_code, parsed_body_or_empty, error_message).
    HTTP hatalarında exception fırlatmaz — çağıran sınıflandırır.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}, ""
    except urllib.error.HTTPError as exc:
        msg = ""
        try:
            raw = exc.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            msg = (
                parsed.get("error", {}).get("message")
                or parsed.get("message")
                or exc.reason
                or ""
            )
        except Exception:
            msg = exc.reason or ""
        return exc.code, {}, str(msg)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return 408, {}, "Zaman aşımı"
        return 0, {}, f"Bağlantı hatası: {exc.reason}"
    except TimeoutError:
        return 408, {}, "Zaman aşımı"


def get_json(url: str, headers: Dict[str, str], timeout: int) -> Tuple[int, Dict[str, Any], str]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}, ""
    except urllib.error.HTTPError as exc:
        msg = exc.reason or ""
        return exc.code, {}, str(msg)
    except Exception as exc:
        return 0, {}, str(exc)
