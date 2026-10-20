"""Interface do Javis — visual em vidro, sobre um fundo aurora.

O fundo e os painéis são renderizados em Python (ver javis/glass.py) e
mostrados num Canvas. Os widgets verdadeiros (Text, Treeview, Entry) ficam
por cima, com fundo transparente para que o vidro apareça atrás deles.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import glass, llm
from .config import (
    APP_NAME,
    APP_VERSION,
    BACKUP_DIR,
    DATA_DIR,
    FALLBACK_MODEL,
    LOG_FILE,
    MAX_IMPORT_BYTES,
    MODEL,
    OLLAMA_TAGS_URL,
    OLLAMA_URL,
    PLAN_FILE,
    PRIORITIES,
    QUICK_MODEL,
    STATE_FILE,
    STATUSES,
    DATE_HINT,
)
from .storage import (
    add_history,
    atomic_write,
    backup_plan,
    br_date,
    br_datetime,
    find_by_id,
    load_state,
    migrate_state,
    next_id,
    now_iso,
    parse_date,
    read_text_safe,
    rotate_state_backup,
    save_state,
    stamp,
)
from .theme import (DEFAULT_THEME, THEMES, darken, get_theme, glass_surface, glass_well, hexc, is_light,
                    lighten, mix)

log = logging.getLogger("javis")

NAV_ITEMS = [
    ("capture", "Início e análise"),
    ("records", "Registros"),
    ("actions", "Ações e resultados"),
    ("decisions", "Decisões"),
    ("plan", "Plano"),
    ("history", "Histórico"),
]

SIDEBAR_W = 236


class JavisApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state, load_notice = load_state()
        rotate_state_backup()
        self.theme_name = self.state.get("tema") if self.state.get("tema") in THEMES else DEFAULT_THEME
        self.theme = get_theme(self.theme_name)
        self.colors = self.theme
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)

        # IA e análise
        self.analysis_result = ""
        self.plan_proposal = ""
        self.busy = False
        self.ollama_ready = False
        self.warming_model = False
        self.preload_in_progress = False
        self.preloaded_quick_model: str | None = None
        self.active_model = MODEL
        self.quick_model = MODEL
        self.current_model = MODEL
        self.detected_quick_model: str | None = None
        self.available_models: list[str] = []
        self.auto_queue: list[tuple[str, str]] = []
        self.current_note_id: str | None = None
        self.current_relation_id: str | None = None
        self.analysis_started = 0.0
        self.analysis_timer_id = None
        self.streaming_started = False
        self.job_id = 0
        self.cancel_event = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.recheck_id = None

        # Interface
        self.texts: list[tk.Text] = []
        self.combos: list[ttk.Combobox] = []
        self.popup_menus: list[tk.Menu] = []
        self.trees: dict[str, ttk.Treeview] = {}
        self.tree_cols: dict[str, list[str]] = {}
        self.tree_titles: dict[str, dict[str, str]] = {}
        self.sort_state: dict[str, tuple[str | None, bool]] = {}
        self.shortcuts: list[tuple[str, object]] = []
        self.pages: dict[str, ttk.Frame] = {}
        self.nav: dict[str, tk.Canvas] = {}
        self.nav_labels: dict[str, tk.Label] = {}
        self.current_page = "capture"
        self.ai_status = ("Verificando IA local…", "muted")
        self._debounce_ids: dict[str, str] = {}
        self.status_kind = "info"
        self._glass_panels: list[dict] = []
        self._backdrop_photo: tk.PhotoImage | None = None
        self._scene_key = None      # evita redesenhar a mesma cena
        self._colors_key = None     # evita reaplicar as mesmas cores
        self._laid_size = None      # último tamanho de janela posicionado
        self._layout_pending = False
        self._hover_anim: dict[str, float] = {}
        self._toast_id = None
        self._pulse_id = None
        self._pulse_phase = 0.0

        root.title(APP_NAME)
        self._init_window()
        self._init_fonts()
        self.style = ttk.Style(root)
        self._glass_palette()
        self.auto_var = tk.BooleanVar(value=bool(self.state.get("auto_analysis_enabled", True)))
        self._setup_shortcuts()
        self._build_menu()
        self._build()
        # O primeiro _layout define a geometria; sem ele o vidro cai no
        # fallback de cor (a janela ainda não tem tamanho neste ponto).
        self.root.update_idletasks()
        self._layout()
        self.apply_theme()
        self.refresh_all()
        self.show_page("capture")

        draft = self.state.get("rascunho", "")
        if draft:
            self.input_box.insert("1.0", draft)
            self.set_status("Rascunho anterior restaurado na caixa de texto.", "info")
        if self.state.get("ai_consent_local") and self.auto_var.get():
            self.auto_queue = [
                (note.get("id"), note.get("texto", ""))
                for note in reversed(self.state["notas"])
                if note.get("analise_automatica_pendente") and note.get("id")
            ]
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._on_tk_error
        root.after(40, self._poll_events)
        root.after(400, self.check_ollama)
        root.after(30000, self._autosave_draft)
        root.after(120, self._start_pulse)
        if load_notice:
            root.after(300, lambda: messagebox.showwarning(APP_NAME, load_notice))

    # ----- janela, fontes, tema ------------------------------------------------

    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def _init_window(self) -> None:
        root = self.root
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        try:
            w, h = (int(v) for v in str(self.state.get("janela", "1240x820")).split("x"))
        except ValueError:
            w, h = 1240, 820
        w, h = min(max(w, 940), sw), min(max(h, 640), sh - 60)
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.minsize(940, 640)
        root.configure(bg=hexc(self.theme["bg"]))

    def _init_fonts(self) -> None:
        families = set(tkfont.families(self.root))
        self.family = "Segoe UI" if "Segoe UI" in families else tkfont.nametofont("TkDefaultFont").actual("family")
        self.mono = "Consolas" if "Consolas" in families else tkfont.nametofont("TkFixedFont").actual("family")
        try:
            size = int(self.state.get("fonte", 10))
        except (TypeError, ValueError):
            size = 10
        self.base_size = min(max(size, 8), 18)
        mk = lambda **kw: tkfont.Font(root=self.root, family=kw.pop("family", self.family), **kw)
        self.f_base = mk(size=self.base_size)
        self.f_bold = mk(size=self.base_size, weight="bold")
        self.f_input = mk(size=self.base_size + 1)
        self.f_h = mk(size=self.base_size + 2, weight="bold")
        self.f_title = mk(size=self.base_size + 8, weight="bold")
        self.f_small = mk(size=max(self.base_size - 1, 7))
        self.f_mono = mk(family=self.mono, size=self.base_size)

    def set_font_size(self, size: int) -> None:
        size = min(max(size, 8), 18)
        if size == self.base_size:
            return
        self.base_size = size
        for font, delta in ((self.f_base, 0), (self.f_bold, 0), (self.f_input, 1),
                            (self.f_h, 2), (self.f_title, 8), (self.f_mono, 0)):
            font.configure(size=size + delta)
        self.f_small.configure(size=max(size - 1, 7))
        self.state["fonte"] = size
        save_state(self.state)
        self.apply_theme()

    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self.theme_name = name
        self.theme = get_theme(name)
        self.colors = self.theme
        self.state["tema"] = name
        save_state(self.state)
        self.apply_theme()
        self.set_status(f"Tema {self.theme['label']} aplicado.", "ok")

    def toggle_theme(self) -> None:
        order = list(THEMES.keys())
        index = order.index(self.theme_name) if self.theme_name in order else 0
        self.set_theme(order[(index + 1) % len(order)])

    def apply_theme(self) -> None:
        t, s, px = self.theme, self.style, self.px
        dark = self.theme_name != "aurora-clara"
        s.theme_use("clam")
        self.root.configure(bg=hexc(t["bg"]))
        s.configure(".", background=hexc(t["bg"]), foreground=hexc(t["text"]), font=self.f_base,
                    bordercolor=hexc(t["surface"]), lightcolor=hexc(t["bg"]), darkcolor=hexc(t["bg"]),
                    troughcolor=hexc(t["bg"]), focuscolor=hexc(t["accent"]), insertcolor=hexc(t["text"]))
        s.configure("TFrame", background=hexc(t["bg"]))
        s.configure("TLabel", background=hexc(t["bg"]), foreground=hexc(t["text"]))
        s.configure("Title.TLabel", font=self.f_title, foreground=hexc(t["text"]))
        s.configure("H.TLabel", font=self.f_h)
        s.configure("Bold.TLabel", font=self.f_bold)
        s.configure("Sub.TLabel", foreground=hexc(t["muted"]))
        s.configure("Banner.TFrame", background=hexc(darken(t["surface"], 0.15)))
        s.configure("Banner.TLabel", background=hexc(darken(t["surface"], 0.15)), foreground=hexc(t["text"]))
        s.configure("Status.TFrame", background=hexc(darken(t["surface"], 0.35)))
        s.configure("Status.TLabel", background=hexc(darken(t["surface"], 0.35)), foreground=hexc(t["muted"]),
                    font=self.f_small, padding=(px(14), px(6)))
        # Botões
        s.configure("TButton", background=hexc(t["surface"]), foreground=hexc(t["text"]),
                    bordercolor=hexc(t["surface"]), lightcolor=hexc(t["surface"]), darkcolor=hexc(t["surface"]),
                    padding=(px(12), px(6)), anchor="center", relief="flat")
        s.map("TButton", background=[("disabled", hexc(darken(t["surface"], 0.2))),
                                     ("pressed", hexc(lighten(t["surface"], 0.14))),
                                     ("active", hexc(lighten(t["surface"], 0.08)))],
              foreground=[("disabled", hexc(t["muted"]))])
        s.configure("Action.TButton", background=hexc(t["accent"]), foreground=hexc(t["accent_fg"]),
                    bordercolor=hexc(t["accent"]), lightcolor=hexc(t["accent"]), darkcolor=hexc(t["accent"]),
                    font=self.f_bold, padding=(px(14), px(8)))
        s.map("Action.TButton", background=[("disabled", hexc(darken(t["accent"], 0.45))),
                                           ("pressed", hexc(darken(t["accent"], 0.18))),
                                           ("active", hexc(lighten(t["accent"], 0.10)))],
              foreground=[("disabled", hexc(t["muted"]))])
        s.configure("Ghost.TButton", background=hexc(t["surface"]), foreground=hexc(t["muted"]),
                    bordercolor=hexc(t["surface"]), lightcolor=hexc(t["surface"]), darkcolor=hexc(t["surface"]),
                    font=self.f_base, padding=(px(10), px(5)))
        s.map("Ghost.TButton", background=[("pressed", hexc(darken(t["surface"], 0.2))),
                                           ("active", hexc(lighten(t["surface"], 0.10)))],
              foreground=[("active", hexc(t["text"]))])
        s.configure("TMenubutton", background=hexc(t["surface"]), foreground=hexc(t["text"]),
                    bordercolor=hexc(t["surface"]), arrowcolor=hexc(t["text"]), padding=(px(12), px(6)))
        s.map("TMenubutton", background=[("active", hexc(lighten(t["surface"], 0.12)))])
        # Campos
        s.configure("TEntry", fieldbackground=hexc(darken(t["surface"], 0.3)), foreground=hexc(t["text"]),
                    bordercolor=hexc(darken(t["surface"], 0.3)), lightcolor=hexc(darken(t["surface"], 0.3)),
                    darkcolor=hexc(darken(t["surface"], 0.3)), insertcolor=hexc(t["text"]), padding=px(5))
        s.configure("TCombobox", fieldbackground=hexc(darken(t["surface"], 0.3)), background=hexc(t["surface"]),
                    foreground=hexc(t["text"]), arrowcolor=hexc(t["text"]),
                    bordercolor=hexc(darken(t["surface"], 0.3)), padding=px(4))
        s.map("TCombobox", fieldbackground=[("readonly", hexc(darken(t["surface"], 0.3))),
                                           ("disabled", hexc(t["bg"]))],
              foreground=[("readonly", hexc(t["text"])), ("disabled", hexc(t["muted"]))])
        s.configure("TCheckbutton", background=hexc(t["bg"]), foreground=hexc(t["text"]),
                    indicatorbackground=hexc(t["surface"]), indicatorforeground=hexc(t["text"]),
                    upperbordercolor=hexc(t["surface"]), lowerbordercolor=hexc(t["surface"]))
        s.map("TCheckbutton", background=[("active", hexc(t["bg"]))],
              indicatorbackground=[("selected", hexc(t["accent"])), ("!selected", hexc(t["surface"]))],
              indicatorforeground=[("selected", hexc(t["accent_fg"]))])
        s.configure("TScrollbar", background=hexc(t["surface"]), troughcolor=hexc(t["bg"]),
                    bordercolor=hexc(t["bg"]), arrowcolor=hexc(t["muted"]),
                    lightcolor=hexc(t["surface"]), darkcolor=hexc(t["surface"]), gripcount=0)
        s.map("TScrollbar", background=[("active", hexc(lighten(t["surface"], 0.18)))])
        s.configure("TPanedwindow", background=hexc(t["bg"]))
        # Tabelas
        s.configure("Treeview", background=hexc(darken(t["surface"], 0.25)), fieldbackground=hexc(darken(t["surface"], 0.25)),
                    foreground=hexc(t["text"]), bordercolor=hexc(t["surface"]), lightcolor=hexc(t["surface"]),
                    darkcolor=hexc(t["surface"]), borderwidth=1, font=self.f_base,
                    rowheight=self.f_base.metrics("linespace") + px(10))
        s.map("Treeview", background=[("selected", hexc(t["accent"]))], foreground=[("selected", hexc(t["accent_fg"]))])
        s.configure("Treeview.Heading", background=hexc(darken(t["surface"], 0.45)), foreground=hexc(t["muted"]),
                    font=self.f_bold, relief="flat", padding=(px(8), px(6)))
        s.map("Treeview.Heading", background=[("active", hexc(lighten(t["surface"], 0.12)))])
        self.root.option_add("*TCombobox*Listbox.font", self.f_base)
        # Widgets tk "puros"
        self.texts = [w for w in self.texts if w.winfo_exists()]
        for widget in self.texts:
            self._style_text(widget)
        self.combos = [c for c in self.combos if c.winfo_exists()]
        for combo in self.combos:
            self.style_combo(combo, register=False)
        for tree in self.trees.values():
            tree.tag_configure("odd", background=hexc(darken(t["surface"], 0.12)))
            tree.tag_configure("atrasada", foreground=hexc(t["danger"]))
            tree.tag_configure("inativa", foreground=hexc(t["muted"]))
            tree.tag_configure("andamento", foreground=hexc(t["accent"]))
        for menu in self.popup_menus:
            menu.configure(background=hexc(t["surface"]), foreground=hexc(t["text"]),
                           activebackground=hexc(t["accent"]), activeforeground=hexc(t["accent_fg"]), borderwidth=0)
        if hasattr(self, "analysis_box"):
            self._style_analysis_tags()
        if hasattr(self, "ai_label"):
            self.set_ai_status(*self.ai_status)
            self.set_status(self.status.cget("text"), self.status_kind)
        # theme_use/style.configure acima redefiniram os estilos: reaplica o vidro.
        self._colors_key = None
        self._layout()

    def _style_text(self, widget: tk.Text) -> None:
        t = self.theme
        widget.configure(background=hexc(darken(t["surface"], 0.35)), foreground=hexc(t["text"]),
                         insertbackground=hexc(t["text"]), selectbackground=hexc(t["accent"]),
                         selectforeground=hexc(t["accent_fg"]), inactiveselectbackground=hexc(t["accent"]),
                         highlightbackground=hexc(darken(t["surface"], 0.45)), highlightcolor=hexc(t["accent"]))

    def _hoverable(self, widget, on_enter, on_leave) -> None:
        """Liga o realce de hover num widget ttk ou tk."""
        try:
            widget.bind("<Enter>", lambda _e: on_enter())
            widget.bind("<Leave>", lambda _e: on_leave())
        except tk.TclError:
            pass

    def make_button(self, parent, text: str, command, style: str = "Ghost.TButton", accent: bool = False,
                    state: str = "normal"):
        """Botão com realce suave ao passar o mouse."""
        button = ttk.Button(parent, text=text, style=style, command=command, state=state)
        cursor = "hand2"

        def on_enter() -> None:
            try:
                if "disabled" not in button.state():
                    button.configure(cursor=cursor)
                    button.state(["active"])
            except tk.TclError:
                pass

        def on_leave() -> None:
            try:
                button.state(["!active"])
            except tk.TclError:
                pass

        self._hoverable(button, on_enter, on_leave)
        return button

    def toast(self, message: str, kind: str = "ok") -> None:
        """Notificação flutuante no canto inferior direito."""
        t = self.theme
        color = {"ok": hexc(t["ok"]), "warn": hexc(t["warn"]), "err": hexc(t["danger"])}.get(kind, hexc(t["accent"]))
        if getattr(self, "_toast", None) is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        frame = tk.Frame(self.root, bg=color, bd=0, highlightthickness=0)
        label = tk.Label(frame, text=message, bg=color, fg="#0b1020" if kind != "err" else "#ffffff",
                         font=self.f_bold, padx=14, pady=8, justify="left")
        label.pack()
        self._toast = frame
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        frame.place(relx=0.985, rely=0.94, anchor="se")
        # Some sozinho depois de alguns segundos.
        self._toast_id = self.root.after(4200, self._dismiss_toast)

    def _dismiss_toast(self) -> None:
        if getattr(self, "_toast", None) is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
            self._toast = None
        self._toast_id = None

    def _style_analysis_tags(self) -> None:
        t = self.theme
        box = self.analysis_box
        box.tag_configure("h", foreground=hexc(t["accent"]), font=self.f_bold, spacing1=self.px(8))
        box.tag_configure("ref", foreground=hexc(t["accent"]), underline=True)
        box.tag_configure("muted", foreground=hexc(t["muted"]))
        if hasattr(self, "history_detail"):
            self.history_detail.tag_configure("h", foreground=hexc(t["accent"]), font=self.f_bold)

    def style_combo(self, combo: ttk.Combobox, register: bool = True) -> None:
        if register:
            self.combos.append(combo)
        t = self.theme
        try:
            popdown = combo.tk.eval(f"ttk::combobox::PopdownWindow {combo}")
            combo.tk.call(f"{popdown}.f.l", "configure", "-background", hexc(t["surface"]),
                          "-foreground", hexc(t["text"]), "-selectbackground", hexc(t["accent"]),
                          "-selectforeground", hexc(t["accent_fg"]))
        except tk.TclError:
            pass

    def make_text(self, parent, height: int = 5, font=None, readonly: bool = False) -> tk.Text:
        widget = tk.Text(parent, height=height, wrap="word", font=font or self.f_base, padx=self.px(10),
                         pady=self.px(8), relief="flat", borderwidth=0, highlightthickness=1,
                         undo=not readonly, bg=hexc(darken(self.theme["surface"], 0.35)),
                         fg=hexc(self.theme["text"]))
        self._style_text(widget)
        if readonly:
            widget.configure(state="disabled")
        for sequence, handler in self.shortcuts:  # atalhos globais vencem os "estilo Emacs" do Tk
            widget.bind(sequence, handler)
        self.texts.append(widget)
        return widget

    # ----- fundo de vidro ------------------------------------------------------

    def _glass_palette(self) -> None:
        """Cores do vidro: dependem só do tema, então são iguais em todo widget."""
        t = self.theme
        self.glass_color = glass_surface(t)
        self.well_color = glass_well(t)
        self.glass_surface = hexc(self.glass_color)
        self.glass_well = hexc(self.well_color)
        self.glass_line = hexc(darken(self.glass_color, 0.25 if is_light(t) else 0.55))

    def _render_backdrop(self) -> None:
        """Desenha o fundo aurora com os painéis de vidro (só se algo mudou)."""
        if not hasattr(self, "backdrop"):
            return
        self._apply_glass_colors()
        width = max(320, self.backdrop.winfo_width())
        height = max(240, self.backdrop.winfo_height())
        key = (self.theme_name, width, height,
               tuple(tuple(sorted(p.items())) for p in self._glass_panels))
        if key == self._scene_key:
            return
        try:
            rgb = glass.compose(width, height, self.theme, self._glass_panels)
            self.backdrop.delete("all")
            if rgb is None:
                self._draw_plain_backdrop()
            else:
                try:
                    photo = tk.PhotoImage(master=self.root, data=glass.to_ppm(width, height, rgb), format="PPM")
                except tk.TclError:
                    photo = tk.PhotoImage(master=self.root, data=glass.encode_png(width, height, rgb))
                self._backdrop_photo = photo
                self.backdrop.create_image(0, 0, image=photo, anchor="nw")
            self._scene_key = key
        except Exception:  # noqa: BLE001 - o vidro é enfeite; nunca deve derrubar o app
            log.exception("Falha ao desenhar o fundo")

    def _draw_plain_backdrop(self) -> None:
        """Sem numpy: fundo liso e cartões chapados (nada pesado, nada trava)."""
        if not getattr(self, "_warned_numpy", False):
            self._warned_numpy = True
            log.warning("numpy não encontrado: usando visual simples (py -m pip install numpy ativa o vidro).")
        self.backdrop.configure(bg=hexc(self.theme["bg"]))
        edge = hexc(lighten(self.glass_color, 0.25))
        for p in self._glass_panels:
            self.backdrop.create_rectangle(p["x"], p["y"], p["x"] + p["w"], p["y"] + p["h"],
                                           fill=self.glass_surface, outline=edge)

    def _apply_glass_colors(self) -> None:
        """Aplica a cor do vidro aos frames, estilos ttk e à barra lateral."""
        key = (self.theme_name, self.base_size)
        if key == self._colors_key:
            return
        self._colors_key = key
        self._glass_palette()
        for frame in [*getattr(self, "glass_frames", []), getattr(self, "page_host", None)]:
            try:
                if frame is not None and frame.winfo_exists():
                    frame.configure(bg=self.glass_surface)
            except tk.TclError:
                pass
        self.apply_widget_colors()
        self._recolor_sidebar()

    def _recolor_sidebar(self) -> None:
        """A barra lateral também segue o tema (antes ficava com as cores antigas)."""
        if not hasattr(self, "sidebar"):
            return
        t = self.theme

        def walk(widget) -> None:
            try:
                widget.configure(bg=self.glass_surface)
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                walk(child)

        walk(self.sidebar)
        for widget, color in ((self.sidebar_title, t["text"]), (self.sidebar_sub, t["muted"]),
                              (self.theme_btn, t["muted"])):
            widget.configure(fg=hexc(color))
        self._highlight_nav(self.current_page)

    def apply_widget_colors(self) -> None:
        """Aplica as cores do vidro aos campos de entrada e listas."""
        if not hasattr(self, "glass_surface"):
            return
        for widget in getattr(self, "texts", []):
            try:
                if widget.winfo_exists():
                    widget.configure(bg=self.glass_well, fg=hexc(self.theme["text"]),
                                     insertbackground=hexc(self.theme["text"]))
            except tk.TclError:
                pass
        for tree in getattr(self, "trees", {}).values():
            try:
                tree.configure(background=self.glass_well, fieldbackground=self.glass_well)
            except tk.TclError:
                pass
        try:
            self.style.configure("Treeview", background=self.glass_well, fieldbackground=self.glass_well)
            self.style.configure("TEntry", fieldbackground=self.glass_well,
                                 foreground=hexc(self.theme["text"]),
                                 bordercolor=self.glass_line, lightcolor=self.glass_line,
                                 darkcolor=self.glass_line)
            self.style.configure("TCombobox", fieldbackground=self.glass_well,
                                 background=self.glass_surface, foreground=hexc(self.theme["text"]),
                                 bordercolor=self.glass_line)
            self.style.configure("TButton", background=self.glass_surface, foreground=hexc(self.theme["text"]),
                                 bordercolor=self.glass_surface, lightcolor=self.glass_surface,
                                 darkcolor=self.glass_surface)
            # Rótulos e quadros usam a cor exata do vidro: sem emenda visível
            # entre a área de conteúdo e o cartão desenhado atrás.
            self.style.configure("TLabel", background=self.glass_surface, foreground=hexc(self.theme["text"]))
            self.style.configure("TFrame", background=self.glass_surface)
            self.style.configure("Sub.TLabel", background=self.glass_surface, foreground=hexc(self.theme["muted"]))
            self.style.configure("H.TLabel", background=self.glass_surface)
            self.style.configure("Bold.TLabel", background=self.glass_surface)
            self.style.configure("Title.TLabel", background=self.glass_surface, foreground=hexc(self.theme["text"]))
            self.style.configure("Banner.TFrame", background=self.glass_well)
            self.style.configure("Banner.TLabel", background=self.glass_well, foreground=hexc(self.theme["text"]))
            self.style.configure("TPanedwindow", background=self.glass_surface)
            # Botões de vidro: um tom acima da placa (abaixo, no tema claro), com contorno fino.
            light = is_light(self.theme)
            shade = darken if light else lighten
            btn = hexc(shade(self.glass_color, 0.05 if light else 0.07))
            edge = hexc(shade(self.glass_color, 0.14 if light else 0.16))
            hot = hexc(shade(self.glass_color, 0.10 if light else 0.15))
            press = hexc(darken(self.glass_color, 0.18 if light else 0.12))
            for name in ("TButton", "Ghost.TButton"):
                self.style.configure(name, background=btn, bordercolor=edge, lightcolor=btn, darkcolor=btn)
                self.style.map(name, background=[("pressed", press), ("active", hot)])
            self.style.configure("TMenubutton", background=btn, bordercolor=edge)
            accent = self.theme["accent"]
            self.style.map("Action.TButton",
                           background=[("disabled", hexc(mix(self.glass_color, accent, 0.35))),
                                       ("pressed", hexc(darken(accent, 0.18))),
                                       ("active", hexc(lighten(accent, 0.10)))])
            self.style.map("TCombobox",
                           fieldbackground=[("readonly", self.glass_well), ("disabled", self.glass_well)],
                           foreground=[("readonly", hexc(self.theme["text"])), ("disabled", hexc(self.theme["muted"]))])
            bar = hexc(darken(self.glass_color, 0.10 if light else 0.35))
            self.style.configure("Status.TFrame", background=bar)
            self.style.configure("Status.TLabel", background=bar)
            # Divisória arrastável: sem o "pino" escuro padrão do tema clam.
            self.style.configure("Sash", sashthickness=self.px(8), gripcount=0, background=self.glass_surface,
                                 lightcolor=self.glass_surface, darkcolor=self.glass_surface,
                                 bordercolor=self.glass_surface)
            self.style.configure("TScrollbar", background=self.glass_surface, troughcolor=self.glass_surface,
                                 bordercolor=self.glass_surface, lightcolor=self.glass_surface,
                                 darkcolor=self.glass_surface)
            self.style.configure("Treeview.Heading", background=self.glass_well,
                                 foreground=hexc(self.theme["muted"]))
            self.style.configure("TCheckbutton", background=self.glass_surface,
                                 foreground=hexc(self.theme["text"]),
                                 indicatorbackground=self.glass_well,
                                 indicatorforeground=hexc(self.theme["text"]),
                                 upperbordercolor=self.glass_line, lowerbordercolor=self.glass_line)
        except tk.TclError:
            pass

    def _refresh_glass(self) -> None:
        """Recalcula a posição dos painéis e redesenha o fundo."""
        self._layout()

    # ----- atalhos e menus -----------------------------------------------------

    def _bind_shortcut(self, sequence: str, func, only_if=None) -> None:
        def handler(_event=None):
            if self.root.grab_current() is not None:  # há um diálogo aberto
                return None
            if only_if is not None and not only_if():
                return None
            func()
            return "break"
        self.root.bind_all(sequence, handler)
        self.shortcuts.append((sequence, handler))

    def _setup_shortcuts(self) -> None:
        b = self._bind_shortcut
        b("<Control-Return>", self.save_note)
        b("<Control-r>", self.analyze)
        b("<Control-Shift-R>", lambda: self.analyze(deep=True))
        b("<Control-s>", self.save_plan)
        b("<Control-o>", self.import_file)
        b("<Control-n>", self.focus_input)
        b("<Control-f>", self.focus_search)
        b("<Control-q>", self.close)
        b("<Control-t>", self.toggle_theme)
        b("<F5>", self.check_ollama)
        b("<Escape>", self.stop_analysis, only_if=lambda: self.busy)
        for index, (key, _label) in enumerate(NAV_ITEMS, start=1):
            b(f"<Control-Key-{index}>", lambda k=key: self.show_page(k))
        for seq in ("<Control-equal>", "<Control-plus>", "<Control-KP_Add>"):
            b(seq, lambda: self.set_font_size(self.base_size + 1))
        for seq in ("<Control-minus>", "<Control-KP_Subtract>"):
            b(seq, lambda: self.set_font_size(self.base_size - 1))
        b("<Control-Key-0>", lambda: self.set_font_size(10))

    def _build_menu(self) -> None:
        bar = tk.Menu(self.root)

        def menu(label: str) -> tk.Menu:
            m = tk.Menu(bar, tearoff=False)
            bar.add_cascade(label=label, menu=m)
            self.popup_menus.append(m)
            return m

        m = menu("Arquivo")
        m.add_command(label="Novo registro", accelerator="Ctrl+N", command=self.focus_input)
        m.add_command(label="Abrir relatório ou arquivo…", accelerator="Ctrl+O", command=self.import_file)
        m.add_command(label="Salvar plano", accelerator="Ctrl+S", command=self.save_plan)
        m.add_separator()
        m.add_command(label="Exportar tudo em Markdown…", command=self.export_markdown)
        m.add_command(label="Fazer backup dos dados (.zip)…", command=self.backup_zip)
        m.add_command(label="Abrir pasta de dados", command=self.open_data_folder)
        m.add_separator()
        m.add_command(label="Sair", accelerator="Ctrl+Q", command=self.close)

        m = menu("Editar")
        m.add_command(label="Guardar registro", accelerator="Ctrl+Enter", command=self.save_note)
        m.add_command(label="Nova ação…", command=self.new_action)
        m.add_command(label="Registrar decisão…", command=self.new_decision)
        m.add_separator()
        m.add_command(label="Pesquisar registros", accelerator="Ctrl+F", command=self.focus_search)

        m = menu("Exibir")
        for index, (key, label) in enumerate(NAV_ITEMS, start=1):
            m.add_command(label=label, accelerator=f"Ctrl+{index}", command=lambda k=key: self.show_page(k))
        m.add_separator()
        for name, spec in THEMES.items():
            m.add_command(label=spec["label"], command=lambda n=name: self.set_theme(n))
        m.add_separator()
        m.add_command(label="Aumentar fonte", accelerator="Ctrl++", command=lambda: self.set_font_size(self.base_size + 1))
        m.add_command(label="Diminuir fonte", accelerator="Ctrl+-", command=lambda: self.set_font_size(self.base_size - 1))
        m.add_command(label="Fonte padrão", accelerator="Ctrl+0", command=lambda: self.set_font_size(10))

        m = menu("IA")
        m.add_command(label="Analisar rápido", accelerator="Ctrl+R", command=self.analyze)
        m.add_command(label="Análise aprofundada", accelerator="Ctrl+Shift+R", command=lambda: self.analyze(deep=True))
        m.add_command(label="Parar análise", accelerator="Esc", command=self.stop_analysis)
        m.add_separator()
        m.add_checkbutton(label="Analisar ao guardar (local)", variable=self.auto_var, command=self.save_auto_preference)
        m.add_command(label="Atualizar modelos / reconectar", accelerator="F5", command=self.check_ollama)

        m = menu("Ajuda")
        m.add_command(label="Atalhos de teclado", command=self.show_shortcuts)
        m.add_command(label="Abrir arquivo de log", command=self.open_log)
        m.add_command(label="Sobre o Javis", command=self.show_about)
        self.root.configure(menu=bar)

    # ----- construção da interface ---------------------------------------------

    def _wrap_label(self, parent, text: str, style: str = "Sub.TLabel") -> ttk.Label:
        label = ttk.Label(parent, text=text, style=style, justify="left", wraplength=self.px(600))
        label.bind("<Configure>", lambda e, w=label: w.configure(wraplength=max(self.px(200), e.width - 8)))
        return label

    def _header(self, parent, title: str, subtitle: str = "") -> None:
        ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
        if subtitle:
            self._wrap_label(parent, subtitle).pack(fill="x", pady=(2, 10))

    def _scrolled_text(self, parent, height: int = 5, font=None, readonly: bool = False):
        frame = ttk.Frame(parent)
        text = self.make_text(frame, height=height, font=font, readonly=readonly)
        bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        return frame, text

    def _make_tree(self, parent, name: str, columns: list[tuple], height: int = 8):
        """columns: (chave, título, largura, estica, alinhamento)."""
        wrap = ttk.Frame(parent)
        tree = ttk.Treeview(wrap, columns=[c[0] for c in columns], show="headings", selectmode="browse", height=height)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        for key, title, width, stretch, anchor in columns:
            tree.heading(key, text=title, anchor=anchor, command=lambda k=key, n=name: self._sort_by(n, k))
            tree.column(key, width=self.px(width), minwidth=self.px(50), stretch=stretch, anchor=anchor)
        self.trees[name] = tree
        self.tree_cols[name] = [c[0] for c in columns]
        self.tree_titles[name] = {c[0]: c[1] for c in columns}
        return wrap, tree

    def _sort_by(self, name: str, column: str) -> None:
        current, reverse = self.sort_state.get(name, (None, False))
        self.sort_state[name] = (column, not reverse) if current == column else (column, False)
        self.refresh_all_for(name)

    def refresh_all_for(self, name: str) -> None:
        {"notes": self.refresh_notes, "actions": self.refresh_actions,
         "decisions": self.refresh_decisions, "history": self.refresh_history}[name]()

    def _fill_tree(self, name: str, rows: list[tuple]) -> None:
        """rows: (iid, valores, tags, chaves_de_ordenação)."""
        tree = self.trees[name]
        column, reverse = self.sort_state.get(name, (None, False))
        if column:
            index = self.tree_cols[name].index(column)
            rows = sorted(rows, key=lambda r: r[3][index], reverse=reverse)
        selected = [s for s in tree.selection()]
        tree.delete(*tree.get_children())
        for position, (iid, values, tags, _keys) in enumerate(rows):
            tree.insert("", "end", iid=iid, values=values, tags=tuple(tags) + (("odd",) if position % 2 else ()))
        keep = [s for s in selected if tree.exists(s)]
        if keep:
            tree.selection_set(keep)
            tree.see(keep[0])
        for key, title in self.tree_titles[name].items():
            arrow = (" ▼" if reverse else " ▲") if key == column else ""
            tree.heading(key, text=title + arrow)

    def _bind_context(self, tree: ttk.Treeview, menu: tk.Menu) -> None:
        def show(event):
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                tree.focus(row)
                menu.tk_popup(event.x_root, event.y_root)
                menu.grab_release()
        tree.bind("<Button-3>", show)

    def _status_menu(self, parent) -> tk.Menu:
        menu = tk.Menu(parent, tearoff=False)
        self.popup_menus.append(menu)
        for status in STATUSES:
            menu.add_command(label=status.capitalize(), command=lambda s=status: self.set_action_status(s))
        return menu

    def _build(self) -> None:
        root = self.root

        # O fundo de vidro é o Canvas mais baixo: a janela inteira é uma
        # "mesa" de aurora com um cartão de vidro flutuante sobre ela.
        self.backdrop = tk.Canvas(root, bd=0, highlightthickness=0, bg=hexc(self.theme["bg"]))
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)

        # A barra lateral vem logo acima do fundo.
        self._build_sidebar(root)

        # As páginas ficam por cima do cartão de vidro, exatamente sobre ele.
        # Usam grid dentro de um contentor: o Tk trata a geometria com mais
        # confiança do que com place() encadeado.
        self.page_host = tk.Frame(root, bg=self.glass_surface)
        self.page_host.place(x=0, y=0, width=10, height=10)
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_host.grid_columnconfigure(0, weight=1)
        self.page_host.bind("<Configure>", lambda _e: None)

        self.glass_frames: list[tk.Widget] = []
        for key, _label in NAV_ITEMS:
            page = tk.Frame(self.page_host, bg=self.glass_surface)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
            self.glass_frames.append(page)
        self._build_capture(self.pages["capture"])
        self._build_records(self.pages["records"])
        self._build_actions(self.pages["actions"])
        self._build_decisions(self.pages["decisions"])
        self._build_plan(self.pages["plan"])
        self._build_history(self.pages["history"])

        # Barra de status: no rodapé, por cima de tudo.
        self.status_bar = ttk.Frame(root, style="Status.TFrame")
        self.status = ttk.Label(self.status_bar, text=f"Dados privados neste computador: {DATA_DIR}",
                                style="Status.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        root.bind("<Configure>", self._on_root_configure)
        self.root.after(200, self._layout)

    def _on_root_configure(self, event=None) -> None:
        """Redesenha o vidro quando a janela muda de tamanho.

        O <Configure> da janela chega também de TODOS os widgets filhos; sem
        este filtro, cada reposicionamento disparava um novo redesenho em
        cascata (6 renders só para abrir o app).
        """
        if event is not None and event.widget is not self.root:
            return
        if (self.root.winfo_width(), self.root.winfo_height()) == self._laid_size:
            return
        if self._layout_pending:
            return
        self._layout_pending = True
        self.root.after(140, self._run_layout)

    def _run_layout(self) -> None:
        self._layout_pending = False
        self._layout()

    def _layout(self) -> None:
        """Posiciona os painéis de vidro e o conteúdo exatamente sobre eles.

        O miolo de cada painel é a cor chapada do vidro; o conteúdo começa
        depois da borda (`rim`), onde o vidro já convergiu para essa cor.
        """
        if not hasattr(self, "backdrop"):
            return
        width = max(320, self.backdrop.winfo_width())
        height = max(240, self.backdrop.winfo_height())
        self._laid_size = (self.root.winfo_width(), self.root.winfo_height())
        margin = self.px(14)
        status_h = self.px(34)
        radius = int(self.theme.get("card_radius", 20))
        rim_side, rim_card = self.px(12), self.px(18)

        panel_h = max(40, height - margin * 2 - status_h)
        side_w = SIDEBAR_W - margin
        card_x = SIDEBAR_W + margin
        card_w = max(40, width - card_x - margin)
        self._glass_panels = [
            {"x": margin, "y": margin, "w": side_w, "h": panel_h, "radius": radius, "rim": rim_side},
            {"x": card_x, "y": margin, "w": card_w, "h": panel_h, "radius": radius, "rim": rim_card},
        ]

        if hasattr(self, "sidebar"):
            self.sidebar.place(x=margin + rim_side, y=margin + rim_side,
                               width=max(10, side_w - rim_side * 2), height=max(10, panel_h - rim_side * 2))
        page_geo = (card_x + rim_card, margin + rim_card,
                    max(10, card_w - rim_card * 2), max(10, panel_h - rim_card * 2))
        self._page_geometry = page_geo
        self.page_host.place(x=page_geo[0], y=page_geo[1], width=page_geo[2], height=page_geo[3])
        if hasattr(self, "status_bar"):
            self.status_bar.place(x=0, y=height - status_h, width=width, height=status_h)

        # O Tk só aplica a nova geometria no próximo ciclo; sem isto os
        # widgets ficam com 1x1 até a próxima interação do usuário.
        self.root.update_idletasks()
        self._render_backdrop()

    def _build_sidebar(self, parent) -> None:
        t = self.theme
        bgc = self.glass_surface
        side = tk.Frame(parent, bg=bgc)
        side.pack_propagate(False)
        self.sidebar = side

        title = tk.Label(side, text="JAVIS", bg=bgc, fg=hexc(t["text"]),
                         font=(self.family, self.base_size + 7, "bold"))
        title.pack(anchor="w", padx=(10, 0), pady=(14, 0))
        sub = tk.Label(side, text="Plano Bismarck", bg=bgc, fg=hexc(t["muted"]), font=self.f_small)
        sub.pack(anchor="w", padx=(12, 0), pady=(2, 0))
        self.sidebar_title, self.sidebar_sub = title, sub

        nav_frame = tk.Frame(side, bg=bgc)
        nav_frame.pack(fill="x", pady=(22, 0))
        self.nav_canvas = nav_frame

        self.nav_buttons: list[tk.Frame] = []
        for key, label in NAV_ITEMS:
            holder = tk.Frame(nav_frame, bg=bgc, height=42, cursor="hand2")
            holder.pack(fill="x", padx=2, pady=2)
            holder.pack_propagate(False)
            lbl = tk.Label(holder, text=label, bg=bgc, fg=hexc(t["muted"]), font=self.f_base, anchor="w", padx=14)
            lbl.pack(fill="x", pady=9)
            for widget in (holder, lbl):
                widget.bind("<Button-1>", lambda _e, k=key: self.show_page(k))
                widget.bind("<Enter>", lambda _e, k=key: self._nav_hover(k, True))
                widget.bind("<Leave>", lambda _e, k=key: self._nav_hover(k, False))
            self.nav[key] = holder
            self.nav_labels[key] = lbl
            self.nav_buttons.append(holder)

        spacer = tk.Frame(side, bg=bgc)
        spacer.pack(fill="both", expand=True)

        self.ai_label = tk.Label(side, text="", bg=bgc, fg=hexc(t["muted"]), font=self.f_small,
                                 justify="left", anchor="w", wraplength=self.px(160))
        self.ai_label.pack(fill="x", padx=10, pady=(0, 10))

        theme_btn = tk.Label(side, text="◐  Alternar tema", bg=bgc, fg=hexc(t["muted"]),
                             font=self.f_small, cursor="hand2")
        theme_btn.pack(anchor="w", padx=10, pady=(0, 8))
        theme_btn.bind("<Button-1>", lambda _e: self.toggle_theme())
        self.theme_btn = theme_btn

    def _nav_hover(self, key: str, entering: bool) -> None:
        """Realce suave ao passar o mouse; o item ativo mantém o destaque."""
        if key == self.current_page:
            return
        t = self.theme
        bg = hexc(lighten(self.glass_color, 0.10)) if entering else self.glass_surface
        self.nav[key].configure(bg=bg)
        self.nav_labels[key].configure(bg=bg, fg=hexc(t["text"]) if entering else hexc(t["muted"]))

    def _build_capture(self, tab) -> None:
        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True)

        top = ttk.Frame(pane)
        pane.add(top, weight=1)
        ttk.Label(top, text="O que aconteceu, o que você está pensando ou o que deseja entender?",
                  style="H.TLabel").pack(anchor="w", pady=(0, 4))
        bar = ttk.Frame(top)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        box_frame, self.input_box = self._scrolled_text(top, height=6, font=self.f_input)
        box_frame.pack(fill="both", expand=True)
        self.input_box.bind("<KeyRelease>", lambda _e: self._update_count())

        ttk.Button(bar, text="Abrir arquivo…", style="Ghost.TButton", command=self.import_file).pack(side="left")
        self.make_button(bar, "Guardar registro", self.save_note, "Action.TButton", accent=True).pack(side="left", padx=8)
        self.analyze_btn = self.make_button(bar, "Analisar rápido", self.analyze, "Action.TButton", accent=True)
        self.analyze_btn.pack(side="left")
        self.deep_btn = self.make_button(bar, "Análise aprofundada", lambda: self.analyze(deep=True), "Ghost.TButton")
        self.deep_btn.pack(side="left", padx=8)
        self.stop_btn = self.make_button(bar, "Parar", self.stop_analysis, "Ghost.TButton")
        self.stop_btn.pack(side="left")
        self.count_label = ttk.Label(bar, text="", style="Sub.TLabel")
        self.count_label.pack(side="right")
        self.busy_indicator = ttk.Label(bar, text="", style="Sub.TLabel")
        self.busy_indicator.pack(side="right", padx=(0, 10))

        bottom = ttk.Frame(pane)
        pane.add(bottom, weight=2)
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(2, weight=1)
        head = ttk.Frame(bottom)
        head.grid(row=0, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(head, text="Análise e próximos passos", style="H.TLabel").pack(side="left")
        self.approve_plan_btn = ttk.Button(head, text="Aprovar atualização do plano…", style="Action.TButton",
                                            command=self.approve_plan_update, state="disabled")
        self.approve_plan_btn.pack(side="right")
        ttk.Button(head, text="Copiar", style="Ghost.TButton", command=self.copy_analysis).pack(side="right", padx=(0, 8))

        self.relation_frame = ttk.Frame(bottom, style="Banner.TFrame", padding=(10, 8))
        self.relation_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.relation_text = ttk.Label(self.relation_frame, text="", style="Banner.TLabel", justify="left",
                                       wraplength=self.px(560))
        self.relation_text.bind("<Configure>", lambda e: self.relation_text.configure(wraplength=max(self.px(200), e.width - 8)))
        self.relation_text.pack(side="left", fill="x", expand=True)
        ttk.Button(self.relation_frame, text="Ignorar", style="Ghost.TButton", command=self.ignore_relation).pack(side="right")
        ttk.Button(self.relation_frame, text="Confirmar vínculo", style="Action.TButton",
                   command=self.confirm_relation).pack(side="right", padx=6)
        self.relation_frame.grid_remove()

        analysis_frame, self.analysis_box = self._scrolled_text(bottom, height=8, readonly=True)
        analysis_frame.grid(row=2, column=0, sticky="nsew")
        self._set_analysis("A análise aparecerá aqui. Use “Analisar rápido” (Ctrl+R) ou “Análise aprofundada” (Ctrl+Shift+R).", muted=True)
        self.analysis_box.bind("<Button-1>", self._on_analysis_click)

        opts = ttk.Frame(bottom)
        opts.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(opts, text="Analisar ao guardar (local)", variable=self.auto_var,
                        command=self.save_auto_preference).pack(side="left")
        self.refresh_models_btn = ttk.Button(opts, text="Atualizar modelos", style="Ghost.TButton", command=self.check_ollama)
        self.refresh_models_btn.pack(side="right")
        self.model_var = tk.StringVar(value=self.state.get("preferred_model", ""))
        self.model_combo = ttk.Combobox(opts, textvariable=self.model_var, state="disabled", width=22)
        self.model_combo.pack(side="right", padx=(6, 8))
        self.style_combo(self.model_combo)
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_selected)
        ttk.Label(opts, text="Modelo aprofundado:", style="Sub.TLabel").pack(side="right")
        self._wrap_label(bottom, "A análise não altera nada sozinha. Revise a sugestão e aprove explicitamente qualquer mudança no plano.").grid(row=4, column=0, sticky="ew", pady=(6, 0))

    def _build_records(self, tab) -> None:
        self._header(tab, "Registros", "Textos e relatórios salvos neste computador. Pesquise por palavra, data ou ID.")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Pesquisar:").pack(side="left")
        self.note_search = tk.StringVar()
        self.search_entry = ttk.Entry(row, textvariable=self.note_search)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Limpar", style="Ghost.TButton", command=lambda: self.note_search.set("")).pack(side="left")
        self.note_count = ttk.Label(row, text="", style="Sub.TLabel")
        self.note_count.pack(side="left", padx=(10, 0))
        self.note_search.trace_add("write", lambda *_: self._debounce("notes", self.refresh_notes))
        buttons = ttk.Frame(tab)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Analisar registro selecionado", style="Action.TButton",
                   command=self.analyze_selected_note).pack(side="left")
        ttk.Button(buttons, text="Copiar texto", style="Ghost.TButton", command=self.copy_selected_note).pack(side="left", padx=8)
        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        wrap, self.notes_tree = self._make_tree(pane, "notes", [("id", "ID", 80, False, "w"),
                                                                  ("data", "Data", 130, False, "w"),
                                                                  ("resumo", "Registro", 640, True, "w")])
        pane.add(wrap, weight=3)
        detail, self.note_details = self._scrolled_text(pane, height=6, readonly=True)
        pane.add(detail, weight=2)
        self.notes_tree.bind("<<TreeviewSelect>>", lambda _e: self.show_note_details())
        self.notes_tree.bind("<Double-1>", lambda _e: self.analyze_selected_note())
        menu = tk.Menu(self.root, tearoff=False)
        self.popup_menus.append(menu)
        menu.add_command(label="Analisar registro", command=self.analyze_selected_note)
        menu.add_command(label="Copiar texto", command=self.copy_selected_note)
        self._bind_context(self.notes_tree, menu)

    def _build_actions(self, tab) -> None:
        self._header(tab, "Ações e acompanhamento",
                     "Registre o que foi feito, o resultado esperado e o que aconteceu depois. "
                     "Ações com data de revisão vencida aparecem em vermelho.")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Mostrar:").pack(side="left")
        self.action_filter = tk.StringVar(value="Todas")
        combo = ttk.Combobox(row, textvariable=self.action_filter, state="readonly", width=14,
                             values=["Todas", "Abertas", "Atrasadas", "Concluídas", "Canceladas"])
        combo.pack(side="left", padx=8)
        self.style_combo(combo)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_actions())
        self.action_count = ttk.Label(row, text="", style="Sub.TLabel")
        self.action_count.pack(side="left")
        buttons = ttk.Frame(tab)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Nova ação…", style="Action.TButton", command=self.new_action).pack(side="left")
        ttk.Button(buttons, text="Registrar resultado…", style="Ghost.TButton", command=self.record_outcome).pack(side="left", padx=8)
        menubutton = ttk.Menubutton(buttons, text="Status")
        menubutton.configure(menu=self._status_menu(menubutton))
        menubutton.pack(side="left")
        ttk.Button(buttons, text="Editar…", style="Ghost.TButton", command=self.edit_action).pack(side="left", padx=8)
        ttk.Button(buttons, text="Analisar efeito com Javis", style="Action.TButton",
                   command=self.analyze_action).pack(side="right")
        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        wrap, self.actions_tree = self._make_tree(pane, "actions", [
            ("id", "ID", 70, False, "w"), ("prioridade", "Prior.", 85, False, "w"),
            ("acao", "Ação / resultado esperado", 520, True, "w"),
            ("prazo", "Revisar em", 125, False, "w"), ("status", "Status", 135, False, "w")])
        pane.add(wrap, weight=3)
        detail, self.action_details = self._scrolled_text(pane, height=6, readonly=True)
        pane.add(detail, weight=2)
        self.actions_tree.bind("<<TreeviewSelect>>", lambda _e: self.show_action_details())
        self.actions_tree.bind("<Double-1>", lambda _e: self.record_outcome())
        menu = tk.Menu(self.root, tearoff=False)
        self.popup_menus.append(menu)
        menu.add_command(label="Registrar resultado…", command=self.record_outcome)
        menu.add_cascade(label="Status", menu=self._status_menu(menu))
        menu.add_command(label="Editar…", command=self.edit_action)
        menu.add_command(label="Analisar efeito com Javis", command=self.analyze_action)
        self._bind_context(self.actions_tree, menu)

    def _build_decisions(self, tab) -> None:
        self._header(tab, "Decisões", "Sugestões do Javis não são decisões. Registre aqui apenas o que você decidiu de fato.")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Mostrar:").pack(side="left")
        self.decision_filter = tk.StringVar(value="Todas")
        combo = ttk.Combobox(row, textvariable=self.decision_filter, state="readonly", width=14,
                             values=["Todas", "Vigentes", "Substituídas"])
        combo.pack(side="left", padx=8)
        self.style_combo(combo)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_decisions())
        buttons = ttk.Frame(tab)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Registrar decisão confirmada…", style="Action.TButton",
                   command=self.new_decision).pack(side="left")
        ttk.Button(buttons, text="Marcar como substituída", style="Ghost.TButton",
                   command=self.supersede_decision).pack(side="left", padx=8)
        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        wrap, self.decisions_tree = self._make_tree(pane, "decisions", [("id", "ID", 70, False, "w"),
                                                                         ("data", "Data", 120, False, "w"),
                                                                         ("texto", "Decisão", 620, True, "w"),
                                                                         ("status", "Status", 130, False, "w")])
        pane.add(wrap, weight=3)
        detail, self.decision_details = self._scrolled_text(pane, height=5, readonly=True)
        pane.add(detail, weight=1)
        self.decisions_tree.bind("<<TreeviewSelect>>", lambda _e: self.show_decision_details())
        menu = tk.Menu(self.root, tearoff=False)
        self.popup_menus.append(menu)
        menu.add_command(label="Marcar como substituída", command=self.supersede_decision)
        self._bind_context(self.decisions_tree, menu)

    def _build_plan(self, tab) -> None:
        self._header(tab, "Plano Bismarck", "Edite o plano diretamente. Cada gravação guarda uma cópia da versão anterior neste computador.")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Salvar plano", style="Action.TButton", command=self.save_plan).pack(side="left")
        ttk.Button(bar, text="Recarregar do disco", style="Ghost.TButton", command=self.reload_plan).pack(side="left", padx=8)
        ttk.Button(bar, text="Versões anteriores…", style="Ghost.TButton", command=self.show_plan_versions).pack(side="left")
        self.dirty_label = ttk.Label(bar, text="", style="Bold.TLabel", foreground=hexc(self.theme["warn"]))
        self.dirty_label.pack(side="right")
        ttk.Label(tab, text=str(PLAN_FILE), style="Sub.TLabel").pack(side="bottom", anchor="w", pady=(6, 0))
        frame, self.plan_box = self._scrolled_text(tab, height=10, font=self.f_mono)
        frame.pack(fill="both", expand=True)
        self.plan_box.insert("1.0", self.state.get("plano", ""))
        self.plan_box.edit_modified(False)
        self.plan_box.edit_reset()
        self.plan_box.bind("<<Modified>>", self._on_plan_modified)

    def _build_history(self, tab) -> None:
        self._header(tab, "Histórico", "Eventos do Javis e análises anteriores. Selecione uma análise para reler a resposta completa.")
        buttons = ttk.Frame(tab)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Abrir análise na tela inicial", style="Action.TButton",
                   command=self.reopen_analysis).pack(side="left")
        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        wrap, self.history_tree = self._make_tree(pane, "history", [("data", "Data", 150, False, "w"),
                                                                      ("tipo", "Tipo", 90, False, "w"),
                                                                      ("desc", "Descrição", 700, True, "w")])
        pane.add(wrap, weight=3)
        detail, self.history_detail = self._scrolled_text(pane, height=8, readonly=True)
        pane.add(detail, weight=2)
        self.history_tree.bind("<<TreeviewSelect>>", lambda _e: self.show_history_detail())
        self.history_tree.bind("<Double-1>", lambda _e: self.reopen_analysis())

    # ----- navegação e status --------------------------------------------------

    def show_page(self, key: str) -> None:
        self.current_page = key
        # Apenas a página ativa fica no grid; as outras são removidas.
        # O Tk cuida da visibilidade, ao contrário do tkraise/lower.
        for name, page in self.pages.items():
            if name == key:
                if not page.winfo_manager():
                    page.grid(row=0, column=0, sticky="nsew")
            elif page.winfo_manager():
                page.grid_forget()
        # O grid_forget das páginas pode mexer na geometria do contentor.
        geo = getattr(self, "_page_geometry", None)
        if geo and self.page_host.winfo_width() < 2:
            self.page_host.place(x=geo[0], y=geo[1], width=geo[2], height=geo[3])
        for name, label in self.nav_labels.items():
            active = name == key
            color = hexc(self.theme["text"]) if active else hexc(self.theme["muted"])
            try:
                label.configure(fg=color)
            except tk.TclError:
                pass
        self._highlight_nav(key)
        if key == "capture":
            try:
                self.input_box.focus_set()
            except tk.TclError:
                pass

    def _highlight_nav(self, key: str) -> None:
        """Destaca o item ativo na barra lateral."""
        t = self.theme
        for name, holder in self.nav.items():
            active = name == key
            bg = hexc(t["accent"]) if active else self.glass_surface
            fg = hexc(t["accent_fg"]) if active else hexc(t["muted"])
            holder.configure(bg=bg)
            try:
                self.nav_labels[name].configure(bg=bg, fg=fg)
            except tk.TclError:
                pass

    def focus_input(self) -> None:
        self.show_page("capture")
        self.input_box.focus_set()

    def focus_search(self) -> None:
        self.show_page("records")
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def set_status(self, text: str, kind: str = "info") -> None:
        self.status_kind = kind
        color = {"ok": hexc(self.theme["ok"]), "warn": hexc(self.theme["warn"]),
                 "err": hexc(self.theme["danger"])}.get(kind, hexc(self.theme["muted"]))
        self.status.configure(text=text, foreground=color)

    def set_ai_status(self, text: str, kind: str = "muted") -> None:
        self.ai_status = (text, kind)
        color = {"ok": hexc(self.theme["ok"]), "warn": hexc(self.theme["warn"])}.get(kind, hexc(self.theme["muted"]))
        self.ai_label.configure(text="● " + text, foreground=color)

    def _start_pulse(self) -> None:
        """Pulsa o indicador de IA e anima a barra de atividade."""
        self._pulse_phase = (self._pulse_phase + 0.05) % 1.0
        if self.ai_status[1] == "ok":
            self.ai_label.configure(fg=hexc(mix(self.theme["ok"], self.theme["text"], self._pulse_phase * 0.5)))
        if self.busy and hasattr(self, "busy_indicator"):
            try:
                self.busy_indicator.configure(
                    text="●" * int(1 + self._pulse_phase * 3),
                    foreground=hexc(self.theme["accent"]))
            except tk.TclError:
                pass
        self._pulse_id = self.root.after(90, self._start_pulse)

    def _update_buttons(self) -> None:
        idle_ready = self.ollama_ready and not self.busy and not self.warming_model
        self.analyze_btn.configure(state="normal" if idle_ready else "disabled",
                                   text="Analisando…" if self.busy else "Analisar rápido")
        self.deep_btn.configure(state="normal" if idle_ready else "disabled")
        self.stop_btn.configure(state="normal" if self.busy else "disabled")
        self.approve_plan_btn.configure(state="normal" if (self.plan_proposal and not self.busy) else "disabled")
    def _update_count(self) -> None:
        text = self.input_box.get("1.0", "end").strip()
        self.count_label.configure(text=f"{len(text.split())} palavras · {len(text)} caracteres" if text else "")

    def _debounce(self, key: str, func, delay: int = 200) -> None:
        if key in self._debounce_ids:
            self.root.after_cancel(self._debounce_ids[key])
        self._debounce_ids[key] = self.root.after(delay, lambda: (self._debounce_ids.pop(key, None), func()))

    def _on_tk_error(self, exc, val, tb) -> None:
        log.error("Erro na interface", exc_info=(exc, val, tb))
        self.set_status(f"Ocorreu um erro inesperado ({val}). Detalhes em {LOG_FILE.name}.", "err")

    def _autosave_draft(self) -> None:
        text = self.input_box.get("1.0", "end").strip()
        if text != self.state.get("rascunho", ""):
            self.state["rascunho"] = text
            try:
                save_state(self.state)
            except OSError:
                log.exception("Falha ao salvar rascunho")
        self.root.after(30000, self._autosave_draft)

    def _on_plan_modified(self, _event=None) -> None:
        self.dirty_label.configure(text="● alterações não salvas" if self.plan_box.edit_modified() else "")

    # ----- utilidades de lista/detalhe -----------------------------------------

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _selected_iid(self, tree: ttk.Treeview) -> str | None:
        selected = tree.selection()
        return selected[0] if selected else None

    def _select_row(self, tree: ttk.Treeview, iid: str) -> bool:
        if not tree.exists(iid):
            return False
        tree.selection_set(iid)
        tree.focus(iid)
        tree.see(iid)
        return True

    def _copy(self, text: str, what: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status(f"{what} copiado para a área de transferência.", "ok")

    def refresh_all(self) -> None:
        self.refresh_notes()
        self.refresh_actions()
        self.refresh_decisions()
        self.refresh_history()
        due = sum(1 for a in self.state["acoes"] if llm_action_due(a))
        if due:
            self.set_status(f"Acompanhamento pendente em {due} ação(ões). Abra “Ações e resultados” para registrar o que aconteceu.", "warn")

    # ----- registros -----------------------------------------------------------

    def refresh_notes(self) -> None:
        query = self.note_search.get().strip().casefold()
        rows = []
        for note in reversed(self.state["notas"]):
            note_id = note.get("id", "")
            text = str(note.get("texto", ""))
            if query and query not in f"{note_id} {note.get('data', '')[:10]} {br_date(note.get('data'))} {text}".casefold():
                continue
            preview = " ".join(text[:400].split())
            if len(preview) > 180:
                preview = preview[:177] + "…"
            rows.append((note_id or str(id(note)), (note_id, br_datetime(note.get("data")), preview), (),
                         (note_id, note.get("data", ""), preview.casefold())))
        self._fill_tree("notes", rows)
        self.note_count.configure(text=f"{len(rows)} de {len(self.state['notas'])}")
        self.show_note_details()

    def _selected_note(self) -> dict | None:
        iid = self._selected_iid(self.notes_tree)
        return find_by_id(self.state["notas"], self.notes_tree.set(iid, "id")) if iid else None

    def show_note_details(self) -> None:
        note = self._selected_note()
        if not note:
            self._set_text(self.note_details, "Selecione um registro para ler o texto completo.")
            return
        links = [r.get("relacionado_a") for r in self.state.get("relacoes", [])
                 if r.get("evento_id") == note.get("id") and r.get("status") == "confirmada"]
        link_text = f"\n\nVínculos confirmados: {', '.join(links)}" if links else ""
        self._set_text(self.note_details, f"{br_datetime(note.get('data'))} · {note.get('id', '')}\n\n{note.get('texto', '')}{link_text}")

    def copy_selected_note(self) -> None:
        note = self._selected_note()
        if note:
            self._copy(str(note.get("texto", "")), "Texto do registro")
        else:
            self.set_status("Selecione um registro primeiro.", "warn")

    def analyze_selected_note(self) -> None:
        note = self._selected_note()
        if not note:
            self.set_status("Selecione um registro primeiro.", "warn")
            return
        note_id = note.get("id")
        self.analyze(f"Analise o registro {note_id} em foco e compare com o Plano Bismarck, as decisões, ações e resultados anteriores.",
                     note_id=note_id)

    def save_note(self) -> None:
        text = self.input_box.get("1.0", "end").strip()
        if not text:
            self.set_status("Escreva um registro ou carregue um arquivo primeiro.", "warn")
            return
        item = self._store_note(text)
        self.input_box.delete("1.0", "end")
        self._update_count()
        if self.auto_var.get():
            if self._ensure_local_consent():
                item["analise_automatica_pendente"] = True
                save_state(self.state)
                self.auto_queue.insert(0, (item["id"], text))
                if self.ollama_ready:
                    self._start_next_auto_review()
                else:
                    self.set_status(f"Registro {item['id']} salvo. Abra o Ollama para iniciar a revisão automática local.", "warn")
            else:
                self.auto_var.set(False)
                self.save_auto_preference()
                self.set_status(f"Registro {item['id']} salvo localmente, sem análise automática.", "ok")
                self.toast(f"Registro {item['id']} salvo", "ok")
        else:
            self.set_status(f"Registro {item['id']} salvo localmente.", "ok")
            self.toast(f"Registro {item['id']} salvo", "ok")

    def _store_note(self, text: str) -> dict:
        item = {"id": next_id("N", self.state["notas"]), "data": now_iso(), "texto": text,
                "origem": "interface do Javis", "tipo": "registro", "analisada": False}
        self.state["notas"].append(item)
        self.state["rascunho"] = ""
        add_history(self.state, f"Registro {item['id']} salvo.")
        save_state(self.state)
        self.refresh_notes()
        self.refresh_history()
        return item

    def save_auto_preference(self) -> None:
        self.state["auto_analysis_enabled"] = bool(self.auto_var.get())
        if not self.auto_var.get():
            self.auto_queue.clear()
            for note in self.state["notas"]:
                note.pop("analise_automatica_pendente", None)
        save_state(self.state)

    def _ensure_local_consent(self) -> bool:
        if self.state.get("ai_consent_local"):
            return True
        approved = messagebox.askyesno(
            APP_NAME,
            "Ativar análise local do Javis?\n\nQuando você guardar um registro, o texto e os acontecimentos recentes serão enviados somente ao Ollama neste computador (127.0.0.1) para procurar possíveis relações. Você pode desligar a análise automática nesta tela."
        )
        if approved:
            self.state["ai_consent_local"] = True
            save_state(self.state)
        return approved

    def _start_next_auto_review(self) -> None:
        if self.busy or self.warming_model or self.current_relation_id or not self.auto_queue or not self.ollama_ready:
            return
        note_id, _text = self.auto_queue.pop(0)
        if not find_by_id(self.state["notas"], note_id):
            self._start_next_auto_review()
            return
        prompt = f"Faça a triagem rápida do registro {note_id} em foco no contexto. Se ele descrever um acontecimento, procure relações com registros anteriores."
        self.analyze(prompt_override=prompt, automatic=True, note_id=note_id)

    def import_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Escolher um documento",
            filetypes=[("Documentos compatíveis", "*.txt *.md *.csv *.json *.log *.docx *.pdf"), ("Todos os arquivos", "*.*")])
        if not filename:
            return
        path = Path(filename)
        try:
            size = path.stat().st_size
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não consegui acessar esse arquivo.\n\n{exc}")
            return
        if size > MAX_IMPORT_BYTES and not messagebox.askyesno(
                APP_NAME, f"O arquivo tem {size / 1048576:.1f} MB e pode demorar para abrir. Continuar?"):
            return
        self.show_page("capture")
        self.set_status(f"Lendo {path.name}…")

        def work() -> None:
            try:
                content, error = read_document(path), None
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha ao importar %s", path)
                content, error = "", str(exc)
            self.events.put(("imported", None, (path.name, content, error)))

        threading.Thread(target=work, daemon=True).start()

    def _finish_import(self, name: str, content: str, error: str | None) -> None:
        if error:
            messagebox.showerror(APP_NAME, f"Não consegui abrir esse arquivo.\n\n{error}")
            self.set_status(f"Falha ao abrir {name}.", "err")
            return
        if not content.strip():
            self.set_status(f"{name} não contém texto legível (um PDF escaneado, por exemplo, precisa de OCR).", "warn")
            return
        self.input_box.insert("end", f"\n\n--- Arquivo: {name} ---\n{content}")
        self.input_box.see("end")
        self._update_count()
        self.set_status(f"Conteúdo de {name} carregado para revisão. Ainda não foi enviado nem salvo.", "ok")

    # ----- ações ---------------------------------------------------------------

    def refresh_actions(self) -> None:
        mode = self.action_filter.get()
        priority_order = {"alta": 0, "média": 1, "baixa": 2}
        rows, due_count = [], 0
        for action in reversed(self.state["acoes"]):
            status = action.get("status", "a fazer")
            due = llm_action_due(action)
            due_count += bool(due)
            if (mode == "Abertas" and status not in ("a fazer", "em andamento")) or \
               (mode == "Atrasadas" and not due) or \
               (mode == "Concluídas" and status != "concluída") or \
               (mode == "Canceladas" and status != "cancelada"):
                continue
            title = action.get("texto", "")
            if action.get("resultado_esperado"):
                title += f" — Esperado: {action['resultado_esperado']}"
            title = " ".join(title.split())
            review = action.get("revisar_em") or action.get("prazo", "")
            tags = ["atrasada"] if due else ["inativa"] if status in ("concluída", "cancelada") \
                else ["andamento"] if status == "em andamento" else []
            action_id = action.get("id", "")
            rows.append((action_id or str(id(action)),
                         (action_id, action.get("prioridade", "média"), title, br_date(review), status), tags,
                         (action_id, priority_order.get(action.get("prioridade", "média"), 1), title.casefold(), review, status)))
        self._fill_tree("actions", rows)
        self.action_count.configure(text=f"{len(rows)} de {len(self.state['acoes'])}")
        self.show_action_details()

    def _selected_action(self, quiet: bool = False) -> dict | None:
        iid = self._selected_iid(self.actions_tree)
        action = find_by_id(self.state["acoes"], self.actions_tree.set(iid, "id")) if iid else None
        if action is None and not quiet:
            self.set_status("Selecione uma ação na lista.", "warn")
        return action

    def show_action_details(self) -> None:
        action = self._selected_action(quiet=True)
        if not action:
            self._set_text(self.action_details, "Selecione uma ação para ver o detalhe e os resultados registrados.")
            return
        lines = [f"Ação: {action.get('texto', '')}",
                 f"Resultado esperado: {action.get('resultado_esperado') or 'não definido'}",
                 f"Prioridade: {action.get('prioridade', 'média')}  |  Status: {action.get('status', 'a fazer')}",
                 f"Prazo: {br_date(action.get('prazo')) or 'não definido'}  |  Rever em: {br_date(action.get('revisar_em')) or 'não definido'}",
                 "", "Resultados registrados:"]
        outcomes = action.get("resultados", [])
        lines += [f"• {br_date(item.get('data'))} — {item.get('texto', '')}" for item in outcomes] or \
                 ["Ainda não há resultados registrados."]
        self._set_text(self.action_details, "\n".join(lines))

    def set_action_status(self, status: str) -> None:
        action = self._selected_action()
        if not action:
            return
        action["status"] = status
        action["atualizada_em"] = now_iso()
        add_history(self.state, f"Ação {action.get('id')} atualizada para '{status}'.")
        save_state(self.state)
        self.refresh_actions()
        self.refresh_history()
        if status == "concluída" and not action.get("resultados") and messagebox.askyesno(
                APP_NAME, "Quer registrar agora o que aconteceu com esta ação?\n\nÉ o resultado que permite ao Javis analisar o efeito."):
            self.record_outcome(action)

    def _action_fields(self, action: dict | None = None) -> list[dict]:
        a = action or {}
        return [
            {"key": "texto", "label": "Ação", "kind": "text", "height": 3, "initial": a.get("texto", "")},
            {"key": "resultado_esperado", "label": "O que você espera que aconteça?", "kind": "line",
             "initial": a.get("resultado_esperado", "")},
            {"key": "prazo", "label": "Prazo", "kind": "date", "initial": a.get("prazo", "")},
            {"key": "revisar_em", "label": "Rever o resultado em", "kind": "date", "initial": a.get("revisar_em", ""),
             "hint": "Nesta data o Javis destaca a ação para você registrar o que aconteceu."},
            {"key": "prioridade", "label": "Prioridade", "kind": "choice", "values": PRIORITIES,
             "initial": a.get("prioridade", "média")},
        ]

    def new_action(self) -> None:
        values = self._ask("Nova ação", self._action_fields(), "Salvar ação", required=("texto",))
        if not values:
            return
        item = {"id": next_id("A", self.state["acoes"]), "data": now_iso(), **values,
                "status": "a fazer", "origem": "interface do Javis", "resultados": []}
        self.state["acoes"].append(item)
        add_history(self.state, f"Ação {item['id']} registrada.")
        save_state(self.state)
        self.show_page("actions")
        self.refresh_actions()
        self.refresh_history()
        self._select_row(self.actions_tree, item["id"])

    def edit_action(self) -> None:
        action = self._selected_action()
        if not action:
            return
        values = self._ask(f"Editar ação {action.get('id')}", self._action_fields(action), "Salvar alterações",
                           required=("texto",))
        if not values:
            return
        action.update(values)
        action["atualizada_em"] = now_iso()
        add_history(self.state, f"Ação {action['id']} editada.")
        save_state(self.state)
        self.refresh_actions()
        self.refresh_history()

    def record_outcome(self, action: dict | None = None) -> None:
        action = action if isinstance(action, dict) else self._selected_action()
        if not action:
            return
        summary = " ".join(str(action.get("texto", "")).split())
        fields = [
            {"key": "texto", "label": f"O que aconteceu após: {summary[:140]}", "kind": "text", "height": 6},
            {"key": "quando", "label": "Quando aconteceu", "kind": "date", "initial": date.today().isoformat()},
            {"key": "revisar_em", "label": "Rever novamente em", "kind": "date", "initial": ""},
        ]
        values = self._ask(f"Resultado de {action.get('id')}", fields, "Salvar resultado", required=("texto",))
        if not values:
            return
        action.setdefault("resultados", []).append({"data": values["quando"] or date.today().isoformat(),
                                                    "registrado_em": now_iso(), "texto": values["texto"]})
        if values["revisar_em"]:
            action["revisar_em"] = values["revisar_em"]
        action["ultima_revisao"] = now_iso()
        add_history(self.state, f"Resultado registrado para a ação {action.get('id')}.")
        save_state(self.state)
        self.refresh_actions()
        self.refresh_history()
        self._select_row(self.actions_tree, action.get("id", ""))

    def analyze_action(self) -> None:
        action = self._selected_action()
        if not action:
            return
        if not action.get("resultados"):
            self.set_status("Registre primeiro o resultado observado. Depois o Javis poderá compará-lo ao que era esperado.", "warn")
            return
        prompt = ("Analise o efeito observado desta ação. Compare resultado esperado e observado, indique o que pode ou não ser "
                  "atribuído à ação, o que ainda falta acompanhar e sugira próximos passos.\n\n"
                  + json.dumps(action, ensure_ascii=False, indent=2))
        self.analyze(prompt)

    def _ask(self, title: str, fields: list[dict], ok_text: str = "Salvar", intro: str = "", required: tuple = ()) -> dict | None:
        dialog = FormDialog(self, title, fields, ok_text, intro, required)
        self.root.wait_window(dialog)
        return dialog.result

    # ----- decisões e plano ----------------------------------------------------

    def refresh_decisions(self) -> None:
        mode = self.decision_filter.get()
        rows = []
        for decision in reversed(self.state["decisoes"]):
            status = decision.get("status", "vigente")
            if (mode == "Vigentes" and status != "vigente") or (mode == "Substituídas" and status == "vigente"):
                continue
            decision_id = decision.get("id", "")
            text = " ".join(str(decision.get("texto", "")).split())
            rows.append((decision_id or str(id(decision)), (decision_id, br_date(decision.get("data")), text, status),
                         [] if status == "vigente" else ["inativa"],
                         (decision_id, decision.get("data", ""), text.casefold(), status)))
        self._fill_tree("decisions", rows)
        self.show_decision_details()

    def _selected_decision(self) -> dict | None:
        iid = self._selected_iid(self.decisions_tree)
        return find_by_id(self.state["decisoes"], self.decisions_tree.set(iid, "id")) if iid else None

    def show_decision_details(self) -> None:
        decision = self._selected_decision()
        if not decision:
            self._set_text(self.decision_details, "Selecione uma decisão para ver o motivo e o status.")
            return
        text = f"{decision.get('texto', '')}\n\nMotivo: {decision.get('motivo') or 'não informado'}\nStatus: {decision.get('status', 'vigente')}"
        if decision.get("substituida_em"):
            text += f" (desde {br_date(decision['substituida_em'])})"
        self._set_text(self.decision_details, text)

    def new_decision(self) -> None:
        values = self._ask("Registrar decisão", [
            {"key": "texto", "label": "Qual decisão você confirmou?", "kind": "text", "height": 3},
            {"key": "motivo", "label": "Motivo ou contexto (opcional)", "kind": "text", "height": 3},
        ], "Registrar decisão", required=("texto",))
        if not values:
            return
        item = {"id": next_id("D", self.state["decisoes"]), "data": now_iso(), "texto": values["texto"],
                "motivo": values["motivo"], "status": "vigente", "substitui": None}
        self.state["decisoes"].append(item)
        add_history(self.state, f"Decisão {item['id']} confirmada.")
        save_state(self.state)
        self.show_page("decisions")
        self.refresh_decisions()
        self.refresh_history()
        self._select_row(self.decisions_tree, item["id"])
        self.sync_decisions_to_plan()

    def supersede_decision(self) -> None:
        item = self._selected_decision()
        if not item:
            self.set_status("Selecione uma decisão.", "warn")
            return
        if item.get("status") != "vigente":
            self.set_status("Esta decisão já está marcada como substituída.", "info")
            return
        if not messagebox.askyesno(APP_NAME, f"Marcar a decisão {item.get('id')} como substituída?"):
            return
        item["status"] = "substituída"
        item["substituida_em"] = now_iso()
        add_history(self.state, f"Decisão {item.get('id')} marcada como substituída.")
        save_state(self.state)
        self.refresh_decisions()
        self.refresh_history()
        self.sync_decisions_to_plan()

    def sync_decisions_to_plan(self) -> None:
        start_marker, end_marker = "<!-- JAVIS:DECISOES:INICIO -->", "<!-- JAVIS:DECISOES:FIM -->"
        decisions = [
            f"- **{d.get('id', '')}** — {d.get('texto', '')}  \n  Status: {d.get('status', 'vigente')} · Registrada: {d.get('data', '')[:10]}"
            + (f"  \n  Motivo: {d.get('motivo')}" if d.get("motivo") else "")
            for d in self.state["decisoes"]
        ] or ["- Nenhuma decisão registrada."]
        block = f"{start_marker}\n## Decisões\n\n" + "\n".join(decisions) + f"\n\n{end_marker}"
        current = self.plan_box.get("1.0", "end").rstrip()
        if start_marker in current and end_marker in current:
            before, rest = current.split(start_marker, 1)
            _, after = rest.split(end_marker, 1)
            updated = before.rstrip() + "\n\n" + block + after
        else:
            updated = current + "\n\n" + block
        self._replace_plan_text(updated + "\n")
        self.save_plan(confirm=False)

    def _replace_plan_text(self, text: str) -> None:
        self.plan_box.delete("1.0", "end")
        self.plan_box.insert("1.0", text)

    def save_plan(self, confirm: bool = True) -> None:
        content = self.plan_box.get("1.0", "end").strip() + "\n"
        if not content.strip():
            self.set_status("O plano está vazio. Escreva o conteúdo antes de salvar.", "warn")
            return
        previous = read_text_safe(PLAN_FILE) if PLAN_FILE.exists() else ""
        changed = previous != content
        if changed:
            if previous:
                backup_plan(previous)
            atomic_write(PLAN_FILE, content)
        self.state["plano"] = content
        add_history(self.state, "Plano Bismarck atualizado." if changed else "Plano Bismarck conferido; sem alterações.")
        save_state(self.state)
        self.plan_box.edit_modified(False)
        self.dirty_label.configure(text="")
        if confirm:
            self.set_status("Plano salvo." if changed else "Plano sem alterações desde a última gravação.", "ok")
            if changed:
                self.toast("Plano salvo · versão anterior guardada", "ok")
        self.refresh_history()

    def reload_plan(self) -> None:
        if self.plan_box.edit_modified() and not messagebox.askyesno(
                APP_NAME, "Descartar as alterações não salvas e recarregar o plano do disco?"):
            return
        if not PLAN_FILE.exists():
            self.set_status("O arquivo do plano ainda não existe no disco.", "warn")
            return
        self._replace_plan_text(read_text_safe(PLAN_FILE))
        self.plan_box.edit_modified(False)
        self.dirty_label.configure(text="")
        self.set_status("Plano recarregado do disco.", "ok")

    def show_plan_versions(self) -> None:
        versions = sorted(BACKUP_DIR.glob("Plano_Bismarck_*.md"), reverse=True)[:50] if BACKUP_DIR.exists() else []
        if not versions:
            self.set_status("Ainda não há versões anteriores. Elas são criadas quando você salva uma alteração.", "warn")
            return
        # Rótulo único por arquivo: tamanho + mtime podem coincidir.
        labels = {}
        for path in versions:
            stamp_txt = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            label = f"{stamp_txt} — {max(1, path.stat().st_size // 1024)} KB — {path.name[-12:]}"
            while label in labels:
                label += " "
            labels[label] = path
        values = self._ask("Versões anteriores do plano",
                           [{"key": "versao", "label": "Escolha uma versão", "kind": "choice", "values": list(labels)}],
                           "Carregar no editor",
                           intro="A versão escolhida é carregada no editor, mas só substitui o plano atual quando você clicar em “Salvar plano”. Dá para desfazer com Ctrl+Z.")
        if not values:
            return
        self._replace_plan_text(read_text_safe(labels[values["versao"]]))
        self.show_page("plan")
        self.set_status("Versão carregada no editor. Revise e salve para aplicar.", "warn")

    # ----- histórico -----------------------------------------------------------

    def refresh_history(self) -> None:
        rows = []
        for index, entry in enumerate(self.state["historico"][-400:]):
            text = entry.get("evento", "")
            rows.append((f"E-{index}", (br_datetime(entry.get("data")), "Evento", text), [],
                         (entry.get("data", ""), "evento", text.casefold())))
        for index, entry in enumerate(self.state["analises"][-100:]):
            summary = " ".join(str(entry.get("pergunta", "revisão do plano")).split())[:140]
            rows.append((entry.get("id") or f"AN-x{index}", (br_datetime(entry.get("data")), "Análise", summary),
                         ["andamento"], (entry.get("data", ""), "análise", summary.casefold())))
        rows.sort(key=lambda r: r[3][0], reverse=True)
        self._fill_tree("history", rows)
        self.show_history_detail()

    def _selected_analysis(self) -> dict | None:
        iid = self._selected_iid(self.history_tree)
        return find_by_id(self.state["analises"], iid) if iid else None

    def show_history_detail(self) -> None:
        iid = self._selected_iid(self.history_tree)
        if not iid:
            self._set_text(self.history_detail, "Selecione uma linha. Para análises, a resposta completa aparece aqui.")
            return
        analysis = find_by_id(self.state["analises"], iid)
        if analysis:
            self._set_text(self.history_detail, f"{br_datetime(analysis.get('data'))} · {iid}\n\nPEDIDO\n{analysis.get('pergunta', '')}\n\nRESPOSTA\n{analysis.get('resposta', '')}")
        else:
            self._set_text(self.history_detail, " ".join(str(v) for v in self.history_tree.item(iid, "values")))

    def reopen_analysis(self) -> None:
        analysis = self._selected_analysis()
        if not analysis:
            self.set_status("Selecione uma linha do tipo Análise.", "warn")
            return
        self.analysis_result = analysis.get("resposta", "")
        self.plan_proposal = llm.extract_proposal(self.analysis_result)
        self.current_note_id = None
        self.current_relation_id = None
        self.relation_frame.grid_remove()
        self._set_analysis(self.analysis_result)
        self._update_buttons()
        self.show_page("capture")
        self.set_status(f"Análise {analysis.get('id')} reaberta.", "ok")

    def open_ref(self, ref: str) -> None:
        prefix = ref.split("-")[0]
        found = False
        if prefix == "N":
            self.show_page("records")
            self.note_search.set("")
            self.refresh_notes()
            found = self._select_row(self.notes_tree, ref)
        elif prefix == "A":
            self.show_page("actions")
            self.action_filter.set("Todas")
            self.refresh_actions()
            found = self._select_row(self.actions_tree, ref)
        elif prefix == "D":
            self.show_page("decisions")
            self.decision_filter.set("Todas")
            self.refresh_decisions()
            found = self._select_row(self.decisions_tree, ref)
        elif prefix == "AN":
            self.show_page("history")
            found = self._select_row(self.history_tree, ref)
        if not found:
            self.set_status(f"Não encontrei {ref} nos registros.", "warn")

    # ----- análise -------------------------------------------------------------

    def current_context(self, note_id: str | None = None, deep: bool = False):
        from .config import CTX_DEEP, CTX_QUICK
        from .llm import SYSTEM_DEEP, SYSTEM_QUICK
        system = SYSTEM_DEEP if deep else SYSTEM_QUICK
        ctx = CTX_DEEP if deep else CTX_QUICK
        predict = 900 if deep else 300
        budget = llm.ContextBudget(ctx, predict, system)
        context = llm.build_context(self.state, self.plan_box.get("1.0", "end").strip(), note_id, deep, budget)
        return context, budget

    def analyze(self, prompt_override: str | None = None, *, deep: bool = False, automatic: bool = False,
                note_id: str | None = None) -> None:
        if self.busy:
            return
        if self.warming_model:
            self.set_status("Preparando o modelo local para responder mais rápido…")
            return
        if not self.ollama_ready:
            self.set_status("A IA local ainda não está pronta. Abra o Ollama e confirme que há um modelo instalado.", "warn")
            self.check_ollama()
            return
        typed = self.input_box.get("1.0", "end").strip()
        user_text = prompt_override if prompt_override is not None else typed
        if not user_text:
            user_text = "Revise o estado atual do Plano Bismarck. Identifique mudanças relevantes, riscos e próximos passos."
        if len(user_text) > 50000:
            self.set_status("Conteúdo muito longo para análise; será considerado um resumo do pedido.", "warn")
            user_text = user_text[:50000]
        if not automatic and not self._ensure_local_consent():
            return
        if prompt_override is None and typed:
            saved = self._store_note(typed)
            note_id = saved.get("id")
            self.input_box.delete("1.0", "end")
            self._update_count()
            user_text = f"Analise o registro {note_id} em foco e compare com o histórico recente."
        if not automatic:
            self.show_page("capture")
        self.current_note_id = note_id
        self.current_relation_id = None
        self.relation_frame.grid_remove()
        self.job_id += 1
        self.cancel_event = threading.Event()
        self.busy = True
        self.plan_proposal = ""
        self.streaming_started = False
        self.analysis_started = time.monotonic()
        model_name = self.active_model if deep else self.quick_model
        self.current_model = model_name
        self.analysis_result = ""
        self._set_analysis(f"Conectando ao Javis local · {model_name}…", muted=True)
        self.set_status(f"Preparando análise {'aprofundada' if deep else 'rápida'}… 00:00  (Esc para parar)")
        self._update_buttons()
        self.analysis_timer_id = self.root.after(1000, self._tick_analysis_timer)

        context, budget = self.current_context(note_id=note_id, deep=deep)
        note = f"Analise o registro {note_id or 'geral'} em foco e compare com o plano, as decisões, ações e resultados anteriores."
        payload = {"id": note_id, "texto": user_text if prompt_override is not None else note}
        if prompt_override is not None:
            payload["texto"] = user_text
        context_json = llm.compact_json(context)
        if budget.dropped:
            self.set_status(budget.summary(), "warn")
        threading.Thread(target=self._analysis_worker,
                         args=(self.job_id, self.cancel_event, payload, context_json, model_name, deep),
                         daemon=True).start()

    def stop_analysis(self) -> None:
        if not self.busy:
            return
        self.cancel_event.set()
        self.job_id += 1  # respostas atrasadas dessa tarefa serão ignoradas
        self.busy = False
        if self.analysis_timer_id is not None:
            self.root.after_cancel(self.analysis_timer_id)
            self.analysis_timer_id = None
        self.auto_queue.clear()
        for note in self.state["notas"]:
            note.pop("analise_automatica_pendente", None)
        save_state(self.state)
        if not self.streaming_started:
            self._set_analysis("Análise interrompida.", muted=True)
        self.set_status("Análise interrompida. Revisões automáticas pendentes foram descartadas.", "warn")
        self._update_buttons()

    def _tick_analysis_timer(self) -> None:
        if not self.busy:
            return
        elapsed = int(time.monotonic() - self.analysis_started)
        self.set_status(f"Javis está respondendo localmente… {elapsed // 60:02d}:{elapsed % 60:02d}  (Esc para parar)")
        self.analysis_timer_id = self.root.after(1000, self._tick_analysis_timer)

    def _append_stream_chunk(self, chunk: str) -> None:
        box = self.analysis_box
        box.configure(state="normal")
        if not self.streaming_started:
            box.delete("1.0", "end")
            self.streaming_started = True
        box.insert("end", chunk)
        box.see("end")
        box.configure(state="disabled")

    def _analysis_worker(self, job: int, cancel: threading.Event, payload: dict, context_json: str,
                         model_name: str, deep: bool) -> None:
        def put(event) -> None:
            self.events.put((event[0], job, event[1]))
        llm.stream_chat(model_name, payload, context_json, deep, cancel, put)

    def _poll_events(self) -> None:
        chunks: list[str] = []
        try:
            while True:
                kind, job, payload = self.events.get_nowait()
                if kind == "chunk":
                    if job == self.job_id:
                        chunks.append(payload)
                    continue
                if chunks:
                    self._append_stream_chunk("".join(chunks))
                    chunks = []
                try:
                    self._handle_event(kind, job, payload)
                except Exception:  # noqa: BLE001
                    log.exception("Falha ao tratar evento %s", kind)
        except queue.Empty:
            pass
        if chunks:
            self._append_stream_chunk("".join(chunks))
        self.root.after(40, self._poll_events)

    def _handle_event(self, kind: str, job: int | None, payload) -> None:
        if kind == "done":
            if job == self.job_id:
                self._analysis_done(*payload)
        elif kind == "error":
            if job == self.job_id:
                self._analysis_done("", "", payload)
        elif kind == "ollama":
            self._apply_ollama_status(*payload)
        elif kind == "preload":
            self._finish_model_preload(*payload)
        elif kind == "imported":
            self._finish_import(*payload)

    def _analysis_done(self, prompt: str, result: str, error: str | None) -> None:
        self.busy = False
        if self.analysis_timer_id is not None:
            self.root.after_cancel(self.analysis_timer_id)
            self.analysis_timer_id = None
        if error:
            self._set_analysis(error)
            self.set_status("A análise não terminou. Confira a conexão local do Ollama e tente novamente.", "err")
            self._update_buttons()
            if self.auto_queue:
                self.root.after(400, self._start_next_auto_review)
            return
        self.analysis_result = result
        self.plan_proposal = llm.extract_proposal(result)
        self._set_analysis(result)
        self._update_buttons()
        item = {"id": next_id("AN", self.state["analises"]), "data": now_iso(), "pergunta": prompt[:3000], "resposta": result}
        self.state["analises"].append(item)
        current_note = find_by_id(self.state["notas"], self.current_note_id)
        if current_note:
            current_note["analisada"] = True
            current_note["analise_automatica_pendente"] = False
        add_history(self.state, "Análise local concluída.")
        save_state(self.state)
        self.refresh_history()
        available = {r.get("id") for key in ("notas", "acoes", "decisoes")
                     for r in self.state.get(key, []) if r.get("id")}
        handled = {(l.get("evento_id"), l.get("relacionado_a")) for l in self.state.get("relacoes", [])}
        related_id = llm.extract_relation_candidate(result, self.current_note_id, available, handled)
        if related_id:
            self.current_relation_id = related_id
            self.relation_text.configure(text=f"Possível relação: o registro {self.current_note_id} pode se conectar a {related_id}. Confirme para atualizar o histórico; isso ainda não prova causa.")
            self.relation_frame.grid()
            self.set_status("Javis encontrou uma relação possível e aguarda sua confirmação.", "warn")
        else:
            self.set_status(f"Análise concluída com {self.current_model}. Revise antes de aprovar qualquer atualização.", "ok")
            if self.auto_queue:
                self.root.after(400, self._start_next_auto_review)

    def confirm_relation(self) -> None:
        note = find_by_id(self.state["notas"], self.current_note_id)
        target_id = self.current_relation_id
        if not note or not target_id:
            self.relation_frame.grid_remove()
            return
        rationale = llm.extract_relation_section(self.analysis_result)
        relation = {"evento_id": note["id"], "relacionado_a": target_id, "status": "confirmada", "data": now_iso(),
                    "justificativa": rationale,
                    "analise_id": self.state["analises"][-1].get("id") if self.state["analises"] else ""}
        self.state.setdefault("relacoes", []).append(relation)
        target_action = find_by_id(self.state["acoes"], target_id)
        if target_action:
            target_action.setdefault("resultados", []).append({
                "data": note.get("data", "")[:10], "registrado_em": now_iso(),
                "texto": f"Relato relacionado por você ({note['id']}): {note.get('texto', '')}\nSinal considerado: {rationale}",
                "origem_registro": note["id"],
            })
            add_history(self.state, f"Registro {note['id']} vinculado à ação {target_id}; resultado acrescentado à ação.")
        else:
            note.setdefault("vinculos", []).append(target_id)
            add_history(self.state, f"Acontecimento {note['id']} vinculado a {target_id} por confirmação da pessoa.")
        save_state(self.state)
        self.refresh_notes()
        self.refresh_actions()
        self.refresh_history()
        self.relation_frame.grid_remove()
        self.set_status(f"Vínculo confirmado: {note['id']} ↔ {target_id}.", "ok")
        self.current_relation_id = None
        if self.auto_queue:
            self.root.after(300, self._start_next_auto_review)

    def ignore_relation(self) -> None:
        if self.current_note_id and self.current_relation_id:
            self.state.setdefault("relacoes", []).append({"evento_id": self.current_note_id,
                                                         "relacionado_a": self.current_relation_id,
                                                         "status": "ignorada", "data": now_iso()})
            save_state(self.state)
        self.relation_frame.grid_remove()
        self.set_status("Sugestão ignorada; nenhuma ação ou acontecimento foi alterado.")
        self.current_relation_id = None
        if self.auto_queue:
            self.root.after(300, self._start_next_auto_review)

    def _set_analysis(self, text: str, muted: bool = False) -> None:
        box = self.analysis_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        if muted:
            box.insert("1.0", text, "muted")
        else:
            lines = text.split("\n")
            for number, line in enumerate(lines, start=1):
                box.insert("end", line + ("\n" if number < len(lines) else ""), "h" if llm.HEADING_RE.match(line) else ())
                for match in llm.REF_RE.finditer(line):
                    box.tag_add("ref", f"{number}.{match.start()}", f"{number}.{match.end()}")
        box.configure(state="disabled")

    def _on_analysis_click(self, event) -> None:
        box = self.analysis_box
        index = box.index(f"@{event.x},{event.y}")
        if "ref" in box.tag_names(index):
            span = box.tag_prevrange("ref", f"{index}+1c")
            if span:
                self.open_ref(box.get(*span))

    def copy_analysis(self) -> None:
        if self.analysis_result:
            self._copy(self.analysis_result, "Texto da análise")
        else:
            self.set_status("Ainda não há análise para copiar.", "warn")

    def approve_plan_update(self) -> None:
        proposal = self.plan_proposal.strip()
        if not proposal:
            return
        values = self._ask("Aprovar atualização do plano",
                           [{"key": "texto", "label": "Texto que será acrescentado ao plano", "kind": "text",
                             "height": 8, "initial": proposal}],
                           "Aprovar e acrescentar",
                           intro="Revise e, se quiser, edite a sugestão do Javis. Uma cópia da versão anterior do plano será guardada.",
                           required=("texto",))
        if not values:
            return
        current = self.plan_box.get("1.0", "end").rstrip()
        self._replace_plan_text(f"{current}\n\n## Atualização aprovada — {date.today().isoformat()}\n\n{values['texto']}\n")
        self.save_plan(confirm=False)
        self.plan_proposal = ""
        self._update_buttons()
        self.show_page("plan")
        self.set_status("Atualização aprovada e acrescentada ao plano.", "ok")

    # ----- Ollama --------------------------------------------------------------

    def check_ollama(self) -> None:
        if self.recheck_id is not None:
            self.root.after_cancel(self.recheck_id)
            self.recheck_id = None
        preferred = self.state.get("preferred_model")

        def worker() -> None:
            quick = None
            try:
                with urllib.request.urlopen(urllib.request.Request(OLLAMA_TAGS_URL, method="GET"), timeout=3) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                models = [m.get("name", "") for m in payload.get("models", [])]
                priority = ("qwen3.5:4b", MODEL, FALLBACK_MODEL, "qwen3:8b", "qwen3.5:9b", "qwen3.5:2b", QUICK_MODEL)
                selected = preferred if preferred in models else next(
                    (c for base in priority for c in models if c == base or c.startswith(base + "-")), None)
                selected = selected or next((name for name in models if name), None)
                quick = next((c for base in (QUICK_MODEL, "qwen3.5:2b", "qwen3.5:0.8b", "qwen3:0.6b")
                              for c in models if c == base or c.startswith(base + "-")), None)
                ready = selected is not None
                if ready:
                    msg, kind = f"IA pronta\nrápida: {quick or selected}\naprofundada: {selected}", "ok"
                else:
                    msg, kind = "Ollama aberto, mas sem modelos.\nBaixe um: ollama pull qwen3:1.7b", "warn"
            except Exception:  # noqa: BLE001 - Ollama fechado é um estado normal
                ready, selected, models = False, self.active_model, []
                msg, kind = "IA local desconectada\nAbra o Ollama (F5 para tentar de novo)", "warn"
            self.events.put(("ollama", None, (ready, selected, msg, kind, models, quick)))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_ollama_status(self, ready: bool, model_name: str, message: str, kind: str, models: list[str],
                             quick: str | None) -> None:
        self.ollama_ready = ready
        self.available_models = models
        self.detected_quick_model = quick
        self.model_combo.configure(values=models, state="readonly" if models else "disabled")
        if ready:
            self.active_model = model_name
            self.model_var.set(model_name)
            self.quick_model = quick or model_name
        else:
            self.model_var.set("")
            self.recheck_id = self.root.after(20000, self.check_ollama)  # percebe sozinho quando o Ollama abrir
        self.set_ai_status(message, kind)
        if ready and any(tag in self.quick_model.lower() for tag in ("1.7b", "2b", "0.8b", "0.6b")) \
                and self.preloaded_quick_model != self.quick_model and not self.preload_in_progress:
            self._start_model_preload(self.quick_model)
        self._update_buttons()
        if ready and self.auto_queue and not self.warming_model:
            self.root.after(250, self._start_next_auto_review)

    def _start_model_preload(self, model_name: str) -> None:
        self.preload_in_progress = True
        self.warming_model = True
        self.set_ai_status(f"Preparando IA local\n{model_name}…", "muted")
        self.set_status("Carregando o modelo para que as próximas análises comecem mais rápido…")
        self._update_buttons()

        def worker() -> None:
            error = None
            try:
                body = json.dumps({"model": model_name, "keep_alive": "15m", "stream": False}).encode("utf-8")
                request = urllib.request.Request(OLLAMA_URL, data=body,
                                                 headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=240) as response:
                    response.read()
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            self.events.put(("preload", None, (model_name, error)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_model_preload(self, model_name: str, error: str | None) -> None:
        self.preload_in_progress = False
        self.warming_model = False
        if error is None:
            self.preloaded_quick_model = model_name
            self.set_ai_status(f"IA pronta\nrápida: {self.quick_model}\naprofundada: {self.active_model}", "ok")
            self.set_status("Modelo carregado. As análises vão começar mais rápido.", "ok")
        else:
            self.set_ai_status(f"IA local conectada\no primeiro carregamento pode demorar ({self.quick_model})", "warn")
        self._update_buttons()
        if self.auto_queue and self.ollama_ready:
            self.root.after(250, self._start_next_auto_review)

    def on_model_selected(self, _event=None) -> None:
        selected = self.model_var.get().strip()
        if not selected or selected not in self.available_models:
            return
        self.active_model = selected
        self.state["preferred_model"] = selected
        save_state(self.state)
        self.quick_model = self.detected_quick_model or selected
        self.set_ai_status(f"IA pronta\nrápida: {self.quick_model}\naprofundada: {selected}", "ok")

    # ----- arquivos, ajuda e saída ---------------------------------------------

    @staticmethod
    def _open_path(path: Path) -> None:
        if hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])

    def open_data_folder(self) -> None:
        try:
            self._open_path(DATA_DIR)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Não consegui abrir a pasta de dados.\n\n{exc}")

    def open_log(self) -> None:
        if not LOG_FILE.exists():
            self.set_status("Nenhum erro foi registrado até agora.", "info")
            return
        try:
            self._open_path(LOG_FILE)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Não consegui abrir o log.\n\n{exc}")

    def export_markdown(self) -> None:
        path = filedialog.asksaveasfilename(title="Exportar em Markdown", defaultextension=".md",
                                           initialfile=f"Javis_exportacao_{date.today():%Y%m%d}.md",
                                           filetypes=[("Markdown", "*.md")])
        if not path:
            return
        s = self.state
        out = [f"# {s.get('projeto', 'Plano Bismarck')} — exportação de {stamp()}", "", "## Plano", "",
               self.plan_box.get("1.0", "end").strip(), "", "## Decisões", ""]
        out += [f"- **{d.get('id')}** ({d.get('status', 'vigente')}, {br_date(d.get('data'))}): {d.get('texto')}"
                + (f" — motivo: {d['motivo']}" if d.get("motivo") else "") for d in s["decisoes"]] or ["- Nenhuma."]
        out += ["", "## Ações", ""]
        for a in s["acoes"]:
            out.append(f"- **{a.get('id')}** [{a.get('status')}] {a.get('texto')} — esperado: "
                       f"{a.get('resultado_esperado') or '—'} — rever em: {br_date(a.get('revisar_em')) or '—'}")
            out += [f"  - {br_date(r.get('data'))}: {' '.join(str(r.get('texto', '')).split())}" for r in a.get("resultados", [])]
        out += ["", "## Registros", ""]
        for n in s["notas"]:
            out += [f"### {n.get('id')} — {br_datetime(n.get('data'))}", "", str(n.get("texto", "")), ""]
        try:
            atomic_write(Path(path), "\n".join(out) + "\n")
            self.set_status(f"Exportado para {path}. O arquivo contém seus dados privados.", "ok")
            self.toast("Exportação concluída", "ok")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não consegui salvar o arquivo.\n\n{exc}")

    def backup_zip(self) -> None:
        path = filedialog.asksaveasfilename(title="Backup dos dados do Javis", defaultextension=".zip",
                                           initialfile=f"Javis_backup_{datetime.now():%Y%m%d_%H%M}.zip",
                                           filetypes=[("Arquivo ZIP", "*.zip")])
        if not path:
            return
        try:
            save_state(self.state)
            target = Path(path).resolve()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in DATA_DIR.rglob("*"):
                    if file.is_file() and file.suffix != ".tmp" and file.resolve() != target:
                        zf.write(file, file.relative_to(DATA_DIR))
            self.set_status(f"Backup salvo em {path}. Ele contém seus dados privados; guarde em local seguro.", "ok")
            self.toast("Backup criado", "ok")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não consegui criar o backup.\n\n{exc}")

    def show_shortcuts(self) -> None:
        messagebox.showinfo("Atalhos de teclado", "\n".join([
            "Ctrl+Enter — Guardar registro", "Ctrl+R — Analisar rápido", "Ctrl+Shift+R — Análise aprofundada",
            "Esc — Parar análise", "Ctrl+N — Novo registro", "Ctrl+O — Abrir arquivo", "Ctrl+S — Salvar plano",
            "Ctrl+F — Pesquisar registros", "Ctrl+1 … 6 — Trocar de seção", "Ctrl+T — Trocar de tema",
            "Ctrl++ / Ctrl+- / Ctrl+0 — Tamanho da fonte", "F5 — Reconectar ao Ollama / atualizar modelos",
            "Ctrl+Q — Sair", "", "Botão direito nas listas — menu de ações",
            "Clique no cabeçalho de uma coluna — ordenar", "Clique em N-001, A-002… na análise — abrir o item"]))

    def show_about(self) -> None:
        messagebox.showinfo("Sobre o Javis", f"{APP_NAME}\nVersão {APP_VERSION}\n\nDados privados: {DATA_DIR}\n"
                                             "IA: Ollama local\n\nVisual em vidro por composição própria (o Tk ignora o alfa de PNG).")

    def close(self) -> None:
        if self.plan_box.edit_modified():
            answer = messagebox.askyesnocancel(APP_NAME, "O plano tem alterações não salvas. Salvar antes de sair?")
            if answer is None:
                return
            if answer:
                self.save_plan(confirm=False)
        self.state["rascunho"] = self.input_box.get("1.0", "end").strip()
        self.state["janela"] = f"{self.root.winfo_width()}x{self.root.winfo_height()}"
        try:
            save_state(self.state)
        except OSError:
            log.exception("Falha ao salvar ao fechar")
        self.cancel_event.set()
        self.root.destroy()


class FormDialog(tk.Toplevel):
    """Diálogo modal declarativo. Campos: key, label, kind (line|text|date|choice), initial, values, hint."""

    def __init__(self, app: "JavisApp", title: str, fields: list[dict], ok_text: str = "Salvar",
                 intro: str = "", required: tuple = ()):
        super().__init__(app.root)
        self.app, self.fields, self.required = app, fields, required
        self.result: dict | None = None
        self.inputs: dict[str, tuple[str, object]] = {}
        self.title(title)
        self.transient(app.root)
        self.configure(background=getattr(app, "glass_surface", hexc(app.theme["bg"])))
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        if intro:
            ttk.Label(frame, text=intro, style="Sub.TLabel", wraplength=app.px(480), justify="left").pack(anchor="w", pady=(0, 10))
        first = None
        for spec in fields:
            kind = spec.get("kind", "line")
            ttk.Label(frame, text=spec["label"], style="Bold.TLabel").pack(anchor="w", pady=(6, 0))
            if kind == "text":
                widget = app.make_text(frame, height=spec.get("height", 4), font=app.f_base)
                widget.pack(fill="both", expand=True, pady=(3, 0))
                widget.insert("1.0", spec.get("initial", ""))
                self.inputs[spec["key"]] = (kind, widget)
            elif kind == "choice":
                var = tk.StringVar(value=spec.get("initial") or spec["values"][0])
                widget = ttk.Combobox(frame, textvariable=var, values=spec["values"], state="readonly")
                widget.pack(fill="x", pady=(3, 0))
                app.style_combo(widget)
                self.inputs[spec["key"]] = (kind, var)
            else:
                initial = spec.get("initial", "")
                if kind == "date" and initial:
                    initial = br_date(initial)
                var = tk.StringVar(value=initial)
                widget = ttk.Entry(frame, textvariable=var)
                widget.pack(fill="x", pady=(3, 0))
                widget.bind("<Return>", lambda _e: self._ok())
                self.inputs[spec["key"]] = (kind, var)
            first = first or widget
            hint = DATE_HINT if kind == "date" else spec.get("hint", "")
            if hint:
                ttk.Label(frame, text=hint, style="Sub.TLabel", wraplength=app.px(480), justify="left").pack(anchor="w", pady=(2, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text=ok_text, style="Action.TButton", command=self._ok).pack(side="right")
        ttk.Button(buttons, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._ok())
        self.update_idletasks()
        width = max(app.px(540), self.winfo_reqwidth())
        height = self.winfo_reqheight()
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - width) // 2)
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(width, height)
        self.grab_set()
        if first is not None:
            first.focus_set()

    def _ok(self) -> None:
        values: dict[str, str] = {}
        for spec in self.fields:
            kind, widget = self.inputs[spec["key"]]
            raw = widget.get("1.0", "end").strip() if kind == "text" else widget.get().strip()
            if kind == "date":
                try:
                    raw = parse_date(raw)
                except ValueError:
                    messagebox.showerror(APP_NAME, f"Data inválida em “{spec['label']}”.\n\n{DATE_HINT}", parent=self)
                    return
            if spec["key"] in self.required and not raw:
                messagebox.showinfo(APP_NAME, f"Preencha: {spec['label']}", parent=self)
                return
            values[spec["key"]] = raw
        self.result = values
        self.destroy()


def llm_action_due(action: dict) -> str | None:
    """Data já vencida que pede acompanhamento, ou None."""
    status = action.get("status")
    if status == "cancelada" or (status == "concluída" and action.get("resultados")):
        return None
    today = date.today()
    for key in ("revisar_em", "prazo"):
        value = action.get(key) or ""
        try:
            if value and date.fromisoformat(value[:10]) <= today:
                return value[:10]
        except ValueError:
            continue
    return None


def read_document(path: Path) -> str:
    import csv
    import xml.etree.ElementTree as ET
    import zipfile
    suffix = path.suffix.lower()
    if suffix == ".docx":
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        paragraphs = []
        for para in root.iter(ns + "p"):
            parts = []
            for node in para.iter():
                if node.tag == ns + "t":
                    parts.append(node.text or "")
                elif node.tag == ns + "tab":
                    parts.append("\t")
                elif node.tag in (ns + "br", ns + "cr"):
                    parts.append("\n")
            paragraphs.append("".join(parts))
        return "\n".join(paragraphs)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("Para abrir PDF, instale o leitor uma vez (no PowerShell: py -m pip install pypdf). "
                             "Arquivos TXT, MD, DOCX, CSV e JSON já podem ser abertos.") from exc
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            return "\n".join(" | ".join(row) for row in csv.reader(f))
    return read_text_safe(path)


def enable_dpi_awareness() -> None:
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def setup_logging() -> None:
    """pythonw não tem console: erros inesperados vão para javis.log."""
    import logging
    from logging.handlers import RotatingFileHandler
    from .config import DATA_DIR, LOG_FILE
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=256_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    except OSError:
        log.addHandler(logging.NullHandler())


def main() -> None:
    setup_logging()
    try:
        enable_dpi_awareness()
        root = tk.Tk()
        JavisApp(root)
        root.mainloop()
    except Exception as exc:  # noqa: BLE001
        log.exception("Javis não conseguiu iniciar")
        try:
            messagebox.showerror(APP_NAME, f"Javis não conseguiu iniciar.\n\n{exc}\n\nDetalhes em {LOG_FILE}")
        except Exception:  # noqa: BLE001
            pass
