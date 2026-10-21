"""Testes das paletas de cor e das regras de tema."""

from __future__ import annotations

import pytest

from javis.theme import (DEFAULT_THEME, THEMES, darken, get_theme, glass_surface, glass_well, hexc,
                         is_light, lighten, mix, theme_names)

CAMPOS_OBRIGATORIOS = {
    "label", "bg", "blobs", "surface", "text", "muted", "accent", "accent_fg",
    "ok", "warn", "danger", "glass_tint", "glass_blur", "card_radius",
}


def test_todos_os_temas_tem_os_campos_esperados():
    for nome, tema in THEMES.items():
        faltando = CAMPOS_OBRIGATORIOS - set(tema)
        assert not faltando, f"o tema {nome} está sem {faltando}"


def test_cores_dos_temas_sao_rgb_validos():
    for nome, tema in THEMES.items():
        for campo in ("bg", "surface", "text", "muted", "accent", "accent_fg", "ok", "warn", "danger"):
            cor = tema[campo]
            assert isinstance(cor, tuple) and len(cor) == 3, f"{nome}.{campo}"
            assert all(isinstance(c, int) and 0 <= c <= 255 for c in cor), f"{nome}.{campo}"


def test_cada_blob_da_aurora_e_valido():
    for nome, tema in THEMES.items():
        assert tema["blobs"], f"o tema {nome} não tem blobs"
        for x, y, raio, cor, forca in tema["blobs"]:
            assert 0 <= x <= 1 and 0 <= y <= 1
            assert raio > 0 and forca > 0
            assert len(cor) == 3


def test_hexc_formata_e_limita():
    assert hexc((0, 0, 0)) == "#000000"
    assert hexc((255, 255, 255)) == "#ffffff"
    assert hexc((-10, 300, 12)) == "#00ff0c"


def test_mix_interpola():
    assert mix((0, 0, 0), (100, 100, 100), 0.0) == (0, 0, 0)
    assert mix((0, 0, 0), (100, 100, 100), 1.0) == (100, 100, 100)
    assert mix((0, 0, 0), (100, 100, 100), 0.5) == (50, 50, 50)


def test_mix_limita_o_fracao():
    assert mix((0, 0, 0), (100, 100, 100), 2.0) == (100, 100, 100)
    assert mix((0, 0, 0), (100, 100, 100), -1.0) == (0, 0, 0)


def test_lighten_e_darken():
    assert lighten((0, 0, 0), 1.0) == (255, 255, 255)
    assert darken((255, 255, 255), 1.0) == (0, 0, 0)
    assert lighten((100, 100, 100), 0.0) == (100, 100, 100)


def test_is_light_separa_o_tema_claro():
    assert is_light(THEMES["aurora-clara"]) is True
    assert is_light(THEMES["aurora"]) is False
    assert is_light(THEMES["meia-noite"]) is False


def test_get_theme_fallback():
    assert get_theme("inexistente") is THEMES[DEFAULT_THEME]
    assert get_theme("aurora") is THEMES["aurora"]


def test_theme_names_lista_os_temas():
    assert theme_names() == list(THEMES.keys())


def test_superficie_do_vidro_depende_so_do_tema():
    """A cor do miolo do vidro tem de ser igual em todos os widgets (sem emenda)."""
    for nome, tema in THEMES.items():
        assert glass_surface(tema) == glass_surface(get_theme(nome))
        assert glass_well(tema) != glass_surface(tema), f"o poço do vidro sumiu no tema {nome}"


def test_o_poco_do_vidro_e_mais_escuro_no_tema_escuro_e_mais_claro_no_claro():
    for nome in ("aurora", "meia-noite"):
        assert sum(glass_well(THEMES[nome])) < sum(glass_surface(THEMES[nome]))
    claro = THEMES["aurora-clara"]
    assert sum(glass_well(claro)) > sum(glass_surface(claro))
