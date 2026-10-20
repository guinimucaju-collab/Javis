"""Paletas e cores do Javis.

O visual é "liquid glass": painéis translúcidos sobre um fundo aurora animado.
As cores de vidro são pré-compostas em Python (o Tk ignora o canal alfa de um
PNG), então aqui ficam só as matrizes de cor: fundo da janela, tinta, acento
e os tons que o motor de vidro usa para montar cada painel.
"""

from __future__ import annotations

# Cada tema descreve:
#   bg         cor base da janela (o motor de vidro parte dela)
#   blobs      aurora: (x%, y%, raio%, cor, força) — cores em RGB
#   surface    cor do conteúdo dentro do vidro
#   text / muted / accent / accent_fg / danger / ok / warn
#   glass_tint quanto de branco entra no painel de vidro
#   glass_blur raio do desfoque do fundo dentro do painel
THEMES: dict[str, dict] = {
    "aurora": {
        "label": "Aurora",
        "bg": (9, 12, 26),
        "blobs": [
            (0.08, 0.06, 0.78, (94, 76, 255), 0.90),
            (0.86, 0.10, 0.70, (0, 190, 230), 0.72),
            (0.52, 0.92, 0.80, (255, 74, 168), 0.58),
            (0.30, 0.55, 0.60, (52, 211, 153), 0.28),
        ],
        "surface": (16, 21, 40),
        "text": (233, 238, 252),
        "muted": (140, 152, 184),
        "accent": (110, 130, 255),
        "accent_fg": (255, 255, 255),
        "ok": (52, 211, 153),
        "warn": (251, 191, 36),
        "danger": (248, 113, 113),
        "blend": 1.0,
        "glass_tint": 0.085,
        "glass_blur": 26,
        "glass_saturation": 1.28,
        "card_radius": 20,
    },
    "meia-noite": {
        "label": "Meia-noite",
        "bg": (8, 10, 20),
        "blobs": [
            (0.12, 0.12, 0.85, (56, 96, 255), 0.78),
            (0.88, 0.22, 0.72, (120, 60, 220), 0.60),
            (0.50, 0.95, 0.85, (30, 120, 200), 0.45),
        ],
        "surface": (14, 18, 32),
        "text": (228, 234, 248),
        "muted": (130, 142, 172),
        "accent": (88, 140, 255),
        "accent_fg": (255, 255, 255),
        "ok": (52, 211, 153),
        "warn": (250, 186, 60),
        "danger": (245, 100, 100),
        "glass_tint": 0.075,
        "glass_blur": 30,
        "card_radius": 22,
    },
    "aurora-clara": {
        "label": "Aurora clara",
        "bg": (226, 232, 246),
        "blobs": [
            (0.18, 0.20, 0.62, (108, 132, 255), 0.80),
            (0.78, 0.28, 0.58, (72, 206, 238), 0.72),
            (0.50, 0.80, 0.60, (250, 122, 186), 0.60),
        ],
        "surface": (250, 251, 255),
        "text": (22, 30, 52),
        "muted": (98, 110, 138),
        "accent": (79, 96, 224),
        "accent_fg": (255, 255, 255),
        "ok": (16, 145, 105),
        "warn": (191, 122, 0),
        "danger": (208, 40, 47),
        "blend": 0.85,
        "glass_tint": 0.10,
        "glass_blur": 22,
        "glass_saturation": 1.35,
        "glass_inner_shadow": 0.12,
        "card_radius": 20,
    },
}

DEFAULT_THEME = "aurora"


def hexc(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Interpola duas cores; t=0 devolve a, t=1 devolve b."""
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def lighten(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return mix(rgb, (255, 255, 255), amount)


def darken(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return mix(rgb, (0, 0, 0), amount)


def theme_names() -> list[str]:
    return list(THEMES.keys())


def get_theme(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])
