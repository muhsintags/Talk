"""
TALK Core - Request pipeline (generate → assess → execute → history).

CLI ve GUI tek iş akışını paylaşır; UI katmanı ince kalır.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Optional, Tuple

from .config import Config
from .executor import execute_stream, find_bash
from .history import HistoryManager
from .api.pipeline import CommandApiPipeline
from .models import CommandSpec, ExecResult
from .security import analyze_command

StreamCallback = Callable[[str, str], None]
ChunkIterator = Iterator[Tuple[str, str]]


class TalkPipeline:
    """Doğal dil isteğinden güvenli çalıştırmaya kadar ortak mantık."""

    def __init__(self, cfg: Config, history: Optional[HistoryManager] = None):
        self.cfg = cfg
        self.history = history or HistoryManager()
        self._api = CommandApiPipeline.from_config(cfg)

    def api_key(self) -> str:
        return self.cfg.load_api_key(model=self.cfg.model)

    def generate(self, prompt: str) -> CommandSpec:
        if not self.api_key():
            raise ValueError(
                "API anahtarı yapılandırılmamış. "
                "GEMINI_API_KEY / GROQ_API_KEY ortam değişkeni veya ~/.talk/config.json kullanın."
            )
        text = (prompt or "").strip()
        if not text:
            raise ValueError("Boş istek.")
        return self._api.generate(text, model=self.cfg.model)

    def assess(self, command: str):
        return analyze_command(command)

    def stream_execute(self, command: str) -> ChunkIterator:
        bash = find_bash()
        return execute_stream(
            command,
            bash_path=bash,
            timeout=self.cfg.exec_timeout,
            max_output_chars=self.cfg.max_output_chars,
        )

    def execute(
        self,
        command: str,
        on_chunk: Optional[StreamCallback] = None,
    ) -> ExecResult:
        start = time.time()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        timed_out = False
        truncated = False
        returncode = 0

        try:
            for stream, text in self.stream_execute(command):
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
                if on_chunk and stream in ("stdout", "stderr", "system"):
                    on_chunk(stream, text)
        except KeyboardInterrupt:
            returncode = 130

        duration = time.time() - start
        return ExecResult(
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            returncode=returncode,
            duration_sec=round(duration, 3),
            timed_out=timed_out,
            truncated=truncated,
        )

    def record_run(
        self,
        prompt: str,
        command: str,
        explanation: str,
        result: ExecResult,
    ) -> None:
        self.history.add(
            prompt=prompt,
            command=command,
            explanation=explanation,
            risk_level=self.assess(command).level.value,
            returncode=result.returncode,
            duration_sec=result.duration_sec,
        )
