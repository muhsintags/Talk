"""
TALK Core - Command Execution Engine
Gerçek zamanlı çıktı akışı (streaming), süreç grubu izolasyonu ve zaman aşımı yönetimi.
"""

from __future__ import annotations

import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from typing import Iterator, Optional, Dict, Tuple
from .models import ExecChunk, ExecResult

EXIT_HINTS: Dict[int, str] = {
    1: "Genel hata veya geçersiz sözdizimi.",
    2: "Kabuk dahili komutunun hatalı kullanımı.",
    126: "Komut bulundu ancak çalıştırma yetkisi (execute permission) yok.",
    127: "Komut bulunamadı; PATH değişkenini veya paket kurulumunu kontrol edin.",
    128: "Geçersiz çıkış argümanı ile sonlandı.",
    130: "Kullanıcı tarafından klavye kesmesiyle durduruldu (SIGINT / Ctrl+C).",
    137: "İşlem zorla sonlandırıldı (SIGKILL / OOM Bellek yetersizliği).",
    143: "İşlem sonlandırma sinyali aldı (SIGTERM).",
}


def find_bash() -> str:
    """Sistemdeki Bash çalıştırılabilir dosyasını bulur."""
    bash = shutil.which("bash")
    if bash:
        return bash

    # Windows Git-Bash / WSL alternatifleri
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

        wsl = shutil.which("wsl")
        if wsl:
            return wsl

    raise RuntimeError("Bash kabuğu bulunamadı. Linux/macOS veya Windows'ta Git Bash / WSL kullanın.")


def _kill_proc_tree(proc: subprocess.Popen) -> None:
    """Tüm alt süreçleri kapsayan süreç grubunu sonlandırır."""
    try:
        if os.name == "posix" and hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def execute_stream(
    command: str,
    bash_path: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout: int = 60,
    max_output_chars: int = 200_000,
) -> Iterator[Tuple[str, str]]:
    """
    (stream_type, text) şeklinde generator döndürür.
    stream_type: 'stdout' | 'stderr' | 'system' | 'exit'
    'exit' chunk'ı string olarak returncode döndürür.
    """
    bash = bash_path or find_bash()
    work_dir = cwd or os.getcwd()

    proc = subprocess.Popen(
        [bash, "-c", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=work_dir,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=(os.name == "posix"),
    )

    q: queue.Queue[Optional[Tuple[str, str]]] = queue.Queue()

    def reader(pipe, stream_name: str):
        try:
            for line in iter(pipe.readline, ""):
                q.put((stream_name, line))
        except Exception:
            pass
        finally:
            pipe.close()

    t_out = threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True)
    t_err = threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    start_time = time.time()
    timed_out = False
    total_chars = 0
    truncated = False

    while proc.poll() is None:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            timed_out = True
            _kill_proc_tree(proc)
            break

        try:
            item = q.get(timeout=0.05)
            if item:
                stream_name, text = item
                total_chars += len(text)
                if total_chars <= max_output_chars:
                    yield (stream_name, text)
                elif not truncated:
                    truncated = True
                    yield ("system", "[UYARI] Çıktı boyutu sınırını aştı; kırpılıyor...\n")
        except queue.Empty:
            continue

    # Kalan borulardaki son çıktıları topla
    t_out.join(timeout=0.5)
    t_err.join(timeout=0.5)
    while not q.empty():
        try:
            item = q.get_nowait()
            if item:
                stream_name, text = item
                total_chars += len(text)
                if total_chars <= max_output_chars:
                    yield (stream_name, text)
        except queue.Empty:
            break

    if timed_out:
        yield ("system", f"[ZAMAN AŞIMI] Komut {timeout} saniye içinde tamamlanamadı ve durduruldu.\n")
        yield ("exit", "-1")
    else:
        ret = proc.poll()
        yield ("exit", str(ret if ret is not None else 0))


def run_command(
    command: str,
    bash_path: Optional[str] = None,
    cwd: Optional[str] = None,
    timeout: int = 60,
    max_output_chars: int = 200_000,
) -> ExecResult:
    """
    Komutu tamamlanana kadar çalıştırıp ExecResult döndürür.
    """
    start_time = time.time()
    stdout_parts = []
    stderr_parts = []
    timed_out = False
    truncated = False
    returncode = 0

    try:
        bash = bash_path or find_bash()
    except Exception as e:
        return ExecResult(stdout="", stderr=str(e), returncode=127, duration_sec=0.0)

    for stream, text in execute_stream(
        command,
        bash_path=bash,
        cwd=cwd,
        timeout=timeout,
        max_output_chars=max_output_chars,
    ):
        if stream == "stdout":
            stdout_parts.append(text)
        elif stream == "stderr":
            stderr_parts.append(text)
        elif stream == "system":
            if "[ZAMAN AŞIMI]" in text:
                timed_out = True
            if "kırpılıyor" in text:
                truncated = True
        elif stream == "exit":
            try:
                returncode = int(text)
            except ValueError:
                returncode = -1

    duration = time.time() - start_time
    return ExecResult(
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        returncode=returncode,
        duration_sec=round(duration, 3),
        timed_out=timed_out,
        truncated=truncated,
    )