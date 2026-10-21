"""Controles de vidro do Javis: botões, campos, combo, caixas, scrollbar.

O Tk não tem transparência por widget, então cada controle é um Canvas (ou um
Frame com um Canvas de fundo) que mostra uma imagem de vidro pré-renderizada,
com bordas suavizadas, e troca de imagem para animar o hover/foco. As imagens
ficam em cache, então a animação só reaproveita quadros já prontos.

As cores vêm de `SKIN`, atualizado por `set_skin()` a cada troca de tema; todos
os controles vivos se repintam sozinhos.
"""

from __future__ import annotations

import time
import tkinter as tk
import weakref

from . import glass
from .theme import darken, glass_surface, glass_well, hexc, is_light, lighten, mix


# --------------------------------------------------------------------------
# Aparência compartilhada
# --------------------------------------------------------------------------

class _Skin:
    scale = 1.0
    light = False
    f_base = f_bold = f_input = None

    def update(self, theme: dict, scale: float, f_base, f_bold, f_input) -> None:
        self.theme = theme
        self.scale = scale
        self.light = is_light(theme)
        self.flat = glass_surface(theme)
        self.well = glass_well(theme)
        self.text = theme["text"]
        self.muted = theme["muted"]
        self.accent = theme["accent"]
        self.accent_fg = theme["accent_fg"]
        self.banner = mix(self.flat, self.accent, 0.14)
        self.f_base, self.f_bold, self.f_input = f_base, f_bold, f_input


SKIN = _Skin()
_live: "weakref.WeakSet" = weakref.WeakSet()
_IMG: dict = {}


def px(value: float) -> int:
    return int(round(value * SKIN.scale))


def ground(name: str):
    return {"flat": SKIN.flat, "well": SKIN.well, "banner": SKIN.banner}.get(name, SKIN.flat)


def set_skin(theme: dict, scale: float, f_base, f_bold, f_input) -> None:
    """Troca o tema/fonte de todos os controles de vidro."""
    SKIN.update(theme, scale, f_base, f_bold, f_input)
    _IMG.clear()
    for widget in list(_live):
        try:
            widget.refresh()
        except tk.TclError:
            pass


def control_image(master, w: int, h: int, **kw):
    """PhotoImage de um controle, com cache. None se não houver numpy."""
    key = (int(w), int(h), tuple(sorted(kw.items())))
    img = _IMG.get(key)
    if img is not None:
        return img
    rgb = glass.render_control(w, h, **kw)
    if rgb is None:
        return None
    if len(_IMG) > 600:
        _IMG.clear()
    img = tk.PhotoImage(master=master, data=glass.to_ppm(int(w), int(h), rgb), format="PPM")
    _IMG[key] = img
    return img


def _put_shape(canvas: tk.Canvas, x: int, y: int, w: int, h: int, plain_fill, plain_outline, **kw) -> None:
    """Coloca (ou atualiza) a forma de vidro no fundo do canvas."""
    img = control_image(canvas, w, h, **kw)
    if img is not None:
        canvas._shape_img = img
        if getattr(canvas, "_shape_kind", None) == "img":
            canvas.itemconfigure("shape", image=img)
            canvas.coords("shape", x, y)
        else:
            canvas.delete("shape")
            canvas.create_image(x, y, anchor="nw", image=img, tags="shape")
            canvas._shape_kind = "img"
    else:  # sem numpy: retângulo simples
        canvas.delete("shape")
        canvas.create_rectangle(x, y, x + w - 1, y + h - 1, fill=hexc(plain_fill),
                                outline=hexc(plain_outline), tags="shape")
        canvas._shape_kind = "rect"
    canvas.tag_lower("shape")


def _strip_style_kw(kw: dict) -> None:
    for key in ("bg", "background", "fg", "foreground", "padding", "style", "font", "relief", "borderwidth"):
        kw.pop(key, None)


class _Fader:
    """Transições suaves: cada valor (hover, foco, marcado) caminha até o alvo."""

    def _tw_init(self, **names: float) -> None:
        self._tw = dict(names)
        self._tt = dict(names)
        self._fade_id = None

    def _tween(self, name: str, target: float) -> None:
        self._tt[name] = target
        if self._fade_id is None:
            self._fade_id = self.after(1, self._tw_step)

    def _tw_step(self) -> None:
        self._fade_id = None
        busy = False
        for key, target in self._tt.items():
            cur = self._tw[key]
            if abs(cur - target) > 0.01:
                cur = min(target, cur + 0.25) if target > cur else max(target, cur - 0.25)
                busy = True
            else:
                cur = target
            self._tw[key] = cur
        try:
            self._paint()
        except tk.TclError:
            return
        if busy:
            self._fade_id = self.after(16, self._tw_step)

    def _lv(self, name: str) -> float:
        return round(self._tw[name] * 4) / 4

    def destroy(self) -> None:  # noqa: D401
        if getattr(self, "_fade_id", None):
            try:
                self.after_cancel(self._fade_id)
            except tk.TclError:
                pass
        super().destroy()


# --------------------------------------------------------------------------
# Paletas de botão
# --------------------------------------------------------------------------

def _ghost_colors(level: float, pressed: bool, disabled: bool, focus: bool):
    f, a = SKIN.flat, SKIN.accent
    if SKIN.light:
        n = (lighten(f, 0.72), lighten(f, 0.46), darken(f, 0.11))
        h = (lighten(f, 0.92), lighten(f, 0.74), mix(darken(f, 0.11), a, 0.55))
        hl = 0.55 + 0.30 * level
    else:
        n = (lighten(f, 0.11), lighten(f, 0.05), lighten(f, 0.20))
        h = (lighten(f, 0.20), lighten(f, 0.11), mix(lighten(f, 0.34), a, 0.40))
        hl = 0.22 + 0.12 * level
    top, bot, bd = (mix(n[i], h[i], level) for i in range(3))
    text = mix(SKIN.muted, SKIN.text, level)
    glow, glow_a = a, 0.26 * level
    if disabled:
        top, bot, bd = mix(f, top, 0.45), mix(f, bot, 0.45), mix(f, bd, 0.45)
        text, glow_a, hl = mix(SKIN.muted, f, 0.45), 0.0, hl * 0.4
    elif pressed:
        top, bot = darken(top, 0.10), darken(bot, 0.10)
        glow_a = 0.0
    if focus and not disabled:
        bd, glow_a = a, max(glow_a, 0.45)
    return top, bot, bd, text, hl, glow, glow_a


def _action_colors(level: float, pressed: bool, disabled: bool, focus: bool):
    f, a = SKIN.flat, SKIN.accent
    n = (lighten(a, 0.10), darken(a, 0.12), lighten(a, 0.30))
    h = (lighten(a, 0.24), darken(a, 0.02), lighten(a, 0.50))
    top, bot, bd = (mix(n[i], h[i], level) for i in range(3))
    text = SKIN.accent_fg
    glow, glow_a, hl = a, 0.50 * level, 0.35
    if disabled:
        top, bot, bd = mix(f, a, 0.34), mix(f, a, 0.26), mix(f, a, 0.42)
        text, glow_a, hl = mix(SKIN.muted, f, 0.15), 0.0, 0.10
    elif pressed:
        top, bot = darken(top, 0.14), darken(bot, 0.14)
        glow_a = 0.0
    if focus and not disabled:
        bd, glow_a = lighten(a, 0.65), max(glow_a, 0.55)
    return top, bot, bd, text, hl, glow, glow_a


# --------------------------------------------------------------------------
# Botão
# --------------------------------------------------------------------------

class GlassButton(_Fader, tk.Canvas):
    """Botão de vidro com hover animado. Aceita a API básica do ttk.Button."""

    def __init__(self, parent, text: str = "", command=None, style: str = "Ghost.TButton",
                 state: str = "normal", ground: str = "flat", **kw) -> None:
        self._kind = "action" if str(style).startswith("Action") else "ghost"
        self._ground = ground
        self._label = text
        self._command = command
        self._menu = None
        self._disabled = state == "disabled"
        self._pressed = False
        self._focus = False
        self._last_press = 0.0
        self._cw = self._ch = 0
        self._txt_id = None
        self._tw_init(hover=0.0)
        tk.Canvas.__init__(self, parent, bd=0, highlightthickness=0, bg=hexc(ground_rgb(ground)),
                           takefocus=0 if self._disabled else 1,
                           cursor="" if self._disabled else "hand2")
        _live.add(self)
        self._measure()
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<space>", lambda _e: self.invoke())
        self.bind("<Return>", lambda _e: self.invoke())

    # --- tamanho e pintura ---------------------------------------------------
    def _font(self):
        return SKIN.f_bold if self._kind == "action" else SKIN.f_base

    def _display(self) -> str:
        return self._label + ("  ▾" if self._menu is not None else "")

    def _measure(self) -> None:
        font = self._font()
        width = font.measure(self._display()) + 2 * px(16) + 4
        height = font.metrics("linespace") + 2 * px(8) + 4
        tk.Canvas.configure(self, width=width, height=height)

    def _on_configure(self, event) -> None:
        self._cw, self._ch = event.width, event.height
        self._paint()

    def _paint(self) -> None:
        w, h = self._cw, self._ch
        if w < 8 or h < 8:
            return
        colors = (_action_colors if self._kind == "action" else _ghost_colors)(
            self._lv("hover"), self._pressed, self._disabled, self._focus)
        top, bot, bd, text, hl, glow, glow_a = colors
        _put_shape(self, 0, 0, w, h, top, bd, radius=min(px(12), (h - 4) // 2), top=top, bot=bot, border=bd,
                   bg=ground_rgb(self._ground), hl=hl, glow=glow, glow_a=round(glow_a, 2))
        y = h / 2 + (1 if self._pressed else 0)
        if self._txt_id is None:
            self._txt_id = self.create_text(w / 2, y, text=self._display(), font=self._font(), fill=hexc(text))
        else:
            self.coords(self._txt_id, w / 2, y)
            self.itemconfigure(self._txt_id, text=self._display(), font=self._font(), fill=hexc(text))

    def refresh(self) -> None:
        tk.Canvas.configure(self, bg=hexc(ground_rgb(self._ground)))
        self._shape_kind = None
        self._measure()
        self._paint()

    # --- eventos ---------------------------------------------------------------
    def _on_enter(self, _e) -> None:
        if not self._disabled:
            self._tween("hover", 1.0)

    def _on_leave(self, _e) -> None:
        self._pressed = False
        self._tween("hover", 0.0)
        self._paint()

    def _on_press(self, _e) -> None:
        if self._disabled:
            return
        self._pressed = True
        self._last_press = time.time()
        self.focus_set()
        self._paint()

    def _on_release(self, event) -> None:
        was = self._pressed
        self._pressed = False
        self._paint()
        if was and not self._disabled and 0 <= event.x <= self._cw and 0 <= event.y <= self._ch:
            self.invoke()

    def _on_focus_in(self, _e) -> None:
        self._focus = time.time() - self._last_press > 0.25  # anel só no foco por teclado
        self._paint()

    def _on_focus_out(self, _e) -> None:
        self._focus = False
        self._paint()

    # --- API parecida com ttk.Button --------------------------------------------
    def invoke(self):
        if self._disabled:
            return None
        if self._menu is not None:
            return self._post_menu()
        return self._command() if self._command else None

    def _post_menu(self) -> None:
        try:
            self._menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2)
        finally:
            self._menu.grab_release()

    def _set_disabled(self, flag: bool) -> None:
        self._disabled = flag
        tk.Canvas.configure(self, cursor="" if flag else "hand2", takefocus=0 if flag else 1)
        if flag:
            self._pressed = False
            self._tween("hover", 0.0)
        self._paint()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if "text" in kw:
            self._label = kw.pop("text")
            self._measure()
        if "command" in kw:
            self._command = kw.pop("command")
        if "menu" in kw:
            self._menu = kw.pop("menu")
            self._measure()
        if "state" in kw:
            self._set_disabled(kw.pop("state") == "disabled")
        if "ground" in kw:
            self._ground = kw.pop("ground")
            self.refresh()
        _strip_style_kw(kw)
        if kw:
            tk.Canvas.configure(self, **kw)
        self._paint()

    config = configure

    def cget(self, key):
        if key == "text":
            return self._label
        if key == "state":
            return "disabled" if self._disabled else "normal"
        if key == "command":
            return self._command
        return tk.Canvas.cget(self, key)

    def state(self, spec=None):
        if spec is None:
            return tuple(s for s, on in (("disabled", self._disabled), ("active", self._tt["hover"] > 0)) if on)
        for item in spec:
            name, neg = item.lstrip("!"), item.startswith("!")
            if name == "disabled":
                self._set_disabled(not neg)
            elif name == "active" and not self._disabled:
                self._tween("hover", 0.0 if neg else 1.0)
        return ()


class GlassMenubutton(GlassButton):
    """Botão que abre um menu (substitui ttk.Menubutton)."""

    def __init__(self, parent, text: str = "", menu=None, **kw) -> None:
        super().__init__(parent, text=text, **kw)
        if menu is not None:
            self.configure(menu=menu)


def ground_rgb(name: str):
    return ground(name)


# --------------------------------------------------------------------------
# Item do menu lateral
# --------------------------------------------------------------------------

class GlassNav(_Fader, tk.Canvas):
    def __init__(self, parent, text: str = "", command=None) -> None:
        self._label = text
        self._command = command
        self._active = False
        self._cw = self._ch = 0
        self._txt_id = None
        self._tw_init(hover=0.0, on=0.0)
        tk.Canvas.__init__(self, parent, bd=0, highlightthickness=0, bg=hexc(SKIN.flat), takefocus=1,
                           cursor="hand2", height=px(42))
        _live.add(self)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", lambda _e: self._tween("hover", 1.0))
        self.bind("<Leave>", lambda _e: self._tween("hover", 0.0))
        self.bind("<ButtonRelease-1>", lambda e: self._click(e))
        self.bind("<space>", lambda _e: self._click(None))
        self.bind("<Return>", lambda _e: self._click(None))

    def _click(self, event) -> None:
        if event is None or (0 <= event.x <= self._cw and 0 <= event.y <= self._ch):
            if self._command:
                self._command()

    def set_active(self, flag: bool) -> None:
        self._active = flag
        self._tween("on", 1.0 if flag else 0.0)

    def _on_configure(self, event) -> None:
        self._cw, self._ch = event.width, event.height
        self._paint()

    def _paint(self) -> None:
        w, h = self._cw, self._ch
        if w < 8 or h < 8:
            return
        hov, on = self._lv("hover"), self._lv("on")
        f, a = SKIN.flat, SKIN.accent
        if SKIN.light:
            g_top, g_bot, g_bd = lighten(f, 0.70), lighten(f, 0.50), darken(f, 0.08)
        else:
            g_top, g_bot, g_bd = lighten(f, 0.10), lighten(f, 0.05), lighten(f, 0.16)
        top = mix(mix(f, g_top, hov), lighten(a, 0.10), on)
        bot = mix(mix(f, g_bot, hov), darken(a, 0.12), on)
        bd = mix(mix(f, g_bd, hov), lighten(a, 0.30), on)
        if hov > 0 or on > 0:
            _put_shape(self, 0, 0, w, h, top, bd, radius=min(px(12), (h - 4) // 2), top=top, bot=bot, border=bd,
                       bg=f, hl=round(0.30 * max(hov, on), 2), glow=a, glow_a=round(0.40 * on, 2))
            self.itemconfigure("shape", state="normal")
        else:
            self.itemconfigure("shape", state="hidden")
        color = mix(mix(SKIN.muted, SKIN.text, hov), SKIN.accent_fg, on)
        font = SKIN.f_bold if self._active else SKIN.f_base
        if self._txt_id is None:
            self._txt_id = self.create_text(px(18), h / 2, anchor="w", text=self._label, font=font, fill=hexc(color))
        else:
            self.coords(self._txt_id, px(18), h / 2)
            self.itemconfigure(self._txt_id, fill=hexc(color), font=font)

    def refresh(self) -> None:
        tk.Canvas.configure(self, bg=hexc(SKIN.flat), height=px(42))
        self._shape_kind = None
        self._paint()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        _strip_style_kw(kw)
        if "text" in kw:
            self._label = kw.pop("text")
        if kw:
            tk.Canvas.configure(self, **kw)

    config = configure


# --------------------------------------------------------------------------
# Checkbox e radio
# --------------------------------------------------------------------------

class _Toggle(_Fader, tk.Canvas):
    RADIO = False

    def __init__(self, parent, text: str = "", variable=None, command=None, onvalue=1, offvalue=0,
                 value=None, state: str = "normal", ground: str = "flat", **kw) -> None:
        self._label = text
        self._var = variable
        self._command = command
        self._on, self._off, self._value = onvalue, offvalue, value
        self._local = False
        self._ground = ground
        self._disabled = state == "disabled"
        self._cw = self._ch = 0
        self._txt_id = self._mark_id = None
        self._tw_init(hover=0.0, on=0.0)
        tk.Canvas.__init__(self, parent, bd=0, highlightthickness=0, bg=hexc(ground_rgb(ground)),
                           takefocus=0 if self._disabled else 1, cursor="" if self._disabled else "hand2")
        _live.add(self)
        self._tw["on"] = self._tt["on"] = 1.0 if self._checked() else 0.0
        self._measure()
        if self._var is not None:
            self._var.trace_add("write", self._on_var)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", lambda _e: None if self._disabled else self._tween("hover", 1.0))
        self.bind("<Leave>", lambda _e: self._tween("hover", 0.0))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<space>", lambda _e: self.toggle())
        self.bind("<FocusIn>", lambda _e: self._tween("hover", 1.0))
        self.bind("<FocusOut>", lambda _e: self._tween("hover", 0.0))

    def _box(self) -> int:
        return px(20)

    def _checked(self) -> bool:
        if self._var is None:
            return self._local
        v = self._var.get()
        if self.RADIO:
            return str(v) == str(self._value)
        if isinstance(v, (bool, int)) and self._on in (1, True):
            return bool(v)
        return str(v) == str(self._on)

    def _on_var(self, *_a) -> None:
        try:
            self._tween("on", 1.0 if self._checked() else 0.0)
        except tk.TclError:
            pass

    def toggle(self) -> None:
        if self._disabled:
            return
        if self.RADIO:
            if self._var is not None:
                self._var.set(self._value)
            self._local = True
        elif self._var is not None:
            self._var.set(self._off if self._checked() else self._on)
        else:
            self._local = not self._local
            self._tween("on", 1.0 if self._local else 0.0)
        if self._command:
            self._command()

    def _on_release(self, event) -> None:
        if 0 <= event.x <= self._cw and 0 <= event.y <= self._ch:
            self.focus_set()
            self.toggle()

    def _measure(self) -> None:
        font = SKIN.f_base
        width = self._box() + px(10) + font.measure(self._label) + 6
        height = max(self._box(), font.metrics("linespace")) + px(10)
        tk.Canvas.configure(self, width=width, height=height)

    def _on_configure(self, event) -> None:
        self._cw, self._ch = event.width, event.height
        self._paint()

    def _paint(self) -> None:
        w, h = self._cw, self._ch
        if w < 8 or h < 8:
            return
        bs = self._box()
        hov, on = self._lv("hover"), self._lv("on")
        f, a = SKIN.flat, SKIN.accent
        off_top = darken(SKIN.well, 0.10 if not SKIN.light else 0.04)
        off_bd = darken(f, 0.18) if SKIN.light else lighten(f, 0.22)
        top = mix(off_top, lighten(a, 0.10), on)
        bot = mix(SKIN.well, darken(a, 0.12), on)
        bd = mix(mix(off_bd, mix(off_bd, a, 0.6), hov), lighten(a, 0.30), on)
        if self._disabled:
            top, bot, bd = mix(f, top, 0.5), mix(f, bot, 0.5), mix(f, bd, 0.5)
        y0 = (h - bs) // 2
        _put_shape(self, 0, y0, bs, bs, top, bd, radius=bs // 2 if self.RADIO else px(6), top=top, bot=bot,
                   border=bd, bg=ground_rgb(self._ground), hl=0.18 * on, glow=a,
                   glow_a=round(0.40 * hov * (0.4 + 0.6 * on) if not self._disabled else 0.0, 2))
        tx = bs + px(10)
        color = SKIN.muted if self._disabled else SKIN.text
        if self._txt_id is None:
            self._txt_id = self.create_text(tx, h / 2, anchor="w", text=self._label, font=SKIN.f_base,
                                            fill=hexc(color))
        else:
            self.coords(self._txt_id, tx, h / 2)
            self.itemconfigure(self._txt_id, text=self._label, fill=hexc(color), font=SKIN.f_base)
        self._paint_mark(bs, y0, on)

    def _paint_mark(self, bs: int, y0: int, on: float) -> None:
        if self._mark_id is None:
            if self.RADIO:
                self._mark_id = self.create_oval(0, 0, 1, 1, outline="", fill=hexc(SKIN.accent_fg))
            else:
                self._mark_id = self.create_line(0, 0, 1, 1, 2, 2, width=max(2, px(2)), capstyle="round",
                                                 joinstyle="round", fill=hexc(SKIN.accent_fg))
        if self.RADIO:
            r = bs * 0.17 * (0.4 + 0.6 * on)
            cx, cy = bs / 2, y0 + bs / 2
            self.coords(self._mark_id, cx - r, cy - r, cx + r, cy + r)
        else:
            self.coords(self._mark_id, bs * 0.28, y0 + bs * 0.54, bs * 0.44, y0 + bs * 0.70,
                        bs * 0.74, y0 + bs * 0.32)
        self.itemconfigure(self._mark_id, fill=hexc(SKIN.accent_fg), state="normal" if on >= 0.5 else "hidden")
        self.tag_raise(self._mark_id)

    def refresh(self) -> None:
        tk.Canvas.configure(self, bg=hexc(ground_rgb(self._ground)))
        self._shape_kind = None
        self._measure()
        self._paint()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if "text" in kw:
            self._label = kw.pop("text")
            self._measure()
        if "command" in kw:
            self._command = kw.pop("command")
        if "state" in kw:
            self._disabled = kw.pop("state") == "disabled"
            tk.Canvas.configure(self, cursor="" if self._disabled else "hand2")
        _strip_style_kw(kw)
        if kw:
            tk.Canvas.configure(self, **kw)
        self._paint()

    config = configure


class GlassCheck(_Toggle):
    """Caixa de seleção de vidro (substitui ttk.Checkbutton)."""


class GlassRadio(_Toggle):
    """Botão de opção de vidro (substitui ttk.Radiobutton)."""
    RADIO = True


# --------------------------------------------------------------------------
# Barra de rolagem
# --------------------------------------------------------------------------

class GlassScrollbar(_Fader, tk.Canvas):
    """Barra de rolagem vertical fina, com thumb de vidro."""

    def __init__(self, parent, orient: str = "vertical", command=None, **kw) -> None:
        self._command = command
        self._first, self._last = 0.0, 1.0
        self._drag = None
        self._cw = self._ch = 0
        self._thumb_id = None
        self._tw_init(hover=0.0)
        tk.Canvas.__init__(self, parent, bd=0, highlightthickness=0, bg=hexc(SKIN.well), takefocus=0,
                           width=px(12))
        _live.add(self)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", lambda _e: self._tween("hover", 1.0))
        self.bind("<Leave>", lambda _e: None if self._drag else self._tween("hover", 0.0))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    def set(self, first, last) -> None:
        self._first, self._last = float(first), float(last)
        self._paint()

    def _geom(self):
        h = self._ch
        span = max(1e-6, self._last - self._first)
        th = max(px(30), span * h)
        y0 = self._first * (h - th) / max(1e-6, 1 - span) if span < 1 else 0
        return y0, th

    def _on_configure(self, event) -> None:
        self._cw, self._ch = event.width, event.height
        self._paint()

    def _paint(self) -> None:
        w, h = self._cw, self._ch
        if w < 6 or h < 10:
            return
        if self._last - self._first >= 0.999:
            self.delete("shape")
            self._shape_kind = None
            return
        y0, th = self._geom()
        well = SKIN.well
        base = darken(well, 0.14) if SKIN.light else lighten(well, 0.20)
        hot = darken(well, 0.28) if SKIN.light else lighten(well, 0.36)
        color = mix(base, hot, self._lv("hover"))
        tw = max(6, w - 4)
        _put_shape(self, 2, int(y0), tw, int(th), color, color, radius=tw // 2, top=color, bot=color, border=color,
                   bg=well, inset=0)

    def _press(self, event) -> None:
        y0, th = self._geom()
        if y0 <= event.y <= y0 + th:
            self._drag = event.y - y0
        elif self._command:
            self._command("scroll", 1 if event.y > y0 else -1, "pages")

    def _motion(self, event) -> None:
        if self._drag is None or not self._command:
            return
        _y0, th = self._geom()
        span = self._last - self._first
        room = max(1.0, self._ch - th)
        first = (event.y - self._drag) / room * (1 - span)
        self._command("moveto", max(0.0, min(1 - span, first)))

    def _release(self, _event) -> None:
        self._drag = None
        self._tween("hover", 0.0)

    def refresh(self) -> None:
        tk.Canvas.configure(self, bg=hexc(SKIN.well), width=px(12))
        self._shape_kind = None
        self._paint()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if "command" in kw:
            self._command = kw.pop("command")
        _strip_style_kw(kw)
        if kw:
            tk.Canvas.configure(self, **kw)

    config = configure


# --------------------------------------------------------------------------
# Campos
# --------------------------------------------------------------------------

class GlassField(_Fader, tk.Frame):
    """Moldura de vidro para qualquer conteúdo: coloque os filhos em `.body`."""

    def __init__(self, parent, pad: int = 6, ground: str = "flat", radius: int = 12) -> None:
        self._ground = ground
        self._radius = radius
        self._pad = pad
        self._cw = self._ch = 0
        self._tw_init(hover=0.0, focus=0.0)
        tk.Frame.__init__(self, parent, bd=0, highlightthickness=0, bg=hexc(ground_rgb(ground)))
        self._bgc = tk.Canvas(self, bd=0, highlightthickness=0, bg=hexc(ground_rgb(ground)))
        self._bgc.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bd=0, highlightthickness=0, bg=hexc(self._fill_rgb()))
        self.body.pack(fill="both", expand=True, padx=px(pad) + 3, pady=px(pad) + 3)
        _live.add(self)
        self._bgc.bind("<Configure>", self._on_configure)
        for widget in (self, self.body, self._bgc):
            tk.Misc.bind(widget, "<Enter>", self._check_hover, add="+")
            tk.Misc.bind(widget, "<Leave>", self._check_hover, add="+")

    def _fill_rgb(self):
        return SKIN.well

    def watch(self, widget) -> None:
        """Liga hover e foco de um filho à moldura."""
        widget.bind("<Enter>", self._check_hover, add="+")
        widget.bind("<Leave>", self._check_hover, add="+")
        widget.bind("<FocusIn>", lambda _e: self._tween("focus", 1.0), add="+")
        widget.bind("<FocusOut>", lambda _e: self._tween("focus", 0.0), add="+")

    def _check_hover(self, _e=None) -> None:
        try:
            x, y = self.winfo_pointerxy()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            inside = rx <= x < rx + self.winfo_width() and ry <= y < ry + self.winfo_height()
            self._tween("hover", 1.0 if inside else 0.0)
        except tk.TclError:
            pass

    def _on_configure(self, event) -> None:
        self._cw, self._ch = event.width, event.height
        self._paint()

    def _paint(self) -> None:
        w, h = self._cw, self._ch
        if w < 12 or h < 12:
            return
        f, a, fill = SKIN.flat, SKIN.accent, self._fill_rgb()
        hov, foc = self._lv("hover"), self._lv("focus")
        if SKIN.light:
            top, bd = darken(fill, 0.07), darken(f, 0.10)
            bd_h = mix(bd, a, 0.45)
        else:
            top, bd = darken(fill, 0.22), lighten(f, 0.14)
            bd_h = mix(lighten(f, 0.26), a, 0.30)
        border = mix(mix(bd, bd_h, hov), a, foc)
        _put_shape(self._bgc, 0, 0, w, h, fill, border, radius=px(self._radius), top=top, bot=fill, border=border,
                   bg=ground_rgb(self._ground), grad_px=px(5), glow=a, glow_a=round(0.42 * foc, 2),
                   bottom_hl=0.0 if SKIN.light else 0.10)

    def refresh(self) -> None:
        g = hexc(ground_rgb(self._ground))
        tk.Frame.configure(self, bg=g)
        self._bgc.configure(bg=g)
        self.body.configure(bg=hexc(self._fill_rgb()))
        self._bgc._shape_kind = None
        self._paint()


class GlassEntry(GlassField):
    """Campo de texto de uma linha (substitui ttk.Entry)."""

    _ENTRY_KEYS = ("textvariable", "show", "state", "font", "exportselection", "validate",
                   "validatecommand", "justify", "width")

    def __init__(self, parent, textvariable=None, show=None, width: int = 20, state: str = "normal", **kw) -> None:
        GlassField.__init__(self, parent, pad=5)
        self.entry = tk.Entry(self.body, textvariable=textvariable, bd=0, highlightthickness=0, relief="flat",
                              font=SKIN.f_input or SKIN.f_base, width=width, show=show or "", state=state)
        self.entry.pack(fill="x", padx=px(4), pady=px(4))
        self._style_entry()
        self.watch(self.entry)

    def _style_entry(self) -> None:
        well = hexc(SKIN.well)
        self.entry.configure(bg=well, fg=hexc(SKIN.text), insertbackground=hexc(SKIN.text),
                             selectbackground=hexc(SKIN.accent), selectforeground=hexc(SKIN.accent_fg),
                             disabledbackground=well, disabledforeground=hexc(SKIN.muted),
                             readonlybackground=well, font=SKIN.f_input or SKIN.f_base)

    def refresh(self) -> None:
        GlassField.refresh(self)
        self._style_entry()

    # --- proxy para o Entry ---------------------------------------------------
    def get(self):
        return self.entry.get()

    def insert(self, index, text):
        return self.entry.insert(index, text)

    def delete(self, first, last=None):
        return self.entry.delete(first, last)

    def select_range(self, start, end):
        return self.entry.select_range(start, end)

    def icursor(self, index):
        return self.entry.icursor(index)

    def focus_set(self):
        return self.entry.focus_set()

    def bind(self, sequence=None, func=None, add=None):
        return self.entry.bind(sequence, func, add)

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        ent = {k: kw.pop(k) for k in list(kw) if k in self._ENTRY_KEYS}
        if ent:
            self.entry.configure(**ent)
        _strip_style_kw(kw)
        if kw:
            tk.Frame.configure(self, **kw)

    config = configure

    def cget(self, key):
        if key in self._ENTRY_KEYS:
            return self.entry.cget(key)
        return tk.Frame.cget(self, key)

    def __getattr__(self, name):
        if name == "entry":
            raise AttributeError(name)
        return getattr(self.entry, name)


class GlassCombo(GlassField):
    """Lista suspensa de vidro (substitui ttk.Combobox somente leitura)."""

    def __init__(self, parent, textvariable=None, values=(), state: str = "readonly", width: int = 14,
                 **kw) -> None:
        self._state = state
        self._values = list(values)
        self._var = textvariable if textvariable is not None else tk.StringVar()
        self._pop = None
        GlassField.__init__(self, parent, pad=5)
        self.label = tk.Label(self.body, textvariable=self._var, anchor="w", bd=0, highlightthickness=0,
                              font=SKIN.f_base, width=width, padx=px(6), pady=px(4))
        self.arrow = tk.Canvas(self.body, width=px(18), height=px(18), bd=0, highlightthickness=0)
        self.label.pack(side="left", fill="x", expand=True)
        self.arrow.pack(side="right", padx=(0, px(4)))
        for widget in (self, self.body, self._bgc, self.label, self.arrow):
            widget.bind("<Button-1>", self._toggle_popup, add="+")
        self.watch(self.label)
        self.watch(self.arrow)
        self._recolor()

    def _fill_rgb(self):
        return SKIN.well if self._state != "disabled" else mix(SKIN.well, SKIN.flat, 0.55)

    def _recolor(self) -> None:
        fill = hexc(self._fill_rgb())
        dis = self._state == "disabled"
        cursor = "" if dis else "hand2"
        self.body.configure(bg=fill, cursor=cursor)
        self.label.configure(bg=fill, fg=hexc(SKIN.muted if dis else SKIN.text), font=SKIN.f_base, cursor=cursor)
        self.arrow.configure(bg=fill, cursor=cursor)
        self.arrow.delete("all")
        w, h = px(18), px(18)
        color = hexc(SKIN.muted if dis else mix(SKIN.muted, SKIN.text, self._tw["hover"]))
        self.arrow.create_line(w * 0.28, h * 0.40, w * 0.50, h * 0.62, w * 0.72, h * 0.40, width=max(2, px(2)),
                               capstyle="round", joinstyle="round", fill=color)

    def _paint(self) -> None:
        GlassField._paint(self)
        if hasattr(self, "arrow"):
            self._recolor()

    def refresh(self) -> None:
        GlassField.refresh(self)
        self._recolor()
        self.arrow.configure(width=px(18), height=px(18))

    # --- API parecida com ttk.Combobox -----------------------------------------
    def get(self):
        return self._var.get()

    def set(self, value) -> None:
        self._var.set(value)

    def current(self, index=None):
        if index is None:
            value = self._var.get()
            return self._values.index(value) if value in self._values else -1
        self._var.set(self._values[index])
        return None

    def configure(self, cnf=None, **kw):
        if cnf:
            kw = {**cnf, **kw}
        if "values" in kw:
            self._values = list(kw.pop("values"))
        if "state" in kw:
            self._state = kw.pop("state")
            GlassField.refresh(self)
            self._recolor()
        if "textvariable" in kw:
            self._var = kw.pop("textvariable")
            self.label.configure(textvariable=self._var)
        kw.pop("width", None)
        _strip_style_kw(kw)
        if kw:
            tk.Frame.configure(self, **kw)

    config = configure

    def cget(self, key):
        if key == "values":
            return tuple(self._values)
        if key == "state":
            return self._state
        return tk.Frame.cget(self, key)

    # --- popup -----------------------------------------------------------------
    def _toggle_popup(self, _e=None):
        if self._pop is not None:
            self._close()
            return "break"
        if self._state == "disabled" or not self._values:
            return "break"
        light = SKIN.light
        pop_bg = lighten(SKIN.well, 0.55) if light else lighten(SKIN.well, 0.06)
        border = darken(SKIN.flat, 0.18) if light else lighten(SKIN.flat, 0.24)
        hot = mix(pop_bg, SKIN.accent, 0.28)
        top = tk.Toplevel(self)
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=hexc(border))
        self._pop = top
        outer = tk.Frame(top, bg=hexc(pop_bg))
        outer.pack(padx=1, pady=1, fill="both", expand=True)
        rows_h = px(32)
        visible = min(len(self._values), 9)
        canvas = tk.Canvas(outer, bd=0, highlightthickness=0, bg=hexc(pop_bg), height=visible * rows_h)
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=hexc(pop_bg))
        width = max(self.winfo_width() - 2, px(160))
        canvas.create_window(0, 0, anchor="nw", window=inner, width=width)
        current = self._var.get()
        for value in self._values:
            row = tk.Label(inner, text=value, anchor="w", padx=px(14), height=1, bd=0, cursor="hand2",
                           bg=hexc(pop_bg), fg=hexc(SKIN.accent if value == current else SKIN.text),
                           font=SKIN.f_bold if value == current else SKIN.f_base, pady=px(6))
            row.pack(fill="x")
            row.bind("<Enter>", lambda _e, r=row, c=hot: self._fade_row(r, c, pop_bg))
            row.bind("<Leave>", lambda _e, r=row, c=pop_bg: self._fade_row(r, c, hot))
            row.bind("<Button-1>", lambda _e, v=value: self._choose(v))
        inner.update_idletasks()
        rows_h = max(1, inner.winfo_reqheight() // len(self._values))
        canvas.configure(scrollregion=(0, 0, width, inner.winfo_reqheight()), height=min(visible * rows_h, inner.winfo_reqheight()))
        wheel = lambda e: canvas.yview_scroll(-1 if (getattr(e, "delta", 0) > 0 or e.num == 4) else 1, "units")
        for widget in (top, canvas, inner, *inner.winfo_children()):
            widget.bind("<MouseWheel>", wheel)
            widget.bind("<Button-4>", wheel)
            widget.bind("<Button-5>", wheel)
        height = min(visible * rows_h, inner.winfo_reqheight()) + 2
        top.geometry(f"{width + 2}x{height}+{self.winfo_rootx()}+{self.winfo_rooty() + self.winfo_height() + px(4)}")
        top.deiconify()
        top.bind("<Escape>", lambda _e: self._close())
        top.bind("<Button-1>", self._maybe_close)
        try:
            top.wait_visibility()
            top.focus_force()
            top.grab_set()
        except tk.TclError:
            pass
        return "break"

    def _maybe_close(self, event) -> None:
        if event.widget is self._pop:
            self._close()

    def _fade_row(self, row, target, start, step: int = 1) -> None:
        """Realce suave da linha em 4 quadros."""
        try:
            token = getattr(row, "_fade_token", 0) + 1
            row._fade_token = token

            def run(i=1):
                if getattr(row, "_fade_token", 0) != token:
                    return
                row.configure(bg=hexc(mix(row_bg(row), target, i / 4)))
                if i < 4:
                    row.after(16, run, i + 1)

            def row_bg(r):
                return start

            run()
        except tk.TclError:
            pass

    def _choose(self, value) -> None:
        self._var.set(value)
        self._close()
        self.event_generate("<<ComboboxSelected>>")

    def _close(self) -> None:
        pop, self._pop = self._pop, None
        if pop is not None:
            try:
                pop.grab_release()
                pop.destroy()
            except tk.TclError:
                pass
