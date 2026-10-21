"""Testes dos controles de vidro (precisam de uma sessão gráfica)."""

from __future__ import annotations

import tkinter as tk

import pytest

from javis import widgets
from javis.theme import THEMES


@pytest.fixture()
def skin():
    widgets.set_skin(THEMES["aurora"], 1.0, tkfont_default(), tkfont_default(), tkfont_default())
    return widgets.SKIN


def tkfont_default():
    import tkinter.font as tkfont

    return tkfont.Font(family="Segoe UI", size=10)


def test_set_skin_atualiza_as_cores(tk_root, skin):
    widgets.set_skin(THEMES["aurora-clara"], 1.0, tkfont_default(), tkfont_default(), tkfont_default())

    assert widgets.SKIN.light is True
    assert widgets.SKIN.text == THEMES["aurora-clara"]["text"]
    widgets.set_skin(THEMES["aurora"], 1.0, tkfont_default(), tkfont_default(), tkfont_default())
    assert widgets.SKIN.light is False


def test_control_image_e_none_quando_o_vidro_esta_desligado(tk_root):
    widgets.set_skin(THEMES["aurora"], 1.0, tkfont_default(), tkfont_default(), tkfont_default(), glass=False)

    assert widgets.control_image(tk_root, 40, 20, radius=4, top=(0, 0, 0), bot=(0, 0, 0),
                                 border=(0, 0, 0), bg=(0, 0, 0)) is None
    widgets.set_skin(THEMES["aurora"], 1.0, tkfont_default(), tkfont_default(), tkfont_default(), glass=True)


def test_botao_chama_o_comando(tk_root, skin):
    chamadas = []
    botao = widgets.GlassButton(tk_root, text="Ok", command=lambda: chamadas.append(1))
    botao.pack()

    botao.invoke()
    assert chamadas == [1]


def test_botao_desligado_nao_faz_nada(tk_root, skin):
    chamadas = []
    botao = widgets.GlassButton(tk_root, text="Ok", command=lambda: chamadas.append(1), state="disabled")
    botao.pack()

    botao.invoke()
    assert chamadas == []


def test_checkbox_alterna_a_variavel(tk_root, skin):
    var = tk.BooleanVar(value=False)
    check = widgets.GlassCheck(tk_root, text="Fazer", variable=var)
    check.pack()

    check.toggle()
    assert var.get() is True
    check.toggle()
    assert var.get() is False


def test_radio_escolhe_o_valor(tk_root, skin):
    var = tk.StringVar(value="a")
    primeiro = widgets.GlassRadio(tk_root, text="A", variable=var, value="a")
    segundo = widgets.GlassRadio(tk_root, text="B", variable=var, value="b")
    primeiro.pack()
    segundo.pack()

    segundo.toggle()
    assert var.get() == "b"


def test_botao_pinta_alguma_coisa(tk_root, skin):
    botao = widgets.GlassButton(tk_root, text="Ok", command=lambda: None)
    botao.pack()
    # a janela está escondida nos testes: simulamos o tamanho para forçar a pintura
    botao._cw, botao._ch = 80, 28
    botao._paint()

    assert botao.find_all(), "o botão não desenhou nada"


def test_campo_de_texto_aceita_texto(tk_root, skin):
    campo = widgets.GlassEntry(tk_root, width=20)
    campo.pack()
    campo.insert(0, "abc")

    assert campo.get() == "abc"
