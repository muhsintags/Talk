#!/usr/bin/env python3
# MIT License - Copyright (c) 2026 TALK contributors
"""
TALK CLI (Terminal Assistant via Language Knowledge) - Modern & Robust

Doğal dildeki istekleri yapay zeka (Google Gemini) ile tek satırlık güvenli Bash
komutuna çevirir, güvenlik denetiminden geçirir, canlı akışla (streaming) çalıştırır.

Kullanım:
  talk                         # Etkileşimli REPL kabuğu
  talk "bellek kullanımını gör" # Tek seferlik hızlı sorgu
  talk --gui                   # Grafik arayüzü başlat
  talk --test                  # API bağlantısını sına
  talk --history               # Geçmiş komutları listele
  talk --config                # Yapılandırmayı görüntüle
"""

from __future__ import annotations

import argparse
import os
import readline
import subprocess
import sys
from typing import Optional

# Core modüllerini içe aktar
import talk_core as core
from talk_core import (
    Config,
    load_config,
    RiskLevel,
    analyze_command,
    HistoryManager,
    test_api_connection,
    EXIT_HINTS,
    CommandSpec,
    ExecResult,
    TalkPipeline,
    evaluate_gate,
)

# Geriye dönük uyumluluk takma adları
VERSION = core.__version__
DEFAULT_MODEL = core.DEFAULT_MODEL
load_history = lambda limit=500: [e.prompt for e in HistoryManager().get_recent(limit)]
save_history_entry = lambda text: HistoryManager().add(text, text)


# --------------------------------------------------------------------------- #
# Terminal Renklendirme ve Biçimlendirme
# --------------------------------------------------------------------------- #

class Ansi:
    _enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    RESET = "\033[0m" if _enabled else ""
    BOLD = "\033[1m" if _enabled else ""
    DIM = "\033[2m" if _enabled else ""
    UNDERLINE = "\033[4m" if _enabled else ""

    # Renkler
    RED = "\033[38;5;196m" if _enabled else ""
    GREEN = "\033[38;5;46m" if _enabled else ""
    YELLOW = "\033[38;5;220m" if _enabled else ""
    BLUE = "\033[38;5;39m" if _enabled else ""
    MAGENTA = "\033[38;5;177m" if _enabled else ""
    CYAN = "\033[38;5;51m" if _enabled else ""
    WHITE = "\033[38;5;255m" if _enabled else ""
    GRAY = "\033[38;5;244m" if _enabled else ""

    # Arka planlar
    BG_RED = "\033[48;5;196m\033[30m" if _enabled else ""
    BG_YELLOW = "\033[48;5;220m\033[30m" if _enabled else ""
    BG_GREEN = "\033[48;5;46m\033[30m" if _enabled else ""


def print_banner(model_name: str) -> None:
    print(f"\n{Ansi.BOLD}{Ansi.CYAN}◆ TALK{Ansi.RESET} {Ansi.DIM}v{VERSION}{Ansi.RESET} — Terminal Assistant via Language Knowledge")
    print(f"{Ansi.GRAY}Model: {Ansi.WHITE}{model_name}{Ansi.GRAY} | CWD: {Ansi.WHITE}{os.getcwd()}{Ansi.RESET}")
    print(f"{Ansi.GRAY}Çıkış: 'exit', 'q' veya Ctrl+D | Kısayollar: [Enter]=Çalıştır, [e]=Düzenle, [k]=Kopyala{Ansi.RESET}\n")


def copy_to_clipboard(text: str) -> bool:
    """Panoya kopyalamayı dener (xclip, wl-copy, pbcopy, clip)."""
    tools = [
        ("pbcopy", []),
        ("wl-copy", []),
        ("xclip", ["-selection", "clipboard"]),
        ("clip.exe", []),
    ]
    for cmd, args in tools:
        try:
            p = subprocess.Popen([cmd] + args, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p.communicate(text.encode("utf-8"), timeout=1.0)
            if p.returncode == 0:
                return True
        except Exception:
            continue
    return False


# --------------------------------------------------------------------------- #
# Onay ve Etkileşim Kapısı
# --------------------------------------------------------------------------- #

def prompt_edit_command(initial_cmd: str) -> str:
    """Readline destekli olarak komutu düzenletir."""
    readline.set_startup_hook(lambda: readline.insert_text(initial_cmd))
    try:
        edited = input(f"{Ansi.BOLD}{Ansi.CYAN}Düzenle>{Ansi.RESET} ").strip()
    finally:
        readline.set_startup_hook(None)
    return edited or initial_cmd


def render_risk_badge(report: core.RiskReport) -> str:
    if report.level == RiskLevel.CRITICAL:
        return f"{Ansi.BG_RED} ✖ KRİTİK RİSK {Ansi.RESET}"
    elif report.level == RiskLevel.DANGEROUS:
        return f"{Ansi.BG_RED} ⚠ YÜKSEK RİSK {Ansi.RESET}"
    elif report.level == RiskLevel.CAUTION:
        return f"{Ansi.BG_YELLOW} ⚠ DİKKAT {Ansi.RESET}"
    return f"{Ansi.BG_GREEN} ✓ GÜVENLİ {Ansi.RESET}"


def confirm_command(cmd_spec: CommandSpec) -> Optional[str]:
    """
    Komutu güvenlik analizinden geçirir, kullanıcıya sunar.
    Dönüş: Çalıştırılacak komut (düzenlenmiş olabilir) veya iptal için None.
    """
    current_cmd = cmd_spec.command
    report = analyze_command(current_cmd)

    print(f"\n{Ansi.BOLD}Önerilen Komut:{Ansi.RESET}")
    print(f"  {Ansi.BOLD}{Ansi.CYAN}{current_cmd}{Ansi.RESET}  {render_risk_badge(report)}")
    if cmd_spec.explanation:
        print(f"  {Ansi.GRAY}↳ {cmd_spec.explanation}{Ansi.RESET}")

    if report.issues:
        print()
        for issue in report.issues:
            color = Ansi.RED if issue.level in (RiskLevel.CRITICAL, RiskLevel.DANGEROUS) else Ansi.YELLOW
            print(f"   {color}!{Ansi.RESET} {issue.title}: {Ansi.GRAY}{issue.description}{Ansi.RESET}")

    while True:
        if report.is_dangerous:
            if not cfg.allow_high_risk_commands:
                print(f"\n{Ansi.RED}{Ansi.BOLD}UYARI: Yüksek riskli komutlar için ayarlardan izin verin.{Ansi.RESET}")
                return None
            print(f"\n{Ansi.RED}{Ansi.BOLD}UYARI: Bu komut kalıcı değişiklik veya yetki yükseltme içeriyor!{Ansi.RESET}")
            prompt_text = (
                f"Çalıştırılsın mı? [{Ansi.GREEN}Enter=Evet{Ansi.RESET} | "
                f"{Ansi.YELLOW}e=Düzenle{Ansi.RESET} | {Ansi.CYAN}k=Kopyala{Ansi.RESET} | {Ansi.GRAY}i=İptal{Ansi.RESET}]: "
            )
        else:
            prompt_text = (
                f"Çalıştırılsın mı? [{Ansi.GREEN}Enter=Evet{Ansi.RESET} | "
                f"{Ansi.YELLOW}e=Düzenle{Ansi.RESET} | {Ansi.CYAN}k=Kopyala{Ansi.RESET} | {Ansi.GRAY}i=İptal{Ansi.RESET}]: "
            )

        try:
            choice = input(prompt_text).strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Ansi.YELLOW}İptal edildi.{Ansi.RESET}\n")
            return None

        clean_choice = choice.lower()

        if clean_choice in ("k", "kopyala", "copy"):
            if copy_to_clipboard(current_cmd):
                print(f"{Ansi.GREEN}✓ Komut panoya kopyalandı!{Ansi.RESET}")
            else:
                print(f"{Ansi.YELLOW}Panoya kopyalanamadı (sistem aracı eksik).{Ansi.RESET}")
            continue

        if clean_choice in ("e", "edit", "düzenle"):
            current_cmd = prompt_edit_command(current_cmd)
            report = analyze_command(current_cmd)
            print(f"\n{Ansi.BOLD}Güncellenen Komut:{Ansi.RESET}")
            print(f"  {Ansi.BOLD}{Ansi.CYAN}{current_cmd}{Ansi.RESET}  {render_risk_badge(report)}")
            continue

        if clean_choice in ("i", "iptal", "cancel", "n", "hayır"):
            print(f"{Ansi.YELLOW}Komut iptal edildi, çalıştırılmadı.{Ansi.RESET}\n")
            return None

        if report.is_dangerous:
            gate = evaluate_gate(current_cmd, allow_bypass=cfg.allow_high_risk_commands, block_critical=True)
            if gate.allowed:
                return current_cmd
            print(f"{Ansi.YELLOW}{gate.message}{Ansi.RESET}\n")
            return None

        if clean_choice in ("", "evet", "y", "yes"):
            gate = evaluate_gate(current_cmd, block_critical=True)
            if gate.allowed:
                return current_cmd
            print(f"{Ansi.RED}{gate.message}{Ansi.RESET}\n")
            return None
        print(f"{Ansi.YELLOW}İptal edildi.{Ansi.RESET}\n")
        return None


# --------------------------------------------------------------------------- #
# Canlı Akışla Çalıştırma (Live Streaming Runner)
# --------------------------------------------------------------------------- #

def run_command_live(pipeline: TalkPipeline, command: str, cfg: Config) -> ExecResult:
    """Komutu terminale canlı akışla yazdırır ve süreyi ölçer."""
    print(f"\n{Ansi.GRAY}── Çıktı Başlangıcı ──────────────────────────────────────{Ansi.RESET}")

    def on_chunk(stream: str, text: str) -> None:
        if stream == "stdout":
            sys.stdout.write(text)
            sys.stdout.flush()
        elif stream == "stderr":
            sys.stderr.write(f"{Ansi.RED}{text}{Ansi.RESET}")
            sys.stderr.flush()
        elif stream == "system":
            sys.stderr.write(f"{Ansi.YELLOW}{text}{Ansi.RESET}")
            sys.stderr.flush()

    result = pipeline.execute(command, on_chunk=on_chunk)
    print(f"{Ansi.GRAY}── Çıktı Sonu ───────────────────────────────────────────{Ansi.RESET}")

    dur_str = f"{result.duration_sec:.2f}s"
    if result.timed_out:
        print(f"{Ansi.RED}✗ Zaman aşımı ({cfg.exec_timeout} sn)!{Ansi.RESET}\n")
    elif result.returncode == 0:
        print(f"{Ansi.GREEN}✓ Başarılı{Ansi.RESET} {Ansi.GRAY}(Çıkış Kodu: 0 | Süre: {dur_str}){Ansi.RESET}\n")
    else:
        hint = EXIT_HINTS.get(result.returncode, "")
        hint_str = f" — {hint}" if hint else ""
        print(
            f"{Ansi.RED}✗ Hata: Çıkış Kodu {result.returncode}{hint_str}{Ansi.RESET} "
            f"{Ansi.GRAY}(Süre: {dur_str}){Ansi.RESET}\n"
        )
    return result


# --------------------------------------------------------------------------- #
# İstek İşleme Döngüsü
# --------------------------------------------------------------------------- #

def handle_user_request(prompt: str, cfg: Config, pipeline: TalkPipeline) -> None:
    if not pipeline.api_key():
        print(f"{Ansi.RED}[Hata] API anahtarı yapılandırılmamış!{Ansi.RESET}")
        print(f"{Ansi.GRAY}Anahtarınızı almak için: https://aistudio.google.com/apikey{Ansi.RESET}")
        print(f"Tanımlamak için: {Ansi.CYAN}export GEMINI_API_KEY='anahtariniz'{Ansi.RESET} veya GUI ayarlarını kullanın.\n")
        return

    print(f"{Ansi.DIM}✦ Komut oluşturuluyor ({cfg.model})...{Ansi.RESET}", end="\r", flush=True)

    try:
        spec = pipeline.generate(prompt)
    except Exception as exc:
        print(" " * 50, end="\r")
        print(f"{Ansi.RED}[API Hatası] {exc}{Ansi.RESET}\n")
        return

    print(" " * 50, end="\r")

    if spec.unsupported:
        print(f"{Ansi.YELLOW}⚠ Bu istek kabuk komutuna dönüştürülemedi.{Ansi.RESET}")
        if spec.explanation:
            print(f"  {Ansi.GRAY}Açıklama: {spec.explanation}{Ansi.RESET}\n")
        return

    command_to_run = confirm_command(spec)
    if not command_to_run:
        return

    result = run_command_live(pipeline, command_to_run, cfg)
    pipeline.record_run(prompt, command_to_run, spec.explanation, result)


# --------------------------------------------------------------------------- #
# CLI Ana Fonksiyonu
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="talk",
        description="TALK - Doğal dili Bash komutuna çevirip güvenli çalıştıran yapay zeka asistanı.",
    )
    parser.add_argument("request", nargs="*", help="Doğal dildeki istek (boş ise etkileşimli mod açılır)")
    parser.add_argument("-m", "--model", help="Kullanılacak Gemini modeli (örn: gemini-2.0-flash)")
    parser.add_argument("--gui", action="store_true", help="Grafik arayüzünü (GUI) başlat")
    parser.add_argument("--test", action="store_true", help="Gemini API bağlantısını test et")
    parser.add_argument("--history", action="store_true", help="Son komut geçmişini göster")
    parser.add_argument("--clear-history", action="store_true", help="Komut geçmişini temizle")
    parser.add_argument("--config", action="store_true", help="Mevcut yapılandırmayı görüntüle")
    parser.add_argument("-v", "--version", action="version", version=f"TALK v{VERSION}")

    args = parser.parse_args()

    if args.gui:
        try:
            import talk_gui
            talk_gui.main()
            return 0
        except ImportError as e:
            print(f"{Ansi.RED}[GUI Hatası] Grafik arayüz yüklenemedi: {e}{Ansi.RESET}", file=sys.stderr)
            return 1

    cfg = load_config()
    pipeline = TalkPipeline(cfg)
    history = pipeline.history

    if args.model:
        cfg.model = args.model

    if args.test:
        key = cfg.load_api_key(provider=cfg.model)
        if not key:
            print(f"{Ansi.RED}API anahtarı bulunamadı.{Ansi.RESET}")
            return 1
        print(f"Model: {cfg.model} ile test ediliyor...")
        ok, msg = test_api_connection(key, cfg.model)
        if ok:
            print(f"{Ansi.GREEN}✓ {msg}{Ansi.RESET}")
            return 0
        else:
            print(f"{Ansi.RED}✗ Bağlantı başarısız: {msg}{Ansi.RESET}")
            return 1

    if args.history:
        items = history.get_recent(25)
        if not items:
            print(f"{Ansi.GRAY}Henüz kayıtlı komut geçmişi yok.{Ansi.RESET}")
            return 0
        print(f"\n{Ansi.BOLD}Son Komut Geçmişi ({len(items)} kayıt):{Ansi.RESET}")
        for item in items:
            status = f"{Ansi.GREEN}✓{Ansi.RESET}" if item.returncode == 0 else f"{Ansi.RED}✗{Ansi.RESET}"
            print(f"{Ansi.GRAY}[{item.timestamp}]{Ansi.RESET} {status} {Ansi.BOLD}{item.prompt}{Ansi.RESET}")
            print(f"  {Ansi.CYAN}$ {item.command}{Ansi.RESET} {Ansi.DIM}({item.duration_sec or 0:.2f}s){Ansi.RESET}")
        print()
        return 0

    if args.clear_history:
        history.clear()
        print(f"{Ansi.GREEN}✓ Komut geçmişi başarıyla temizlendi.{Ansi.RESET}")
        return 0

    if args.config:
        print(f"\n{Ansi.BOLD}TALK Yapılandırması:{Ansi.RESET}")
        print(f"  Config Dosyası: {core.CONFIG_PATH}")
        print(f"  Model:          {cfg.model}")
        print(f"  API Zaman Aşımı: {cfg.api_timeout}s")
        print(f"  Çalıştırma Aşımı: {cfg.exec_timeout}s")
        key = cfg.load_api_key(provider=cfg.model)
        masked = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else ("Yok" if not key else "***")
        print(f"  API Anahtarı:    {masked}\n")
        return 0

    if args.request:
        prompt = " ".join(args.request).strip()
        handle_user_request(prompt, cfg, pipeline)
        return 0

    print_banner(cfg.model)

    for item in history.get_recent(100):
        try:
            readline.add_history(item.prompt)
        except Exception:
            pass

    while True:
        try:
            prompt = input(f"{Ansi.BOLD}{Ansi.GREEN}talk>{Ansi.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Ansi.GRAY}Görüşmek üzere!{Ansi.RESET}")
            break

        if not prompt:
            continue

        if prompt.lower() in ("exit", "quit", "q", "çıkış", "cikis"):
            print(f"{Ansi.GRAY}Görüşmek üzere!{Ansi.RESET}")
            break

        if prompt.lower() in ("clear", "cls"):
            os.system("clear" if os.name == "posix" else "cls")
            continue

        handle_user_request(prompt, cfg, pipeline)

    return 0


if __name__ == "__main__":
    sys.exit(main())