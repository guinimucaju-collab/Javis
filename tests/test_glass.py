"""Testes do motor de vidro (numpy): composição da cena e dos controles."""

from __future__ import annotations

import pytest

from javis import glass
from javis.theme import THEMES

pytestmark = pytest.mark.skipif(not glass.HAS_NUMPY, reason="sem numpy o vidro não é desenhado")


def test_compose_devolve_rgb_do_tamanho_certo():
    largura, altura = 120, 80
    paineis = [{"x": 10, "y": 10, "w": 60, "h": 40, "radius": 8, "rim": 6}]

    rgb = glass.compose(largura, altura, THEMES["aurora"], paineis)

    assert rgb is not None
    assert len(rgb) == largura * altura * 3


def test_compose_sem_paineis_ainda_desenha_o_fundo():
    rgb = glass.compose(40, 30, THEMES["aurora"], [])
    assert rgb is not None and len(rgb) == 40 * 30 * 3


def test_compose_com_cor_chave_nao_desenha_a_aurora():
    """Com a cor-chave (acrílico), o fundo fica chapado para o Windows transparentizar."""
    largura, altura = 50, 40
    rgb = glass.compose(largura, altura, THEMES["aurora"], [], key=glass.__dict__.get("KEY_RGB", (1, 0, 2)))
    fundo = rgb[:3]

    assert fundo == bytes((1, 0, 2))


def test_render_control_devolve_rgb():
    rgb = glass.render_control(40, 20, radius=6, top=(40, 40, 60), bot=(30, 30, 50),
                               border=(80, 80, 100), bg=(20, 20, 30))
    assert rgb is not None and len(rgb) == 40 * 20 * 3


def test_render_control_corrige_tamanhos_minimos():
    rgb = glass.render_control(0, 0, radius=0, top=(0, 0, 0), bot=(0, 0, 0),
                               border=(0, 0, 0), bg=(0, 0, 0))
    assert rgb is not None and len(rgb) > 0


def test_to_ppm_tem_cabecalho_valido():
    data = glass.to_ppm(3, 2, b"\xff" * 18)
    assert data.startswith(b"P6\n3 2\n255\n")
    assert len(data) == len(b"P6\n3 2\n255\n") + 18


def test_encode_png_gera_arquivo_valido():
    data = glass.encode_png(3, 2, b"\x10" * 18)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in data and b"IEND" in data


def test_compose_sem_numpy_devolve_none(monkeypatch):
    monkeypatch.setattr(glass, "np", None)
    assert glass.compose(30, 30, THEMES["aurora"], []) is None


def test_render_control_sem_numpy_devolve_none(monkeypatch):
    monkeypatch.setattr(glass, "np", None)
    rgb = glass.render_control(20, 10, radius=4, top=(0, 0, 0), bot=(0, 0, 0),
                               border=(0, 0, 0), bg=(0, 0, 0))
    assert rgb is None
