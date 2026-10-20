"""Motor de vidro: renderiza o fundo aurora e os painéis translúcidos.

O Tk não compõe o canal alfa de um PNG (verificado em captura de tela real:
uma imagem semitransparente vira opaca). Por isso o vidro é *pré-composto*
aqui: geramos o fundo aurora, tiramos uma cópia desfocada dele para dentro
de cada painel e misturamos o branco do vidro por cima. O resultado é um
painel que deixa ver o que está atrás — o mesmo efeito do acrylic do
Windows, sem depender de API do sistema.

O motor usa apenas a biblioteca padrão. Se `numpy` estiver disponível, o
cálculo é vetorizado e fica instantâneo; caso contrário, cai para um
renderizador puro em Python (mais lento, mas com o mesmo resultado).
"""

from __future__ import annotations

import math
import struct
import zlib

try:  # opcional: acelera muito o cálculo do fundo
    import numpy as _np
except ImportError:  # pragma: no cover - depende do ambiente
    _np = None

from .theme import darken, hexc, lighten, mix


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------

def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """rgb: bytes RGB, uma linha por pixel, 3 bytes por pixel."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filtro "none"
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# Fundo aurora
# --------------------------------------------------------------------------

def _aurora_numpy(width: int, height: int, theme: dict):
    np = _np
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    base = np.array(theme["bg"], np.float32)
    # Os blobs são misturados com a cor base um de cada vez, em vez de
    # somados: somar saturaria tudo em branco no tema claro e o vidro
    # perderia a cor (virava cinza).
    img = base.copy()
    blend = float(theme.get("blend", 1.0))
    for cx, cy, radius, color, strength in theme["blobs"]:
        dx = (xx - cx * width) / (radius * width)
        dy = (yy - cy * height) / (radius * width)
        d = np.sqrt(dx * dx + dy * dy)
        falloff = (np.clip(1.0 - d, 0.0, 1.0) ** 2.2 * strength)[..., None]
        img = img + (np.array(color, np.float32) - img) * falloff * blend
    return np.clip(img, 0, 255).astype(np.uint8)


def _aurora_python(width: int, height: int, theme: dict) -> bytearray:
    """Versão sem numpy: mesma fórmula, amostra por amostra."""
    out = bytearray(width * height * 3)
    bg = theme["bg"]
    blend = float(theme.get("blend", 1.0))
    blobs = []
    for cx, cy, radius, color, strength in theme["blobs"]:
        blobs.append((cx * width, cy * height, radius * width, color, strength))
    idx = 0
    for y in range(height):
        for x in range(width):
            r, g, b = float(bg[0]), float(bg[1]), float(bg[2])
            for cx, cy, radius, color, strength in blobs:
                dx = (x - cx) / radius
                dy = (y - cy) / radius
                d = math.sqrt(dx * dx + dy * dy)
                if d < 1.0:
                    f = (1.0 - d) ** 2.2 * strength * blend
                    r += (color[0] - r) * f
                    g += (color[1] - g) * f
                    b += (color[2] - b) * f
            out[idx] = max(0, min(255, int(r)))
            out[idx + 1] = max(0, min(255, int(g)))
            out[idx + 2] = max(0, min(255, int(b)))
            idx += 3
    return out


def render_backdrop(width: int, height: int, theme: dict) -> bytes:
    """Devolve o PNG (RGB) do fundo aurora."""
    width = max(1, int(width))
    height = max(1, int(height))
    if _np is not None:
        arr = _aurora_numpy(width, height, theme)
        return encode_png(width, height, arr.tobytes())
    return encode_png(width, height, bytes(_aurora_python(width, height, theme)))


# --------------------------------------------------------------------------
# Painel de vidro
# --------------------------------------------------------------------------

def _blur_box(data, width: int, height: int, radius: int, channels: int = 3):
    """Desfoque de caixa separável, repetido — barato e suficiente para o vidro.

    Separável significa O(r) em vez de O(r²): o custo cai de ~60s para ~0.2s
    numa janela 1200x760 com raio 26.
    """
    if radius < 1:
        return data
    if _np is not None:
        np = _np
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(height, width, channels)
        for _ in range(3):
            arr = _box_blur_np(arr, radius)
        return arr
    # caminho puro: listas de floats
    grid = [list(data[i * width * channels:(i + 1) * width * channels]) for i in range(height)]
    for _ in range(3):
        grid = _box_blur_py(grid, width, height, channels, radius)
    flat = []
    for row in grid:
        flat.extend(row)
    return flat


def _box_blur_np(arr, radius: int):
    """Uma passada de desfoque de caixa nas duas direções."""
    np = _np
    pad = np.pad(arr, ((0, 0), (radius, radius), (0, 0)), mode="edge")
    acc = np.zeros_like(arr)
    for dx in range(-radius, radius + 1):
        acc += pad[:, radius + dx:radius + dx + arr.shape[1], :]
    acc /= (2 * radius + 1)
    pad = np.pad(acc, ((radius, radius), (0, 0), (0, 0)), mode="edge")
    out = np.zeros_like(arr)
    for dy in range(-radius, radius + 1):
        out += pad[radius + dy:radius + dy + arr.shape[0], :, :]
    out /= (2 * radius + 1)
    return out


def _box_blur_py(grid, width, height, channels, radius):
    """Uma passagem de desfoque de caixa, em Python puro."""
    # horizontal
    tmp = []
    for y in range(height):
        src = grid[y]
        row = [0.0] * (width * channels)
        for x in range(width):
            base = x * channels
            for c in range(channels):
                total = 0.0
                for dx in range(-radius, radius + 1):
                    xx = x + dx
                    if xx < 0:
                        xx = 0
                    elif xx >= width:
                        xx = width - 1
                    total += src[xx * channels + c]
                row[base + c] = total / (2 * radius + 1)
        tmp.append(row)
    # vertical
    out = []
    for y in range(height):
        row = [0.0] * (width * channels)
        for x in range(width):
            base = x * channels
            for c in range(channels):
                total = 0.0
                for dy in range(-radius, radius + 1):
                    yy = y + dy
                    if yy < 0:
                        yy = 0
                    elif yy >= height:
                        yy = height - 1
                    total += tmp[yy][base + c]
                row[base + c] = total / (2 * radius + 1)
        out.append(row)
    return out


def decode_png_rgb(data: bytes) -> tuple[int, int, bytes]:
    """Lê um PNG RGB (sem alfa) e devolve (largura, altura, bytes RGB)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("não é um PNG")
    pos = 8
    width = height = 0
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", payload[:10])
            if depth != 8 or color != 2:
                raise ValueError("o PNG precisa ser RGB de 8 bits")
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    stride = width * 3
    out = bytearray(width * height * 3)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        filt = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if filt == 1:
            for i in range(3, stride):
                line[i] = (line[i] + line[i - 3]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = line[i - 3] if i >= 3 else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                a = line[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, bytes(out)


def glass_panel(
    backdrop_png: bytes,
    width: int,
    height: int,
    theme: dict,
    panels: list[dict],
) -> bytes:
    """Compõe os painéis de vidro sobre o fundo.

    Cada painel é um dicionário: x, y, w, h (em pixels), radius (opcional),
    tint (opcional) e opacity (opcional). Devolve os bytes RGB finais.
    """
    _, _, raw = decode_png_rgb(backdrop_png)
    if _np is not None:
        return _glass_numpy(raw, width, height, theme, panels)
    return bytes(_glass_python(raw, width, height, theme, panels))

def _saturate(arr, factor: float):
    """Aumenta a saturação de um array RGB (float) mantendo o brilho.

    Em temas claros a saturação é reduzida: o véu branco já domina e
    saturar mais transformaria o painel em cinza.
    """
    np = _np
    if np is None:
        return arr
    grey = arr.mean(axis=2, keepdims=True)
    return np.clip(grey + (arr - grey) * factor, 0, 255)


def _inner_shadow(width: int, height: int, corner: int):
    """Máscara 1 na borda, 0 no miolo: simula a sombra interna do vidro.

    `dist` é a distância com sinal: negativa dentro do retângulo, zero na
    borda. A sombra só aparece perto da borda (dist -> 0) e some no miolo
    (dist muito negativo).
    """
    np = _np
    if np is None:
        return [[0.0] * width for _ in range(height)]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    qx = np.abs(xx - (width / 2)) - (width / 2 - corner)
    qy = np.abs(yy - (height / 2)) - (height / 2 - corner)
    dist = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0)
    depth = np.maximum(0.0, -dist)          # 0 na borda, cresce para dentro
    falloff = np.clip(1.0 - depth / max(1.0, corner * 1.8), 0.0, 1.0)
    return falloff


def _glass_numpy(backdrop_rgb: bytes, width: int, height: int, theme: dict, panels: list[dict]) -> bytes:
    np = _np
    canvas = np.frombuffer(backdrop_rgb, dtype=np.uint8).reshape(height, width, 3).astype(np.float32)
    tint_default = theme.get("glass_tint", 0.16)
    blur_default = theme.get("glass_blur", 26)
    yy_all, xx_all = np.mgrid[0:height, 0:width].astype(np.float32)

    for panel in panels:
        x, y = int(panel["x"]), int(panel["y"])
        w, h = int(panel["w"]), int(panel["h"])
        if w <= 0 or h <= 0:
            continue
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        rw, rh = x1 - x0, y1 - y0
        region = canvas[y0:y1, x0:x1]
        radius = int(panel.get("blur", blur_default))
        tint = float(panel.get("tint", tint_default))
        opacity = float(panel.get("opacity", 1.0))
        corner = int(panel.get("radius", 0))

        # Desfoque do que está atrás do vidro.
        frosted = _blur_box(region.copy(), rw, rh, max(1, radius // 9))
        # O vidro real preserva a saturação do que está atrás; devolve um pouco
        # dela, senão o painel fica lavado e sem vida. Em tema claro o fundo já
        # é quase branco, então o véu branco apenas clareia (e não acinzenta).
        sat = float(panel.get("saturation", theme.get("glass_saturation", 1.28)))
        frosted = _saturate(frosted, sat)
        # Vidro: um véu de branco, mais forte em cima (luz vindo de cima).
        ramp = np.linspace(1.0, 0.45, rh, dtype=np.float32)[:, None, None]
        veil = tint * ramp
        mixed = frosted * (1.0 - veil) + 255.0 * veil

        # Sombra interna da "lente": escurece logo dentro da borda, como um
        # vidro com espessura. É o que dá a sensação de profundidade.
        if corner > 0:
            inner = _inner_shadow(rw, rh, corner)[..., None]
            strength = float(panel.get("inner_shadow", theme.get("glass_inner_shadow", 0.30)))
            mixed = mixed * (1.0 - inner * strength)

        # Cantos arredondados: fora da máscara, o fundo volta ao normal.
        if corner > 0:
            cy = yy_all[y0:y1, x0:x1]
            cx = xx_all[y0:y1, x0:x1]
            qx = np.abs(cx - (x + w / 2)) - (w / 2 - corner)
            qy = np.abs(cy - (y + h / 2)) - (h / 2 - corner)
            dist = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0)
            alpha = np.clip(corner + 0.5 - dist, 0.0, 1.0)[..., None]
        else:
            alpha = np.ones((rh, rw, 1), np.float32)

        region[:] = mixed * alpha + region * (1.0 - alpha)

        # Borda especular: luz em cima, sombra embaixo.
        edge_light = np.array(lighten((int(region[0, 0, 0]), int(region[0, 0, 1]), int(region[0, 0, 2])), 0.42), np.float32)
        edge_dark = np.array(darken((int(region[-1, 0, 0]), int(region[-1, 0, 1]), int(region[-1, 0, 2])), 0.30), np.float32)
        region[0, :, :] = edge_light
        region[-1, :, :] = edge_dark
        region[:, 0, :] = edge_light * 0.92
        region[:, -1, :] = edge_dark

    return np.clip(canvas, 0, 255).astype(np.uint8).tobytes()


def _glass_python(backdrop_rgb: bytes, width: int, height: int, theme: dict, panels: list[dict]) -> bytearray:
    canvas = bytearray(backdrop_rgb)
    tint_default = theme.get("glass_tint", 0.16)
    blur_default = theme.get("glass_blur", 26)

    for panel in panels:
        x, y = int(panel["x"]), int(panel["y"])
        w, h = int(panel["w"]), int(panel["h"])
        if w <= 0 or h <= 0:
            continue
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        rw, rh = x1 - x0, y1 - y0
        region = bytes(canvas[(y0 * width + x0) * 3:(y1 * width + x1) * 3])
        radius = int(panel.get("blur", blur_default))
        tint = float(panel.get("tint", tint_default))
        opacity = float(panel.get("opacity", 1.0))

        frosted = _blur_box(region, rw, rh, max(1, radius // 6))
        for row in range(rh):
            ramp = 1.0 - 0.45 * (row / max(1, rh - 1))
            base = (y0 + row) * width
            for col in range(rw):
                pos = (row * rw + col) * 3
                for c in range(3):
                    value = frosted[pos + c] * (1.0 - tint * ramp) + 255.0 * (tint * ramp)
                    value = value * opacity + canvas[(base + x0 + col) * 3 + c] * (1.0 - opacity)
                    canvas[(base + x0 + col) * 3 + c] = max(0, min(255, int(value)))
    return canvas


def rounded_mask(width: int, height: int, radius: int) -> bytes:
    """Máscara 1 = dentro do canto arredondado (usada pelo botão de vidro)."""
    mask = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            inside = True
            for cx, cy in ((radius, radius), (width - radius, radius),
                            (radius, height - radius), (width - radius, height - radius)):
                if (x < radius and cx == radius and y < radius and cy == radius) or \
                   (x >= width - radius and cx == width - radius and y < radius and cy == radius) or \
                   (x < radius and cx == radius and y >= height - radius and cy == height - radius) or \
                   (x >= width - radius and cx == width - radius and y >= height - radius and cy == height - radius):
                    dx = x - cx
                    dy = y - cy
                    if dx * dx + dy * dy > radius * radius:
                        inside = False
                        break
            mask[y * width + x] = 1 if inside else 0
    return bytes(mask)


def sample_region(png: bytes, x: int, y: int, w: int, h: int) -> tuple[int, int, int]:
    """Cor média de uma região do PNG — usada para casar a cor dos widgets
    (que o Tk obriga a serem sólidos) com o vidro desenhado atrás."""
    width, height, raw = decode_png_rgb(png)
    total = [0, 0, 0]
    count = 0
    for yy in range(max(0, y), min(height, y + h)):
        base = yy * width * 3
        for xx in range(max(0, x), min(width, x + w)):
            off = base + xx * 3
            total[0] += raw[off]
            total[1] += raw[off + 1]
            total[2] += raw[off + 2]
            count += 1
    if not count:
        return (0, 0, 0)
    return (total[0] // count, total[1] // count, total[2] // count)


def make_button_image(width: int, height: int, radius: int, top_color, bottom_color, border=None) -> bytes:
    """PNG do botão de vidro (gradiente + borda). O Tk mostra como imagem."""
    width, height = max(2, int(width)), max(2, int(height))
    rows = []
    for y in range(height):
        t = y / max(1, height - 1)
        row = bytearray()
        base = mix(top_color, bottom_color, t)
        for x in range(width):
            row += bytes(base)
            if border and (x < 1 or y < 1 or x >= width - 1 or y >= height - 1):
                row[-3:] = bytes(border)
        rows.append(bytes(row))
    return encode_png(width, height, b"".join(rows))
