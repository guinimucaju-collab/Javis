"""Acrílico nativo do Windows 10/11: desfoque real do que está atrás da janela.

O Tk não tem transparência por pixel, então combinamos duas coisas:
  1. `-transparentcolor`: pixels da cor-chave ficam transparentes (as áreas fora
     dos painéis de vidro);
  2. o DWM aplica o desfoque acrílico atrás da janela (SetWindowCompositionAttribute).
Tudo é protegido por try/except: se algo falhar, devolve False e o app continua
com o fundo aurora normal. Só faz algo no Windows.
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"
KEY_RGB = (1, 0, 2)  # cor-chave: nenhum widget usa um tom tão escuro


def _hwnd(root) -> int:
    import ctypes
    try:
        return int(root.wm_frame(), 16)
    except (ValueError, TypeError):
        return ctypes.windll.user32.GetParent(root.winfo_id())


def _accent(hwnd: int, state: int, abgr: int) -> bool:
    import ctypes
    from ctypes import wintypes

    class AccentPolicy(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class WinCompAttrData(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.POINTER(AccentPolicy)),
                    ("SizeOfData", ctypes.c_size_t)]

    policy = AccentPolicy(state, 2, abgr, 0)
    data = WinCompAttrData(19, ctypes.pointer(policy), ctypes.sizeof(policy))  # 19 = WCA_ACCENT_POLICY
    fn = ctypes.windll.user32.SetWindowCompositionAttribute
    fn.argtypes = [wintypes.HWND, ctypes.POINTER(WinCompAttrData)]
    fn.restype = wintypes.BOOL
    return bool(fn(hwnd, ctypes.byref(data)))


def _dark_titlebar(hwnd: int, dark: bool) -> None:
    import ctypes
    value = ctypes.c_int(1 if dark else 0)
    for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11/Win10 recente)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:  # noqa: BLE001
            pass


def enable(root, tint: tuple, alpha: int, dark: bool) -> bool:
    """Liga transparência + acrílico. `tint` é a cor do véu e `alpha` (0-255) a força dele."""
    if not IS_WINDOWS:
        return False
    try:
        key = "#%02x%02x%02x" % KEY_RGB
        root.configure(bg=key)
        root.attributes("-transparentcolor", key)
        root.update_idletasks()
        hwnd = _hwnd(root)
        r, g, b = tint
        abgr = (int(alpha) << 24) | (b << 16) | (g << 8) | r
        _dark_titlebar(hwnd, dark)
        return _accent(hwnd, 4, abgr) or _accent(hwnd, 3, abgr)  # 4 = acrílico, 3 = blur simples
    except Exception:  # noqa: BLE001 - efeito opcional
        return False


def disable(root) -> None:
    if not IS_WINDOWS:
        return
    try:
        root.attributes("-transparentcolor", "")
        _accent(_hwnd(root), 0, 0)  # 0 = desligado
    except Exception:  # noqa: BLE001
        pass
