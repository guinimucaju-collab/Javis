"""Motor de vidro: renderiza o fundo aurora e os painéis de vidro.

O Tk não deixa widgets transparentes, então o vidro é pré-composto numa imagem
que fica no Canvas de fundo. O truque que evita emendas: o miolo de cada
painel é uma cor chapada (theme.glass_surface) e só a borda ("rim") mostra o
fundo desfocado, com brilho de vidro, convergindo suavemente para essa cor.
Os widgets por cima usam exatamente a mesma cor chapada.

Precisa de numpy. Sem ele, `compose` devolve None e a interface usa um visual
simples (sem aurora), sem travar.
"""

from __future__ import annotations

import struct
import zlib

try:
    import numpy as np
except ImportError:  # pragma: no cover - depende do ambiente
    np = None

from .theme import glass_surface, is_light

HAS_NUMPY = np is not None

_aurora_cache: dict = {}


# --------------------------------------------------------------------------
# Formatos de imagem
# --------------------------------------------------------------------------

def to_ppm(width: int, height: int, rgb: bytes) -> bytes:
    """PPM binário: o Tk lê direto, sem compressão (bem mais rápido que PNG)."""
    return b"P6\n%d %d\n255\n" % (width, height) + rgb


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """PNG RGB; só usado se o Tk recusar o PPM."""
    stride = width * 3
    if np is not None:
        arr = np.frombuffer(rgb, np.uint8).reshape(height, stride)
        raw = np.concatenate([np.zeros((height, 1), np.uint8), arr], axis=1).tobytes()
    else:
        out = bytearray()
        for y in range(height):
            out.append(0)
            out += rgb[y * stride:(y + 1) * stride]
        raw = bytes(out)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1))
            + chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# Peças numéricas
# --------------------------------------------------------------------------

def _aurora(width: int, height: int, theme: dict):
    key = (theme.get("label"), width, height)
    cached = _aurora_cache.get("last")
    if cached and cached[0] == key:
        return cached[1].copy()
    xx = np.arange(width, dtype=np.float32)[None, :]
    yy = np.arange(height, dtype=np.float32)[:, None]
    img = np.empty((height, width, 3), np.float32)
    img[:] = theme["bg"]
    blend = float(theme.get("blend", 1.0))
    for cx, cy, radius, color, strength in theme["blobs"]:
        dx = (xx - cx * width) / (radius * width)
        dy = (yy - cy * height) / (radius * width)
        d = np.sqrt(dx * dx + dy * dy)
        fall = (np.clip(1.0 - d, 0.0, 1.0) ** 2.2 * (strength * blend))[..., None]
        img += (np.asarray(color, np.float32) - img) * fall
    _aurora_cache["last"] = (key, img.copy())
    return img


def _box_axis(a, r: int, axis: int):
    """Desfoque de caixa em O(1) por pixel (soma acumulada)."""
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def _blur(a, r: int, passes: int = 2):
    for _ in range(passes):
        a = _box_axis(_box_axis(a, r, 0), r, 1)
    return a


def _blur_low(a, r: int, passes: int = 2, f: int = 4):
    """Desfoque barato para coisas suaves: calcula em 1/f da resolução e amplia."""
    h, w = a.shape[:2]
    small = _blur(a[::f, ::f], max(1, r // f), passes)
    big = np.repeat(np.repeat(small, f, axis=0), f, axis=1)
    return big[:h, :w]


def _sdf(xx, yy, x, y, w, h, r):
    """Distância com sinal até um retângulo arredondado (<0 dentro, 0 na borda)."""
    qx = np.abs(xx + 0.5 - (x + w / 2)) - (w / 2 - r)
    qy = np.abs(yy + 0.5 - (y + h / 2)) - (h / 2 - r)
    return (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
            + np.minimum(np.maximum(qx, qy), 0) - r)


def _clip_region(panel: dict, width: int, height: int, pad: int = 0):
    x0 = max(0, int(panel["x"]) - pad)
    y0 = max(0, int(panel["y"]) - pad)
    x1 = min(width, int(panel["x"] + panel["w"]) + pad)
    y1 = min(height, int(panel["y"] + panel["h"]) + pad)
    return x0, y0, x1, y1


def _shadow(canvas, panel: dict, theme: dict) -> None:
    """Sombra suave sob o painel: é o que o descola do fundo."""
    height, width = canvas.shape[:2]
    strength = float(theme.get("glass_shadow", 0.20 if is_light(theme) else 0.42))
    x, y, w, h = (int(panel[k]) for k in ("x", "y", "w", "h"))
    r = min(int(panel.get("radius", 0)), w // 2, h // 2)
    x0, y0, x1, y1 = _clip_region(panel, width, height, pad=44)
    yy = np.arange(y0, y1, dtype=np.float32)[:, None]
    xx = np.arange(x0, x1, dtype=np.float32)[None, :]
    mask = np.clip(0.5 - _sdf(xx, yy, x, y + 10, w, h, r), 0.0, 1.0)[..., None]
    mask = _blur_low(mask, 20, 3)
    canvas[y0:y1, x0:x1] *= (1.0 - strength * mask)


def _glass(canvas, panel: dict, theme: dict, flat) -> None:
    height, width = canvas.shape[:2]
    x, y, w, h = (int(panel[k]) for k in ("x", "y", "w", "h"))
    if w <= 0 or h <= 0:
        return
    x0, y0, x1, y1 = _clip_region(panel, width, height)
    if x1 <= x0 or y1 <= y0:
        return
    rh = y1 - y0
    r = min(int(panel.get("radius", 0)), w // 2, h // 2)
    rim = max(4, int(panel.get("rim", 16)))
    region = canvas[y0:y1, x0:x1]
    yy = np.arange(y0, y1, dtype=np.float32)[:, None]
    xx = np.arange(x0, x1, dtype=np.float32)[None, :]
    sdf = _sdf(xx, yy, x, y, w, h, r)
    alpha = np.clip(0.5 - sdf, 0.0, 1.0)[..., None]
    depth = np.maximum(0.0, -sdf)

    # Vidro fosco: o que está atrás, desfocado, saturado e com um véu branco
    # mais forte em cima (luz vindo de cima).
    blur_r = max(2, int(theme.get("glass_blur", 26)) // 6)
    frosted = _blur_low(region, blur_r * 4, 2)
    sat = float(theme.get("glass_saturation", 1.28))
    grey = frosted.mean(axis=2, keepdims=True)
    frosted = np.clip(grey + (frosted - grey) * sat, 0, 255)
    tint = float(theme.get("glass_tint", 0.085)) * 2.2
    veil = tint * np.linspace(1.0, 0.5, rh, dtype=np.float32)[:, None, None]
    veiled = frosted * (1.0 - veil) + 255.0 * veil

    # Do miolo (cor chapada) até a borda (vidro fosco), em `rim` pixels.
    t = np.clip(depth / rim, 0.0, 1.0)
    inner = (t * t * (3.0 - 2.0 * t))[..., None]
    edge = float(theme.get("glass_edge", 0.60 if is_light(theme) else 0.78))
    mixed = flat + (veiled - flat) * (edge * (1.0 - inner))

    # Linha especular: clara em cima, mais fraca embaixo, seguindo o contorno
    # arredondado de verdade.
    ring = np.clip(1.0 - np.abs(sdf + 0.5), 0.0, 1.0)
    lit = np.linspace(1.0, 0.25, rh, dtype=np.float32)[:, None]
    line = (ring * (0.22 + 0.45 * lit))[..., None]
    mixed = mixed * (1.0 - line) + 255.0 * line

    region[:] = mixed * alpha + region * (1.0 - alpha)


def compose(width: int, height: int, theme: dict, panels: list[dict]):
    """Devolve os bytes RGB da cena (fundo + sombras + vidro) ou None sem numpy."""
    if np is None:
        return None
    width, height = max(1, int(width)), max(1, int(height))
    canvas = _aurora(width, height, theme)
    flat = np.asarray(glass_surface(theme), np.float32)
    for panel in panels:
        _shadow(canvas, panel, theme)
    for panel in panels:
        _glass(canvas, panel, theme, flat)
    return np.clip(canvas, 0, 255).astype(np.uint8).tobytes()
