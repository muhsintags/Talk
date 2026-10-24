"""
TALK Core - Shared execution gate / confirmation policy.

CLI ve GUI aynı kuralları kullanır: kritik engel, tehlikeli komutlarda açık onay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import RiskLevel
from .security import analyze_command


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    message: str = ""


def evaluate_gate(
    command: str,
    *,
    explicit_confirm: str = "",
    bypass_confirmation: bool = False,
    allow_bypass: Optional[bool] = None,
    block_critical: bool = True,
) -> GateDecision:
    """
    Komutun çalıştırılıp çalıştırılamayacağını değerlendirir.

    explicit_confirm: Eski uyumluluk için korunur; artık yüksek riskli komutlarda
    metin girişi gerektirmez. Ayar açık olduğunda doğrudan izin verilir.
    bypass_confirmation: Kullanıcı bilinçli olarak güvenlik onayını atladı (GUI/ayarlar).
    block_critical: CRITICAL seviyesinde komutları tamamen engelle.
    """
    cmd = (command or "").strip()
    if not cmd:
        return GateDecision(False, "Boş komut.")

    report = analyze_command(cmd)

    if block_critical and report.level == RiskLevel.CRITICAL:
        return GateDecision(
            False,
            "Kritik risk tespit edildi; bu komut çalıştırılamaz. Komutu düzenleyin veya iptal edin.",
        )

    if bypass_confirmation:
        if allow_bypass is False:
            return GateDecision(
                False,
                "Yüksek riskli komutlar için Ayarlar > 'Yüksek riskli komutların çalışmasına izin ver' seçeneğini açın.",
            )
        return GateDecision(True)

    if report.is_dangerous:
        if allow_bypass is True:
            return GateDecision(True)
        return GateDecision(
            False,
            "Yüksek riskli komutlar için Ayarlar > 'Yüksek riskli komutların çalışmasına izin ver' seçeneğini açın.",
        )

    return GateDecision(True)
