#!/usr/bin/env python3
# MIT License - Copyright (c) 2026 TALK contributors
"""
TALK GUI (Terminal Assistant via Language Knowledge) - Modern Desktop GUI

Özellikler:
  - Şık Tokyo Night / Dark Terminal teması
  - Gerçek zamanlı çıktı akışı (live execution streaming)
  - Dinamik Güvenlik Kapısı (Risk Rozetleri, Düzenleme ve Onaylama Alanı)
  - Entegre Geçmiş Çekmecesi (arama ve tek tıkla yeniden çalıştırma)
  - API Bağlantı Testi içeren gelişmiş Ayarlar Penceresi
  - Standart kütüphane tabanlı (Harici ağır paket gerekmez)
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Optional, List

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, font as tkfont
except ImportError as exc:
    raise SystemExit("tkinter bulunamadı. Linux için: sudo apt install python3-tk") from exc

import talk_core as core
from talk_core import (
    load_config,
    RiskLevel,
    analyze_command,
    generate_command,
    test_api_connection,
    EXIT_HINTS,
    CommandSpec,
    TalkPipeline,
    evaluate_gate,
)
from talk_core.models import ExecResult

AI_STUDIO_URL = "https://aistudio.google.com/app/apikey"
MAX_TERM_LINES = 6000
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "talk_icon.png"
APP_ICON_ICO_PATH = Path(__file__).resolve().parent / "assets" / "talk_icon.ico"


def apply_app_icon(root: tk.Misc):
    """Set the window/taskbar icon using the bundled design asset."""
    icon_png = APP_ICON_PATH
    icon_ico = APP_ICON_ICO_PATH
    if not icon_png.exists() and not icon_ico.exists():
        return None

    photo = None
    try:
        if icon_png.exists():
            photo = tk.PhotoImage(file=str(icon_png))
            root.iconphoto(True, photo)
    except Exception:
        photo = None

    if photo is None:
        try:
            if icon_ico.exists():
                root.iconbitmap(default=str(icon_ico))
        except Exception:
            pass
    return photo

# -----------------------------------------------------------------------------
# Tokyo Night / Modern Dark Palette
# -----------------------------------------------------------------------------
THEME = {
    "bg": "#0f141c",          # Ana arka plan
    "surface": "#161d27",     # Panel / kart arka planı
    "surface_light": "#1e2736",
    "border": "#283446",      # İnce çerçeveler
    "text": "#d8e2ed",        # Standart metin
    "muted": "#6b7c96",       # İkincil / soluk metin
    "cyan": "#00e5bf",        # Turkuaz vurgu (prompt)
    "blue": "#38bdf8",        # Canlı mavi
    "purple": "#c084fc",      # Komut rengi
    "green": "#22c55e",       # Başarı / Güvenli
    "amber": "#f59e0b",       # Dikkat / Uyarı
    "red": "#ef4444",         # Kritik / Hata
    "danger_bg": "#3c151b",   # Yüksek risk arka planı
    "danger_fg": "#ff6b6b",
}


def pick_best_font(root: tk.Misc) -> str:
    """Sistemdeki en okunaklı monospace yazı tipini seçer."""
    try:
        available = set(tkfont.families(root))
        for family in (
            "JetBrains Mono",
            "Fira Code",
            "Cascadia Code",
            "Source Code Pro",
            "Ubuntu Mono",
            "Consolas",
            "DejaVu Sans Mono",
            "Menlo",
            "Monaco",
        ):
            if family in available:
                return family
    except Exception:
        pass
    return "Courier"


# -----------------------------------------------------------------------------
# Ayarlar Penceresi (Modal Dialog)
# -----------------------------------------------------------------------------
class SettingsModal(tk.Toplevel):
    def __init__(self, parent: "TalkApp"):
        super().__init__(parent)
        self.parent = parent
        self.title("TALK — Yapılandırma ve Ayarlar")
        self.geometry("520x460")
        self.minsize(480, 420)
        self.configure(bg=THEME["surface"])
        self.transient(parent)
        self.grab_set()

        x = parent.winfo_x() + (parent.winfo_width() // 2) - 260
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 230
        self.geometry(f"+{max(10, x)}+{max(10, y)}")

        self.font_family = parent.font_family
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 20, "pady": 6}

        # Başlık
        title_frame = tk.Frame(self, bg=THEME["surface"])
        title_frame.pack(fill="x", padx=20, pady=(16, 12))
        tk.Label(
            title_frame, text="⚙ Yapılandırma", bg=THEME["surface"], fg=THEME["cyan"],
            font=(self.font_family, 13, "bold"),
        ).pack(side="left")

        # API Keyler
        key_label_f = tk.Frame(self, bg=THEME["surface"])
        key_label_f.pack(fill="x", **pad)
        tk.Label(
            key_label_f, text="AI API Anahtarları:", bg=THEME["surface"], fg=THEME["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")

        link = tk.Label(
            key_label_f, text="[AI Studio'dan Al ↗]", bg=THEME["surface"], fg=THEME["blue"],
            cursor="hand2", font=(self.font_family, 9, "underline"),
        )
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: webbrowser.open(AI_STUDIO_URL))

        self.api_key_rows = []
        self.api_key_vars = []
        self.api_key_providers: List[str] = []
        self.key_entry = None
        self.key_var = tk.StringVar(value="")
        self.show_var = tk.BooleanVar(value=False)
        self.keys_container = tk.Frame(self, bg=THEME["surface"])
        self.keys_container.pack(fill="x", **pad)
        self._render_api_keys()

        add_key_frame = tk.Frame(self, bg=THEME["surface"])
        add_key_frame.pack(fill="x", **pad)
        tk.Button(
            add_key_frame, text="Add Google API key", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=(self.font_family, 9), cursor="hand2", command=lambda: self._add_api_key_row("google"),
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            add_key_frame, text="Add Groq API key", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=(self.font_family, 9), cursor="hand2", command=lambda: self._add_api_key_row("groq"),
        ).pack(side="left")
        tk.Checkbutton(
            add_key_frame, text="Göster", variable=self.show_var, command=self._toggle_show,
            bg=THEME["surface"], fg=THEME["muted"], activebackground=THEME["surface"],
            activeforeground=THEME["text"], selectcolor=THEME["bg"],
            font=(self.font_family, 9), relief="flat", cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        self.safe_mode_var = tk.BooleanVar(value=self.parent.cfg.allow_high_risk_commands)
        tk.Checkbutton(
            self,
            text="Yüksek riskli komutların çalışmasına izin ver",
            variable=self.safe_mode_var,
            bg=THEME["surface"],
            fg=THEME["text"],
            activebackground=THEME["surface"],
            selectcolor=THEME["bg"],
            font=(self.font_family, 9),
            anchor="w",
        ).pack(fill="x", padx=20, pady=(4, 0))

        # Test Butonu ve Test Durumu
        test_frame = tk.Frame(self, bg=THEME["surface"])
        test_frame.pack(fill="x", padx=20, pady=(2, 10))

        self.test_btn = tk.Button(
            test_frame, text="⚡ Bağlantıyı Sına", bg=THEME["surface_light"], fg=THEME["text"],
            activebackground=THEME["border"], relief="flat", font=(self.font_family, 9),
            cursor="hand2", command=self._test_connection,
        )
        self.test_btn.pack(side="left")

        self.test_status_lbl = tk.Label(
            test_frame, text="", bg=THEME["surface"], fg=THEME["muted"], font=(self.font_family, 9),
        )
        self.test_status_lbl.pack(side="left", padx=10)

        # İşletim Sistemi Seçimi
        tk.Label(
            self, text="İşletim Sistemi:", bg=THEME["surface"], fg=THEME["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", **pad)

        self.os_preset_var = tk.StringVar(value=self.parent.cfg.get("os_preset") or "linux")
        self.custom_os_var = tk.StringVar(value=self.parent.cfg.get("os_custom") or "")
        self.os_buttons = {}
        os_btn_frame = tk.Frame(self, bg=THEME["surface"])
        os_btn_frame.pack(fill="x", padx=20, pady=(0, 6))

        for key, label in (("windows11", "Windows 11"), ("macos", "macOS"), ("linux", "Linux Debian")):
            btn = tk.Button(
                os_btn_frame, text=label, width=16,
                bg=THEME["surface_light"], fg=THEME["text"], relief="flat",
                font=(self.font_family, 9), cursor="hand2",
                command=lambda selected=key: self._select_os_preset(selected),
            )
            btn.pack(side="left", padx=(0, 8))
            self.os_buttons[key] = btn
            if self.os_preset_var.get() == key:
                btn.configure(bg=THEME["cyan"], fg="#051419")

        tk.Label(
            self, text="Özel işletim sistemi:", bg=THEME["surface"], fg=THEME["text"],
            font=(self.font_family, 9),
        ).pack(anchor="w", **pad)
        tk.Entry(
            self, textvariable=self.custom_os_var, bg=THEME["bg"], fg=THEME["text"],
            relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["cyan"], font=(self.font_family, 10),
        ).pack(fill="x", padx=20, pady=(0, 8))

        # Model Seçimi
        tk.Label(
            self, text="Yapay Zeka Modeli:", bg=THEME["surface"], fg=THEME["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(anchor="w", **pad)

        model_row = tk.Frame(self, bg=THEME["surface"])
        model_row.pack(fill="x", padx=20, pady=2)

        self.model_var = tk.StringVar(value=self.parent.cfg.model)
        model_dropdown = ttk.Combobox(
            model_row, textvariable=self.model_var, values=core.AVAILABLE_MODELS, font=(self.font_family, 10),
        )
        model_dropdown.pack(side="left", fill="x", expand=True, ipady=2)

        tk.Button(
            model_row, text="Auto / Otomatik", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=(self.font_family, 9), cursor="hand2", command=self._set_auto_model,
        ).pack(side="right", padx=(8, 0))

        # Zaman Aşımı (Timeout)
        to_frame = tk.Frame(self, bg=THEME["surface"])
        to_frame.pack(fill="x", padx=20, pady=(12, 6))

        tk.Label(
            to_frame, text="Komut Çalıştırma Zaman Aşımı (sn):", bg=THEME["surface"], fg=THEME["text"],
            font=(self.font_family, 10),
        ).pack(side="left")

        self.timeout_var = tk.StringVar(value=str(self.parent.cfg.exec_timeout))
        tk.Entry(
            to_frame, textvariable=self.timeout_var, width=6, bg=THEME["bg"], fg=THEME["text"],
            relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["cyan"], font=(self.font_family, 10), justify="center",
        ).pack(side="right")

        # Bilgi Notu
        tk.Label(
            self,
            text="* Keyring destekleniyorsa anahtar işletim sistemi kasasında tutulur.\n"
                 "* Auto / Otomatik modu, mevcut Gemini ve Groq modelleri arasında uygun alternatifi seçer.\n"
                 "* Boş bırakılırsa uygun ortam değişkeni (GEMINI_API_KEY / GROQ_API_KEY) kullanılır.",
            bg=THEME["surface"], fg=THEME["muted"], font=(self.font_family, 8),
            justify="left",
        ).pack(anchor="w", padx=20, pady=(8, 0))

        # Alt Butonlar
        btn_frame = tk.Frame(self, bg=THEME["surface"])
        btn_frame.pack(fill="x", side="bottom", padx=20, pady=16)

        if not self.parent.cfg.safe_mode:
            tk.Button(
                btn_frame, text="Tehlikeli bile olsa çalıştır", bg=THEME["amber"], fg="#000",
                relief="flat", font=(self.font_family, 10, "bold"), cursor="hand2",
                command=self._danger_run_anyway,
            ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_frame, text="İptal", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=(self.font_family, 10), cursor="hand2", command=self.destroy,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_frame, text="Kaydet ve Uygula", bg=THEME["cyan"], fg="#051419",
            activebackground=THEME["green"], font=(self.font_family, 10, "bold"),
            relief="flat", cursor="hand2", command=self._save_settings,
        ).pack(side="right")

    def _render_api_keys(self):
        for frame in self.api_key_rows:
            frame.destroy()
        self.api_key_rows.clear()
        self.api_key_vars.clear()
        self.api_key_providers.clear()

        saved = self.parent.cfg.get_api_credentials()
        if not saved:
            fallback = self.parent.cfg.load_api_key()
            if fallback:
                saved = [{"provider": "gemini", "key": fallback}]
        if not saved:
            saved = [{"provider": "gemini", "key": ""}]

        for idx, cred in enumerate(saved):
            prov = cred.get("provider") or "gemini"
            self._add_api_key_row("google" if prov == "gemini" else "groq", initial_key=cred.get("key") or "")
            if idx == 0 and self.api_key_vars:
                self.key_var = self.api_key_vars[0]
                self.key_entry = self._entry_for_row(self.api_key_rows[0])

    def _entry_for_row(self, row: tk.Frame) -> Optional[tk.Entry]:
        for child in row.winfo_children():
            if isinstance(child, tk.Entry):
                return child
        return None

    def _add_api_key_row(self, provider: str = "google", initial_key: str = ""):
        prov_slug = "groq" if provider.lower() == "groq" else "gemini"
        var = tk.StringVar(value=initial_key)
        self.api_key_vars.append(var)
        self.api_key_providers.append(prov_slug)

        row = tk.Frame(self.keys_container, bg=THEME["surface"])
        row.pack(fill="x", pady=4)

        tk.Label(
            row, text=("Google" if prov_slug == "gemini" else "Groq"),
            bg=THEME["surface"], fg=THEME["cyan"], font=(self.font_family, 8, "bold"),
            width=8, anchor="w",
        ).pack(side="left", padx=(0, 8))

        entry = tk.Entry(
            row, textvariable=var, show="" if self.show_var.get() else "*", bg=THEME["bg"], fg=THEME["text"],
            insertbackground=THEME["cyan"], relief="flat", highlightthickness=1,
            highlightbackground=THEME["border"], highlightcolor=THEME["cyan"],
            font=(self.font_family, 10),
        )
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.api_key_rows.append(row)
        if self.key_entry is None:
            self.key_var = var
            self.key_entry = entry

        tk.Button(
            row, text="−", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", width=3, cursor="hand2", command=lambda current=row: self._remove_api_key_row(current),
        ).pack(side="right", padx=(6, 0))

    def _remove_api_key_row(self, row):
        if row in self.api_key_rows:
            idx = self.api_key_rows.index(row)
            row.destroy()
            self.api_key_rows.pop(idx)
            if idx < len(self.api_key_vars):
                self.api_key_vars.pop(idx)
            if idx < len(self.api_key_providers):
                self.api_key_providers.pop(idx)
            if self.key_entry is not None and self.key_entry in row.winfo_children():
                self.key_entry = None
                self.key_var = tk.StringVar(value="")
                if self.api_key_vars:
                    self.key_var = self.api_key_vars[0]
                    self.key_entry = self._find_entry_for_var(self.key_var)

    def _find_entry_for_var(self, value_var):
        for row, key_var in zip(self.api_key_rows, self.api_key_vars):
            if key_var is value_var:
                return row.winfo_children()[0]
        return None

    def _toggle_show(self):
        show = self.show_var.get()
        for row in self.api_key_rows:
            entry = self._entry_for_row(row)
            if entry is not None:
                entry.configure(show="" if show else "*")

    def _select_os_preset(self, preset: str):
        self.os_preset_var.set(preset)
        for key, btn in self.os_buttons.items():
            if key == preset:
                btn.configure(bg=THEME["cyan"], fg="#051419")
            else:
                btn.configure(bg=THEME["surface_light"], fg=THEME["text"])

    def _set_auto_model(self):
        self.model_var.set("auto")

    def _test_connection(self):
        key = self.key_var.get().strip() if self.key_var else ""
        model = self.model_var.get().strip() or core.DEFAULT_MODEL
        if not key:
            key = self.parent.cfg.load_api_key(provider=model)

        if not key:
            provider_hint = "Gemini/Groq" if model == "auto" else model
            self.test_status_lbl.configure(
                text=f"API anahtarı bulunamadı. {provider_hint} için env/ayarları kontrol edin.",
                fg=THEME["amber"],
            )
            return

        self.test_status_lbl.configure(text="Test ediliyor...", fg=THEME["cyan"])
        self.test_btn.configure(state="disabled")

        def worker():
            ok, msg = test_api_connection(key, model, timeout=30)

            def update_ui():
                self.test_btn.configure(state="normal")
                if ok:
                    self.test_status_lbl.configure(text="✓ Bağlantı başarılı!", fg=THEME["green"])
                else:
                    short_err = msg if len(msg) < 45 else msg[:45] + "..."
                    self.test_status_lbl.configure(text=f"✗ {short_err}", fg=THEME["red"])

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _danger_run_anyway(self):
        if self.parent.cfg.safe_mode:
            messagebox.showwarning("TALK", "Güvenli mod açık: onay atlama devre dışı.")
            return
        if getattr(self.parent, "active_spec", None):
            self.destroy()
            self.parent._run_without_prompt()
            return

        self.parent.append_terminal("⚠ Tehlikeli bile olsa çalıştır modu açık. Güvenlik duvarı kapatıldı.\n", "warn")
        self.destroy()

    def _save_settings(self):
        credentials = []
        for var, prov in zip(self.api_key_vars, self.api_key_providers):
            key = var.get().strip()
            if key:
                credentials.append({"provider": prov, "key": key})
                env_name = "GEMINI_API_KEY" if prov == "gemini" else "GROQ_API_KEY"
                os.environ[env_name] = key
        model = self.model_var.get().strip() or core.DEFAULT_MODEL
        try:
            timeout_val = int(self.timeout_var.get().strip())
        except ValueError:
            timeout_val = 60

        selected_preset = self.os_preset_var.get() or "linux"
        custom_os = (self.custom_os_var.get() or "").strip()

        self.parent.cfg.model = model
        self.parent.cfg.set("exec_timeout", timeout_val)
        allow_high_risk = bool(self.safe_mode_var.get())
        self.parent.cfg.set("allow_high_risk_commands", allow_high_risk)
        self.parent.cfg.set("safe_mode", not allow_high_risk)
        self.parent.cfg.set("os_preset", selected_preset)
        self.parent.cfg.set("os_custom", custom_os)
        self.parent.cfg.set_api_credentials(credentials)
        self.parent.cfg.save()
        os_label = self.parent.cfg.apply_os_context()
        os.environ["TALK_OS_LABEL"] = os_label

        # Aktif iş akışını da aynı ayarlara yeniden bağla; böylece GUI/devre içi
        # önbelleklenmiş API bilgisi yerine doğrudan yeni config kullanılır.
        self.parent.pipeline = TalkPipeline(self.parent.cfg)
        self.parent.update_status_bar()
        self.parent.append_terminal(
            f"✓ Yapılandırma güncellendi (Model: {model}, Anahtar: {len(credentials)}, Güvenli mod: {self.parent.cfg.safe_mode})\n\n",
            "ok",
        )
        self.destroy()


# -----------------------------------------------------------------------------
# Ana Masaüstü Arayüzü (TalkApp)
# -----------------------------------------------------------------------------
class TalkApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("talk — Yapay Zeka Destekli Akıllı Terminal")
        self.geometry("980x680")
        self.minsize(760, 520)
        self.configure(bg=THEME["bg"])
        self.app_icon = apply_app_icon(self)

        self.cfg = load_config()
        self.cfg.apply_os_context()
        self.pipeline = TalkPipeline(self.cfg)
        self.history_mgr = self.pipeline.history
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.active_spec: Optional[CommandSpec] = None
        self.running_proc_killable = False

        self.font_family = pick_best_font(self)
        self.font_main = (self.font_family, 11)
        self.font_bold = (self.font_family, 11, "bold")
        self.font_sm = (self.font_family, 9)

        # Geçmiş dizini & gezinti
        self.input_history: List[str] = [e.prompt for e in self.history_mgr.get_recent(50)]
        self.hist_idx: Optional[int] = None
        self.hist_draft = ""

        self._build_layout()
        self.after(100, self._poll_queue)
        self.after(300, self._initial_greeting)

    def _build_layout(self):
        # 1. Üst Başlık Çubuğu
        header = tk.Frame(self, bg=THEME["surface"], height=42)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = tk.Frame(header, bg=THEME["surface"])
        title_box.pack(side="left", padx=14)

        tk.Label(title_box, text="●", bg=THEME["surface"], fg=THEME["cyan"], font=(self.font_family, 10)).pack(side="left")
        tk.Label(title_box, text=" talk", bg=THEME["surface"], fg=THEME["text"], font=(self.font_family, 12, "bold")).pack(side="left")
        tk.Label(title_box, text=f" v{core.__version__}", bg=THEME["surface"], fg=THEME["muted"], font=self.font_sm).pack(side="left")

        # Durum Göstergeleri (Sağ)
        right_actions = tk.Frame(header, bg=THEME["surface"])
        right_actions.pack(side="right", padx=14)

        self.key_status_badge = tk.Label(
            right_actions, text="API", bg=THEME["surface_light"], fg=THEME["muted"],
            font=self.font_sm, padx=8, pady=2,
        )
        self.key_status_badge.pack(side="left", padx=4)

        self.model_badge = tk.Label(
            right_actions, text=self.cfg.model, bg=THEME["surface_light"], fg=THEME["blue"],
            font=self.font_sm, padx=8, pady=2,
        )
        self.model_badge.pack(side="left", padx=4)

        self.btn_history = tk.Button(
            right_actions, text="🕒 Geçmiş", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=self.font_sm, cursor="hand2", padx=6, pady=1,
            command=self.toggle_history_panel,
        )
        self.btn_history.pack(side="left", padx=4)

        btn_settings = tk.Button(
            right_actions, text="⚙ Ayarlar", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=self.font_sm, cursor="hand2", padx=6, pady=1,
            command=self.open_settings,
        )
        btn_settings.pack(side="left", padx=4)

        # 2. Ana Çalışma Alanı
        self.body_paned = tk.PanedWindow(self, orient="horizontal", bg=THEME["border"], bd=0, sashwidth=2)
        self.body_paned.pack(fill="both", expand=True)

        self.main_content = tk.Frame(self.body_paned, bg=THEME["bg"])
        self.body_paned.add(self.main_content, minsize=480, stretch="always")

        term_frame = tk.Frame(self.main_content, bg=THEME["bg"])
        term_frame.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        self.terminal = tk.Text(
            term_frame, wrap="word", bg=THEME["bg"], fg=THEME["text"], relief="flat", bd=0,
            font=self.font_main, insertbackground=THEME["cyan"], selectbackground=THEME["border"],
            selectforeground=THEME["text"], padx=8, pady=8, cursor="xterm", spacing1=2, spacing3=2,
        )
        self.terminal.pack(fill="both", expand=True, side="left")

        sb = tk.Scrollbar(
            term_frame, command=self.terminal.yview, orient="vertical",
            bg=THEME["bg"], troughcolor=THEME["bg"], activebackground=THEME["border"],
            bd=0, highlightthickness=0, width=9,
        )
        self.terminal.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        self.terminal.tag_configure("prompt", foreground=THEME["cyan"], font=self.font_bold)
        self.terminal.tag_configure("cmd", foreground=THEME["purple"], font=self.font_bold)
        self.terminal.tag_configure("stdout", foreground=THEME["text"])
        self.terminal.tag_configure("stderr", foreground=THEME["red"])
        self.terminal.tag_configure("system", foreground=THEME["muted"])
        self.terminal.tag_configure("ok", foreground=THEME["green"], font=self.font_bold)
        self.terminal.tag_configure("warn", foreground=THEME["amber"])
        self.terminal.tag_configure("link", foreground=THEME["blue"], underline=True)
        self.terminal.tag_configure("header", foreground=THEME["blue"], font=self.font_bold)

        self.ctx_menu = tk.Menu(
            self, tearoff=0, bg=THEME["surface"], fg=THEME["text"],
            activebackground=THEME["cyan"], activeforeground="#000",
            relief="flat", font=self.font_sm,
        )
        self.ctx_menu.add_command(label="Kopyala", command=self._copy_selection)
        self.ctx_menu.add_command(label="Tümünü Seç", command=self._select_all)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="Ekranı Temizle", command=self._clear_terminal)
        self.terminal.bind("<Button-3>", self._show_ctx)

        # 3. Güvenlik Kapısı & Komut İnceleme Kartı
        self.gate_frame = tk.Frame(self.main_content, bg=THEME["surface"], highlightthickness=1, highlightbackground=THEME["border"])

        gate_top = tk.Frame(self.gate_frame, bg=THEME["surface"])
        gate_top.pack(fill="x", padx=10, pady=(8, 4))

        self.risk_pill = tk.Label(
            gate_top, text="GÜVENLİ", bg=THEME["green"], fg="#000",
            font=(self.font_family, 9, "bold"), padx=8, pady=2,
        )
        self.risk_pill.pack(side="left")

        self.gate_explanation = tk.Label(
            gate_top, text="", bg=THEME["surface"], fg=THEME["muted"],
            font=self.font_sm, anchor="w",
        )
        self.gate_explanation.pack(side="left", fill="x", expand=True, padx=10)

        cmd_row = tk.Frame(self.gate_frame, bg=THEME["surface"])
        cmd_row.pack(fill="x", padx=10, pady=4)

        tk.Label(cmd_row, text="$", bg=THEME["surface"], fg=THEME["cyan"], font=self.font_bold).pack(side="left", padx=(0, 6))

        self.gate_cmd_var = tk.StringVar()
        self.gate_cmd_entry = tk.Entry(
            cmd_row, textvariable=self.gate_cmd_var, bg=THEME["bg"], fg=THEME["purple"],
            relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["cyan"], font=self.font_bold, insertbackground=THEME["cyan"],
        )
        self.gate_cmd_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.gate_cmd_entry.bind("<Return>", lambda _e: self._approve_gate())
        self.gate_cmd_entry.bind("<KeyRelease>", lambda _e: self._on_gate_cmd_edited())

        self.gate_action_bar = tk.Frame(self.gate_frame, bg=THEME["surface"])
        self.gate_action_bar.pack(fill="x", padx=10, pady=(4, 8))

        self.danger_confirm_var = tk.StringVar()
        self.danger_confirm_entry = tk.Entry(
            self.gate_action_bar, textvariable=self.danger_confirm_var, width=12,
            bg=THEME["bg"], fg=THEME["red"], relief="flat", highlightthickness=1,
            highlightbackground=THEME["red"], highlightcolor=THEME["red"],
            font=self.font_bold,
        )
        self.danger_confirm_entry.bind("<Return>", lambda _e: self._approve_gate())
        self.danger_confirm_lbl = tk.Label(
            self.gate_action_bar, text="Yüksek riskli komutlar için ayarlardan izin verin.",
            bg=THEME["surface"], fg=THEME["red"], font=self.font_sm,
        )

        self.btn_gate_run = tk.Button(
            self.gate_action_bar, text="✅ Onayla ve Çalıştır", bg=THEME["cyan"], fg="#000",
            relief="flat", font=(self.font_family, 9, "bold"), cursor="hand2", padx=10,
            command=self._approve_gate,
        )
        self.btn_gate_run.pack(side="right", padx=(6, 0))

        self.btn_gate_skip = tk.Button(
            self.gate_action_bar, text="⚠ Tehlikeli bile olsa çalıştır", bg=THEME["amber"], fg="#000",
            relief="flat", font=(self.font_family, 9, "bold"), cursor="hand2", padx=10,
            command=self._run_without_prompt,
        )
        self.btn_gate_skip.pack_forget()

        self.btn_gate_copy = tk.Button(
            self.gate_action_bar, text="📋 Kopyala", bg=THEME["surface_light"], fg=THEME["text"],
            relief="flat", font=self.font_sm, cursor="hand2", padx=8,
            command=self._copy_gate_command,
        )
        self.btn_gate_copy.pack(side="right", padx=(6, 0))

        self.btn_gate_cancel = tk.Button(
            self.gate_action_bar, text="İptal (Esc)", bg=THEME["surface_light"], fg=THEME["muted"],
            relief="flat", font=self.font_sm, cursor="hand2", padx=8,
            command=self._cancel_gate,
        )
        self.btn_gate_cancel.pack(side="right")

        # 4. Alt Giriş Çubuğu
        input_bar = tk.Frame(self.main_content, bg=THEME["surface"], height=48)
        input_bar.pack(fill="x", side="bottom", padx=12, pady=(4, 12))

        self.prompt_lbl = tk.Label(
            input_bar, text="❯", bg=THEME["surface"], fg=THEME["cyan"],
            font=(self.font_family, 13, "bold"), padx=10,
        )
        self.prompt_lbl.pack(side="left")

        self.user_entry = tk.Entry(
            input_bar, bg=THEME["surface"], fg=THEME["text"], insertbackground=THEME["cyan"],
            relief="flat", font=self.font_main, selectbackground=THEME["border"],
            selectforeground=THEME["text"],
        )
        self.user_entry.pack(fill="x", expand=True, side="left", ipady=6, padx=(0, 8))
        self.user_entry.bind("<Return>", self._handle_input_submit)
        self.user_entry.bind("<Up>", self._on_hist_up)
        self.user_entry.bind("<Down>", self._on_hist_down)
        self.user_entry.bind("<Escape>", lambda _e: self._cancel_gate())
        self.user_entry.focus_set()

        self.btn_send = tk.Button(
            input_bar, text="Gönder ↵", bg=THEME["cyan"], fg="#051419",
            activebackground=THEME["green"], relief="flat", font=(self.font_family, 9, "bold"),
            cursor="hand2", padx=12, pady=4, command=self._handle_input_submit,
        )
        self.btn_send.pack(side="right", padx=6)

        # 5. Sağ Bölüm: Geçmiş Çekmecesi
        self.history_frame = tk.Frame(self.body_paned, bg=THEME["surface"], width=280)

        hist_header = tk.Frame(self.history_frame, bg=THEME["surface"])
        hist_header.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(
            hist_header, text="Komut Geçmişi", bg=THEME["surface"], fg=THEME["text"],
            font=(self.font_family, 10, "bold"),
        ).pack(side="left")

        tk.Button(
            hist_header, text="✕", bg=THEME["surface"], fg=THEME["muted"], relief="flat",
            cursor="hand2", command=self.toggle_history_panel,
        ).pack(side="right")

        self.hist_search_var = tk.StringVar()
        self.hist_search_var.trace_add("write", lambda *_: self._filter_history_list())
        search_entry = tk.Entry(
            self.history_frame, textvariable=self.hist_search_var, bg=THEME["bg"], fg=THEME["text"],
            relief="flat", highlightthickness=1, highlightbackground=THEME["border"],
            highlightcolor=THEME["cyan"], font=self.font_sm,
        )
        search_entry.pack(fill="x", padx=10, pady=4, ipady=3)

        self.hist_listbox = tk.Listbox(
            self.history_frame, bg=THEME["bg"], fg=THEME["text"], relief="flat", bd=0,
            selectbackground=THEME["surface_light"], selectforeground=THEME["cyan"],
            font=self.font_sm, highlightthickness=0,
        )
        self.hist_listbox.pack(fill="both", expand=True, padx=10, pady=4)
        self.hist_listbox.bind("<Double-Button-1>", self._on_history_item_clicked)

        hist_footer = tk.Frame(self.history_frame, bg=THEME["surface"])
        hist_footer.pack(fill="x", padx=10, pady=6)
        tk.Button(
            hist_footer, text="Geçmişi Temizle", bg=THEME["surface_light"], fg=THEME["muted"],
            font=(self.font_family, 8), relief="flat", cursor="hand2", command=self._clear_all_history,
        ).pack(side="right")

        self.bind_all("<Control-l>", lambda _e: self._clear_terminal())
        self.bind_all("<Control-comma>", lambda _e: self.open_settings())

        self.update_status_bar()

    def allow_gate_bypass(self) -> bool:
        return bool(self.cfg.allow_high_risk_commands)

    def update_status_bar(self):
        key = self.cfg.load_api_key()
        if key:
            self.key_status_badge.configure(text="● API AKTİF", fg=THEME["green"])
        else:
            self.key_status_badge.configure(text="▲ API ANAHTARI EKSİK", fg=THEME["amber"])
        self.model_badge.configure(text=self.cfg.model)

    def _initial_greeting(self):
        self.append_terminal("◆ TALK Terminal Engine Hazır.\n", "header")
        self.append_terminal(
            "Doğal dilde Türkçe komut yazın (örn: 'bellek kullanımını göster', "
            "'en büyük 5 dosyayı bul', 'nginx servisini yeniden başlat')...\n"
            "Kısayollar: [↑/↓]=Geçmiş  [Ctrl+L]=Temizle  [Ctrl+,]=Ayarlar\n",
            "system",
        )
        key = self.cfg.load_api_key()
        if not key:
            self.append_terminal(
                "⚠ API Anahtarı girilmemiş. Sağ üstteki [⚙ Ayarlar] butonundan anahtarınızı kaydedin.\n",
                "warn",
            )
            self.append_terminal(f"→ Ücretsiz API Anahtarı Al: {AI_STUDIO_URL}\n\n", "link")
        else:
            self.append_terminal("✓ API anahtarı algılandı.\n\n", "ok")

    def _verify_startup_api(self):
        key = self.cfg.load_api_key()
        if not key:
            return
        try:
            ok, msg = test_api_connection(key, self.cfg.model, timeout=30)
            if ok:
                self.append_terminal(f"✓ Gemini API bağlantısı doğrulandı.\n\n", "ok")
            else:
                self.append_terminal(f"⚠ API anahtarı bulundu, ancak bağlanamadı: {msg}\n\n", "warn")
        except Exception as exc:
            self.append_terminal(f"⚠ API doğrulama sırasında hata oluştu: {exc}\n\n", "warn")

    def append_terminal(self, text: str, tag: str = "stdout"):
        self.terminal.configure(state="normal")
        self.terminal.insert("end", text, tag)
        lines = int(self.terminal.index("end-1c").split(".")[0])
        if lines > MAX_TERM_LINES:
            self.terminal.delete("1.0", f"{lines - MAX_TERM_LINES}.0")
        self.terminal.see("end")
        self.terminal.configure(state="disabled")

    def _clear_terminal(self):
        self.terminal.configure(state="normal")
        self.terminal.delete("1.0", "end")
        self.terminal.configure(state="disabled")

    def _select_all(self):
        self.terminal.tag_add("sel", "1.0", "end")

    def _copy_selection(self):
        try:
            text = self.terminal.get("sel.first", "sel.last")
            self.clipboard_clear()
            self.clipboard_append(text)
        except tk.TclError:
            pass

    def _show_ctx(self, event):
        try:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.ctx_menu.grab_release()

    def toggle_history_panel(self):
        if self.history_frame in self.body_paned.panes():
            self.body_paned.forget(self.history_frame)
            self.btn_history.configure(bg=THEME["surface_light"])
        else:
            self.body_paned.add(self.history_frame, width=280)
            self.btn_history.configure(bg=THEME["border"])
            self._filter_history_list()

    def _filter_history_list(self):
        q = self.hist_search_var.get().strip().lower()
        self.hist_listbox.delete(0, "end")
        entries = self.history_mgr.get_recent(100)
        entries.reverse()
        self._cached_entries = []
        for e in entries:
            if not q or (q in e.prompt.lower() or q in e.command.lower()):
                self._cached_entries.append(e)
                prefix = "✓ " if e.returncode == 0 else ("✗ " if e.returncode is not None else "· ")
                self.hist_listbox.insert("end", f"{prefix}{e.prompt}")

    def _on_history_item_clicked(self, _event):
        sel = self.hist_listbox.curselection()
        if sel and hasattr(self, "_cached_entries"):
            entry = self._cached_entries[sel[0]]
            self.user_entry.delete(0, "end")
            self.user_entry.insert(0, entry.prompt)
            self.user_entry.focus_set()

    def _clear_all_history(self):
        if messagebox.askyesno("TALK", "Tüm geçmiş silinsin mi?"):
            self.history_mgr.clear()
            self._filter_history_list()

    def _on_hist_up(self, _event):
        if not self.input_history:
            return "break"
        if self.hist_idx is None:
            self.hist_draft = self.user_entry.get()
            self.hist_idx = len(self.input_history) - 1
        elif self.hist_idx > 0:
            self.hist_idx -= 1
        self.user_entry.delete(0, "end")
        self.user_entry.insert(0, self.input_history[self.hist_idx])
        return "break"

    def _on_hist_down(self, _event):
        if self.hist_idx is None:
            return "break"
        if self.hist_idx < len(self.input_history) - 1:
            self.hist_idx += 1
            item = self.input_history[self.hist_idx]
        else:
            self.hist_idx = None
            item = self.hist_draft
        self.user_entry.delete(0, "end")
        self.user_entry.insert(0, item)
        return "break"

    def _handle_input_submit(self, _event=None):
        if self.busy:
            return

        text = self.user_entry.get().strip()
        if not text:
            return

        self.user_entry.delete(0, "end")
        self.input_history.append(text)
        self.hist_idx = None
        self.hist_draft = ""

        api_key = self.cfg.load_api_key(provider=self.cfg.model)
        if not api_key:
            self.append_terminal(f"❯ {text}\n", "prompt")
            self.append_terminal("[Hata] API Anahtarı tanımlı değil! Üstteki '⚙ Ayarlar' butonu ile girin.\n\n", "stderr")
            self.open_settings()
            return

        self.append_terminal(f"❯ {text}\n", "prompt")
        self.append_terminal(f"✦ Komut üretiliyor ({self.cfg.model})...\n", "system")
        self.busy = True
        self.prompt_lbl.configure(fg=THEME["amber"])

        def worker():
            try:
                spec = self.pipeline.generate(text)
                self.q.put(("command_generated", spec))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_security_gate(self, spec: CommandSpec):
        self.active_spec = spec
        self.gate_cmd_var.set(spec.command)
        self.gate_explanation.configure(text=spec.explanation or "Açıklama yok")

        report = analyze_command(spec.command)
        self._update_gate_risk_ui(report)

        self.gate_frame.pack(fill="x", padx=12, pady=6, after=self.terminal.master)
        self.gate_cmd_entry.focus_set()

    def _update_gate_risk_ui(self, report: core.RiskReport):
        level = report.level
        if level == RiskLevel.CRITICAL:
            self.risk_pill.configure(text="✖ KRİTİK RİSK", bg=THEME["red"], fg="#fff")
        elif level == RiskLevel.DANGEROUS:
            self.risk_pill.configure(text="⚠ YÜKSEK RİSK", bg=THEME["danger_bg"], fg=THEME["danger_fg"])
        elif level == RiskLevel.CAUTION:
            self.risk_pill.configure(text="⚠ DİKKAT", bg=THEME["amber"], fg="#000")
        else:
            self.risk_pill.configure(text="✓ GÜVENLİ", bg=THEME["green"], fg="#000")

        if report.level == RiskLevel.CRITICAL:
            self.danger_confirm_var.set("")
            self.danger_confirm_lbl.configure(
                text="Kritik risk — bu komut engellendi. Düzenleyin veya iptal edin.",
            )
            self.danger_confirm_lbl.pack(side="left", padx=(0, 8))
            self.danger_confirm_entry.pack_forget()
            self.btn_gate_run.configure(text="Engellendi", state="disabled")
            self.btn_gate_skip.pack_forget()
        elif report.is_dangerous:
            self.danger_confirm_var.set("")
            if self.allow_gate_bypass():
                self.danger_confirm_lbl.configure(
                    text="Yüksek riskli komutlar için izin açık; çalıştırılabilir.",
                )
                self.danger_confirm_lbl.pack(side="left", padx=(0, 8))
                self.danger_confirm_entry.pack_forget()
                self.btn_gate_run.configure(text="▶ Çalıştır", state="normal")
                self.btn_gate_skip.configure(text="⚠ Riskli çalıştır")
                self.btn_gate_skip.pack(side="right", padx=(6, 0))
            else:
                self.danger_confirm_lbl.configure(
                    text="Yüksek riskli komutlar için Ayarlar > 'Yüksek riskli komutların çalışmasına izin ver' seçeneğini açın.",
                )
                self.danger_confirm_lbl.pack(side="left", padx=(0, 8))
                self.danger_confirm_entry.pack_forget()
                self.btn_gate_run.configure(text="Engellendi", state="disabled")
                self.btn_gate_skip.pack_forget()
        else:
            self.danger_confirm_entry.pack_forget()
            self.danger_confirm_lbl.pack_forget()
            self.btn_gate_run.configure(text="▶ Çalıştır", state="normal")
            self.btn_gate_skip.pack_forget()

    def _on_gate_cmd_edited(self):
        cmd = self.gate_cmd_var.get().strip()
        report = analyze_command(cmd)
        self._update_gate_risk_ui(report)
        if report.level != RiskLevel.CRITICAL:
            self.btn_gate_run.configure(state="normal")

    def _copy_gate_command(self):
        cmd = self.gate_cmd_var.get().strip()
        self.clipboard_clear()
        self.clipboard_append(cmd)
        self.btn_gate_copy.configure(text="✓ Kopyalandı!")
        self.after(1500, lambda: self.btn_gate_copy.configure(text="📋 Kopyala"))

    def _cancel_gate(self):
        if self.gate_frame.winfo_ismapped():
            self.gate_frame.pack_forget()
            self.active_spec = None
            self.append_terminal("İptal edildi. Komut çalıştırılmadı.\n\n", "system")
            self.user_entry.focus_set()

    def _approve_gate(self):
        cmd = self.gate_cmd_var.get().strip()
        if not cmd:
            return

        gate = evaluate_gate(cmd, allow_bypass=self.allow_gate_bypass(), block_critical=True)
        if not gate.allowed:
            messagebox.showwarning("TALK — Güvenlik", gate.message)
            return

        self._run_gate_command(cmd)

    def _run_without_prompt(self):
        cmd = self.gate_cmd_var.get().strip()
        if not cmd:
            return
        gate = evaluate_gate(
            cmd,
            bypass_confirmation=True,
            allow_bypass=self.allow_gate_bypass(),
            block_critical=True,
        )
        if not gate.allowed:
            messagebox.showwarning("TALK — Güvenlik", gate.message)
            return
        self.append_terminal("⚠ Tehlikeli komut doğrudan çalıştırma onayı verildi.\n", "warn")
        self._run_gate_command(cmd, skip_prompt=True)

    def _run_gate_command(self, cmd: str, skip_prompt: bool = False):
        spec = self.active_spec
        self.gate_frame.pack_forget()
        self.active_spec = None

        if skip_prompt:
            self.append_terminal("⚡ Kullanıcı doğrulama atlandı; komut doğrudan çalıştırılıyor...\n", "warn")

        self._execute_command_live(cmd, spec.prompt if spec else "", spec.explanation if spec else "")

    def _execute_command_live(self, command: str, prompt: str, explanation: str):
        self.busy = True
        self.prompt_lbl.configure(fg=THEME["amber"])
        self.append_terminal(f"$ {command}\n", "cmd")
        def worker():
            try:
                def on_chunk(stream: str, text: str) -> None:
                    tag = "warn" if stream == "system" else stream
                    self.q.put(("stream_chunk", (text, tag)))

                result = self.pipeline.execute(command, on_chunk=on_chunk)
                self.q.put(
                    (
                        "exec_finished",
                        (
                            command,
                            prompt,
                            explanation,
                            result.returncode,
                            result.duration_sec,
                            result.timed_out,
                        ),
                    )
                )
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                msg_type, payload = self.q.get_nowait()
                if msg_type == "command_generated":
                    spec: CommandSpec = payload
                    self.busy = False
                    self.prompt_lbl.configure(fg=THEME["cyan"])

                    if spec.unsupported:
                        self.append_terminal("⚠ Bu istek bir kabuk komutuna dönüştürülemedi.\n", "warn")
                        if spec.explanation:
                            self.append_terminal(f"↳ {spec.explanation}\n\n", "system")
                        continue

                    self.append_terminal("Önerilen Komut: ", "system")
                    self.append_terminal(f"{spec.command}\n", "cmd")
                    if spec.explanation:
                        self.append_terminal(f"↳ {spec.explanation}\n", "system")

                    report = analyze_command(spec.command)
                    for issue in report.issues:
                        self.append_terminal(f"  ! {issue.title}: {issue.description}\n", "warn")

                    self._show_security_gate(spec)

                elif msg_type == "stream_chunk":
                    text, tag = payload
                    self.append_terminal(text, tag)

                elif msg_type == "exec_finished":
                    command, prompt, exp, returncode, duration, timed_out = payload
                    self.busy = False
                    self.prompt_lbl.configure(fg=THEME["cyan"])

                    dur_str = f"{duration:.2f}s"
                    if timed_out:
                        self.append_terminal(f"✗ Komut zaman aşımına uğradı ({self.cfg.exec_timeout} sn)!\n\n", "stderr")
                    elif returncode == 0:
                        self.append_terminal(f"✓ Başarılı [Çıkış Kodu 0] ({dur_str})\n\n", "ok")
                    else:
                        hint = EXIT_HINTS.get(returncode, "")
                        hint_str = f" — {hint}" if hint else ""
                        self.append_terminal(f"✗ Hata: [Çıkış Kodu {returncode}]{hint_str} ({dur_str})\n\n", "stderr")

                    self.pipeline.record_run(
                        prompt or command,
                        command,
                        exp,
                        ExecResult("", "", returncode, round(duration, 3), timed_out, False),
                    )
                    self._filter_history_list()

                elif msg_type == "error":
                    self.busy = False
                    self.prompt_lbl.configure(fg=THEME["cyan"])
                    self.append_terminal(f"[Hata] {payload}\n\n", "stderr")

        except queue.Empty:
            pass

        self.after(60, self._poll_queue)

    def open_settings(self):
        for w in self.winfo_children():
            if isinstance(w, SettingsModal) and w.winfo_exists():
                w.lift()
                w.focus_force()
                return
        SettingsModal(self)


def main():
    app = TalkApp()
    app.mainloop()


if __name__ == "__main__":
    main()