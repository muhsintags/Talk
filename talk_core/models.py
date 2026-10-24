"""
TALK Core - Data Models
Modüler ve tip-güvenli veri yapıları.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class RiskLevel(str, Enum):
    SAFE = "SAFE"           # Salt-okunur veya zararsız komutlar (ls, cat, df, top)
    CAUTION = "CAUTION"     # Dosya değişikliği, servis açma/kapama, paket yönetimi
    DANGEROUS = "DANGEROUS" # Dosya silme, yetki yükseltme, ağır disk işlemleri
    CRITICAL = "CRITICAL"   # Fork bombası, disk formatlama, kök dizin silme


@dataclass
class RiskIssue:
    level: RiskLevel
    title: str
    description: str
    pattern: str = ""
    matched_text: str = ""


@dataclass
class RiskReport:
    level: RiskLevel
    issues: List[RiskIssue] = field(default_factory=list)

    @property
    def is_dangerous(self) -> bool:
        return self.level in (RiskLevel.DANGEROUS, RiskLevel.CRITICAL)

    @property
    def needs_caution(self) -> bool:
        return self.level == RiskLevel.CAUTION

    @property
    def reasons(self) -> List[str]:
        return [f"[{issue.level.value}] {issue.title}: {issue.description}" for issue in self.issues]


@dataclass
class CommandSpec:
    prompt: str
    command: str
    explanation: str = ""
    unsupported: bool = False
    model: str = ""
    raw_response: str = ""


@dataclass
class ExecChunk:
    stream: str  # "stdout" | "stderr" | "system"
    text: str


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    returncode: int
    duration_sec: float = 0.0
    timed_out: bool = False
    truncated: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class HistoryEntry:
    id: str
    timestamp: str
    prompt: str
    command: str
    explanation: str = ""
    returncode: Optional[int] = None
    duration_sec: Optional[float] = None
    risk_level: str = "SAFE"