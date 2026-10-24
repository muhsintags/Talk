"""
TALK Core - Security Engine & Threat Scanner
Kabuk komutlarını derinlemesine analiz eden güvenlik motoru.
"""

from __future__ import annotations

import re
from typing import List, Tuple
from .models import RiskLevel, RiskIssue, RiskReport

CRITICAL_RULES: List[Tuple[str, str, str]] = [
    (
        r":\(\)\s*\{\s*:\|:&\s*\};:",
        "Fork Bombası",
        "Sistemi kilitleyen fork bombası deseni tespit edildi.",
    ),
    (
        r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+/(?:\s|$|\*)",
        "Kök Dizin Silme (rm -rf /)",
        "Tüm işletim sistemi kök dizinini geri dönülemez biçimde yok edebilir.",
    ),
    (
        r">\s*/dev/sd[a-z0-9]",
        "Ham Disk Üzerine Yazma",
        "Depolama aygıtının ham bloklarına doğrudan yazarak bölüntü tablosunu bozar.",
    ),
    (
        r"\bdd\b[^\n]*\bof=/dev/sd",
        "Ham Blok Kopyalama (dd of=/dev/sdX)",
        "Fiziksel diski doğrudan ezebilir.",
    ),
    (
        r"\bmkfs(\.\w+)?\b",
        "Dosya Sistemi Formatlama",
        "Disk bölümünü sıfırlayarak dosya sistemini biçimlendirir.",
    ),
    (
        r"\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?(ba|z)?sh\b",
        "Uzak Script İndir ve Çalıştır Zinciri",
        "İnternetten indirilen içeriğin denetlenmeden doğrudan kabukta çalıştırılması çok tehlikelidir.",
    ),
    (
        r"\$\([^\n]*\b(rm|mkfs|dd|sudo|curl|wget|chmod|chown|truncate|shutdown|reboot|mount|umount|kill|pkill|killall|passwd|userdel|groupdel)\b[^\n]*\)",
        "Komut Değiştirme (Command Substitution)",
        "Komut yerleşimi içinde riskli bir kabuk işlemi çalıştırılmaktadır; tehlikeli bir zincir oluşabilir.",
    ),
    (
        r"`[^`\n]*(rm|mkfs|dd|sudo|curl|wget|chmod|chown|truncate|shutdown|reboot|mount|umount|kill|pkill|killall|passwd|userdel|groupdel)[^`\n]*`",
        "Backtick Komut Yürütme",
        "Backtick ile işlenen komut içeriği doğrudan kabukta çalıştırılmaktadır.",
    ),
]

DANGEROUS_RULES: List[Tuple[str, str, str]] = [
    (
        r"\$\([^\n]*\)",
        "Komut Değiştirme (Command Substitution)",
        "Yaygın olarak shell içinde ek komut çalıştırmak için kullanılır; gömülü riskleri artırır.",
    ),
    (
        r"`[^`\n]*`",
        "Backtick Komut Çalıştırma",
        "Komut çıktısı doğrudan kabukta çalıştırılabilir; güvenlik riskini artırır.",
    ),
    (
        r"\bsh\s+-c\b|\b(?:ba|z)?sh\s+-c\b",
        "Kabuk Çalıştırma (sh -c)",
        "Dinamik kabuk komutları başlatılır; ek komutların çalışmasına izin verir.",
    ),
    (
        r"\brm\b",
        "Dosya / Dizin Silme",
        "Belirtilen dosya veya dizinleri kalıcı olarak siler.",
    ),
    (
        r"\brmdir\b",
        "Dizin Silme (rmdir)",
        "Belirtilen dizini siler.",
    ),
    (
        r"\bfind\b[^\n]*\s-delete\b",
        "Toplu Silme (find -delete)",
        "Eşleşen tüm dosyaları topluca siler.",
    ),
    (
        r"\bfind\b[^\n]*-exec\s+rm\b",
        "Toplu Silme (find -exec rm)",
        "Arama sonucundaki her dosya için silme komutu çalıştırır.",
    ),
    (
        r"\bshred\b",
        "Dosya İmhası (shred)",
        "Dosyanın üzerini rastgele veriyle ezerek geri kurtarılamaz yapar.",
    ),
    (
        r"\btruncate\b",
        "Dosya Sıfırlama (truncate)",
        "Dosya boyutunu sıfırlayabilir veya kırpabilir.",
    ),
    (
        r"\bsudo\b",
        "Yükseltilmiş Yetki (sudo)",
        "Komut root (yönetici) ayrıcalıkları ile çalıştırılacak.",
    ),
    (
        r"\b(userdel|groupdel|passwd|chroot)\b",
        "Kullanıcı / Yetki Değişikliği",
        "Kullanıcı hesabı, parola veya chroot ortamını değiştirir.",
    ),
    (
        r"\b(shutdown|reboot|halt|poweroff)\b",
        "Sistem Kapatma / Yeniden Başlatma",
        "Sistem oturumunu sonlandırır veya makineyi kapatır.",
    ),
    (
        r"\beval\b",
        "Dinamik Komut Yürütme (eval)",
        "Gizli veya zararlı kabuk komutlarının yürütülmesine zemin hazırlayabilir.",
    ),
    (
        r"\bxargs\b[^\n]*\brm\b",
        "Toplu Silme (xargs rm)",
        "Girdideki parametreleri rm komutuna ileterek toplu silme yapar.",
    ),
    (
        r">\s*(/etc/|/boot/|/usr/|/var/|/root/|~/\.ssh|\$HOME/\.ssh|~/\.(bashrc|zshrc|profile)|\$HOME/\.(bashrc|zshrc|profile))",
        "Kritik Sistem/Yapılandırma Dosyasına Yazma",
        "Sistem yapılandırma dosyalarını veya SSH anahtarlarını ezebilir.",
    ),
    (
        r"\bgit\s+push\b[^\n]*--force",
        "Git Zorlamalı Gönderme (--force)",
        "Uzak depodaki geçmişi ve takım arkadaşlarının commitlerini ezebilir.",
    ),
    (
        r"\bgit\s+reset\b[^\n]*--hard",
        "Git Yerel Sıfırlama (--hard)",
        "Henüz commit edilmemiş tüm yerel değişiklikleri kalıcı olarak siler.",
    ),
    (
        r"\bcrontab\s+-r\b",
        "Zamanlanmış Görevleri Silme",
        "Kullanıcıya ait tüm crontab kayıtlarını siler.",
    ),
    (
        r"\bhistory\s+-c\b",
        "Komut Geçmişini Temizleme",
        "Kabuk geçmişini temizleyerek denetim izini siler.",
    ),
]

CAUTION_RULES: List[Tuple[str, str, str]] = [
    (
        r"\b(chmod|chown)\b",
        "Dosya İzni / Sahiplik Değişimi",
        "Dosya erişim haklarını veya sahipliğini değiştirir.",
    ),
    (
        r"\b(mv|ln)\b",
        "Dosya Taşıma / Bağlantı Oluşturma",
        "Dosyaların yerini değiştirebilir veya sembolik bağlantı oluşturur.",
    ),
    (
        r"\bsed\b[^\n]*\s-i\b",
        "Dosya Üzerine Yazma (sed -i)",
        "Dosyayı doğrudan yerinde düzenler.",
    ),
    (
        r"\b(systemctl|service)\b",
        "Servis Yönetimi",
        "Arka plan servislerini başlatır, durdurur veya yeniden başlatır.",
    ),
    (
        r"\b(kill|pkill|killall)\b",
        "Süreç Sonlandırma",
        "Çalışan süreçlere sinyal göndererek sonlandırır.",
    ),
    (
        r"\b(mount|umount)\b",
        "Disk Bağlama / Ayırma",
        "Dosya sistemlerini sisteme bağlar veya sistemden ayırır.",
    ),
    (
        r"\b(apt|apt-get|dnf|yum|pacman|brew|apk|zypper)\b[^\n]*\b(install|remove|purge|upgrade|update)\b",
        "Paket Yöneticisi Değişikliği",
        "Sisteme paket kurar, günceller veya kaldırır.",
    ),
    (
        r"\b(export|unset)\s+[A-Za-z_]+=",
        "Ortam Değişkeni Değişimi",
        "Kabuk ortam değişkenlerini değiştirir.",
    ),
    (
        r">\s*[^>\s]",
        "Dosyaya Yönlendirme (>)",
        "Hedef dosyanın mevcut içeriğini ezebilir.",
    ),
]

_COMPILED_CRITICAL = [(re.compile(p, re.IGNORECASE), t, d) for p, t, d in CRITICAL_RULES]
_COMPILED_DANGEROUS = [(re.compile(p, re.IGNORECASE), t, d) for p, t, d in DANGEROUS_RULES]
_COMPILED_CAUTION = [(re.compile(p, re.IGNORECASE), t, d) for p, t, d in CAUTION_RULES]

_ALLOWED_DESKTOP_DELETE_EXTENSIONS = ("ipynb", "mp4", "png", "pdf", "json", "zip", "7z")


def _is_user_desktop_cleanup(command: str) -> bool:
    """Kullanıcı masaüstündeki medya/doküman dosyalarını hedef alan toplu silme komutlarına özel izin verir."""
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

    extensions = "|".join(_ALLOWED_DESKTOP_DELETE_EXTENSIONS)
    if not re.search(rf"(?:\.(?:{extensions})|\*\.(?:{extensions})|(?:-name|-iname)\s+['\"]?\*\.(?:{extensions})['\"]?)", cmd, re.IGNORECASE):
        return False

    if re.search(r"\b(?:sudo|curl|wget|bash\s+-c|sh\s+-c|\|\s*(?:sudo\s+)?(?:ba|z)?sh)\b", cmd, re.IGNORECASE):
        return False

    return True


def analyze_command(command: str) -> RiskReport:
    """
    Verilen kabuk komutunu tarar ve ayrıntılı RiskReport oluşturur.
    """
    clean_cmd = (command or "").strip()
    if _is_user_desktop_cleanup(clean_cmd):
        return RiskReport(level=RiskLevel.SAFE, issues=[])

    issues: List[RiskIssue] = []

    # Çok satırlı komut enjeksiyon kontrolü
    if "\n" in clean_cmd:
        issues.append(
            RiskIssue(
                level=RiskLevel.CRITICAL,
                title="Çok Satırlı Komut Tespit Edildi",
                description="Komut birden fazla bağımsız satır içeriyor; güvenlik gereği engellendi.",
                matched_text="\\n",
            )
        )

    # 1. Kritik kontroller
    for rx, title, desc in _COMPILED_CRITICAL:
        match = rx.search(clean_cmd)
        if match:
            issues.append(
                RiskIssue(
                    level=RiskLevel.CRITICAL,
                    title=title,
                    description=desc,
                    pattern=rx.pattern,
                    matched_text=match.group(0),
                )
            )

    # 2. Tehlikeli kontroller
    for rx, title, desc in _COMPILED_DANGEROUS:
        match = rx.search(clean_cmd)
        if match:
            issues.append(
                RiskIssue(
                    level=RiskLevel.DANGEROUS,
                    title=title,
                    description=desc,
                    pattern=rx.pattern,
                    matched_text=match.group(0),
                )
            )

    # 3. Dikkat gerektiren kontroller
    for rx, title, desc in _COMPILED_CAUTION:
        match = rx.search(clean_cmd)
        if match:
            issues.append(
                RiskIssue(
                    level=RiskLevel.CAUTION,
                    title=title,
                    description=desc,
                    pattern=rx.pattern,
                    matched_text=match.group(0),
                )
            )

    # En yüksek risk seviyesini belirle
    if any(i.level == RiskLevel.CRITICAL for i in issues):
        level = RiskLevel.CRITICAL
    elif any(i.level == RiskLevel.DANGEROUS for i in issues):
        level = RiskLevel.DANGEROUS
    elif any(i.level == RiskLevel.CAUTION for i in issues):
        level = RiskLevel.CAUTION
    else:
        level = RiskLevel.SAFE

    return RiskReport(level=level, issues=issues)


def is_dangerous(command: str) -> bool:
    rep = analyze_command(command)
    return rep.is_dangerous


def needs_caution(command: str) -> bool:
    rep = analyze_command(command)
    return rep.needs_caution


def get_risk_reasons(command: str) -> List[str]:
    rep = analyze_command(command)
    return rep.reasons