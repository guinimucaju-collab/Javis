"""Testes da interface: páginas, tema, vidros, registros, exportação e backup."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from javis import ui as ui_module
from javis.ui import NAV_ITEMS, JavisApp


# --------------------------------------------------------------------------
# Estrutura
# --------------------------------------------------------------------------

def test_app_cria_uma_pagina_para_cada_item_do_menu(app):
    for chave, _rotulo in NAV_ITEMS:
        assert chave in app.pages, f"faltou a página {chave}"
        assert app.pages[chave].winfo_exists()


def test_lateral_tem_todos_os_itens(app):
    assert len(app.nav_buttons) == len(NAV_ITEMS)


def test_show_page_troca_a_pagina_ativa(app):
    for chave, _rotulo in NAV_ITEMS:
        app.show_page(chave)
        assert app.current_page == chave
        assert app.pages[chave].winfo_manager(), f"a página {chave} não ficou visível"


def test_o_app_abre_na_tela_de_captura(app):
    assert app.current_page == "capture"


def test_configuracoes_tem_o_escolhedor_de_tema_e_de_vidro(app):
    app.show_page("settings")
    assert app.theme_var.get() in ("aurora", "meia-noite", "aurora-clara")
    assert app.glass_var.get() in (True, False)


# --------------------------------------------------------------------------
# Tema
# --------------------------------------------------------------------------

def test_set_theme_muda_o_tema_e_salva(app, data_dir):
    app.set_theme("aurora-clara")

    assert app.theme_name == "aurora-clara"
    assert app.theme_var.get() == "aurora-clara"
    salvo = json.loads(data_dir.joinpath("estado.json").read_text(encoding="utf-8"))
    assert salvo["tema"] == "aurora-clara"


def test_o_app_abre_no_tema_escolhido(app, data_dir, monkeypatch):
    estado = json.loads(data_dir.joinpath("estado.json").read_text(encoding="utf-8"))
    estado["tema"] = "meia-noite"
    data_dir.joinpath("estado.json").write_text(json.dumps(estado), encoding="utf-8")

    novo = JavisApp(app.root)
    try:
        assert novo.theme_name == "meia-noite"
    finally:
        novo.root.destroy()


def test_tema_desconhecido_e_ignorado(app):
    antes = app.theme_name
    app.set_theme("tema-que-nao-existe")
    assert app.theme_name == antes


# --------------------------------------------------------------------------
# Registros
# --------------------------------------------------------------------------

def test_save_note_registra_e_limpa_a_caixa(app):
    app.auto_var.set(False)
    app.input_box.insert("1.0", "um registro de teste")

    app.save_note()

    assert len(app.state["notas"]) == 1
    assert app.state["notas"][0]["id"] == "N-001"
    assert app.state["notas"][0]["texto"] == "um registro de teste"
    assert app.input_box.get("1.0", "end").strip() == ""


def test_save_note_sem_texto_nao_registra_nada(app):
    app.auto_var.set(False)
    app.input_box.delete("1.0", "end")

    app.save_note()
    assert app.state["notas"] == []


def test_registros_aparecem_na_lista(app):
    app.auto_var.set(False)
    for texto in ("primeiro", "segundo"):
        app.input_box.insert("1.0", texto)
        app.save_note()

    ids = [item["id"] for item in app.state["notas"]]
    assert ids == ["N-001", "N-002"]
    assert app.notes_tree.get_children(), "a lista de registros ficou vazia"


# --------------------------------------------------------------------------
# Efeito de vidro
# --------------------------------------------------------------------------

def test_desligar_o_vidro_muda_o_desenho_do_fundo(app):
    app.glass_var.set(False)
    app.toggle_glass()

    assert app.glass_on is False
    assert app.state["vidro"] is False
    # sem vidro, o fundo é desenhado com retângulos (sem imagem da aurora)
    tipos = {app.backdrop.type(item) for item in app.backdrop.find_all()}
    assert "image" not in tipos, "o fundo ainda está usando a imagem do vidro"


def test_ligar_o_vidro_de_volta(app):
    app.glass_var.set(False)
    app.toggle_glass()
    app.glass_var.set(True)
    app.toggle_glass()

    assert app.glass_on is True
    assert app.state["vidro"] is True
    tipos = {app.backdrop.type(item) for item in app.backdrop.find_all()}
    assert "image" in tipos


def test_o_vidro_desligado_e_salvo_no_arquivo(app, data_dir):
    app.glass_var.set(False)
    app.toggle_glass()

    salvo = json.loads(data_dir.joinpath("estado.json").read_text(encoding="utf-8"))
    assert salvo["vidro"] is False


# --------------------------------------------------------------------------
# Exportação e backup
# --------------------------------------------------------------------------

def test_export_markdown_gera_arquivo(app, tmp_path, monkeypatch):
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro para exportar")
    app.save_note()

    destino = tmp_path / "exportacao.md"
    monkeypatch.setattr(ui_module.filedialog, "asksaveasfilename", lambda **kw: str(destino))

    app.export_markdown()

    texto = destino.read_text(encoding="utf-8")
    assert "# Javis" in texto
    assert "registro para exportar" in texto
    assert "## Decisões" in texto and "## Ações" in texto


def test_backup_zip_gera_arquivo_com_os_dados(app, tmp_path, monkeypatch):
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro para backup")
    app.save_note()

    destino = tmp_path / "backup.zip"
    monkeypatch.setattr(ui_module.filedialog, "asksaveasfilename", lambda **kw: str(destino))

    app.backup_zip()

    assert destino.exists()
    with zipfile.ZipFile(destino) as zf:
        assert zf.namelist(), "o zip veio vazio"


# --------------------------------------------------------------------------
# Robustez
# --------------------------------------------------------------------------

def test_o_app_abre_sem_numpy(tk_root, data_dir, monkeypatch):
    """Sem numpy o app tem de abrir, só que com o visual simples."""
    from javis import glass

    monkeypatch.setattr(glass, "np", None)
    app = JavisApp(tk_root)
    try:
        assert app.theme_name in ("aurora", "meia-noite", "aurora-clara")
        assert app.backdrop.find_all(), "o fundo não foi desenhado"
    finally:
        tk_root.destroy()


def test_estado_vazio_nao_quebra_a_interface(app, data_dir):
    """Um arquivo de estado com o conteúdo unexpected não pode derrubar o app."""
    data_dir.joinpath("estado.json").write_text('{"notas": "isso nao e lista", "acoes": 42}', encoding="utf-8")

    novo = JavisApp(app.root)
    try:
        assert novo.state["notas"] == []
        assert novo.state["acoes"] == []
    finally:
        novo.root.destroy()


def test_fechar_o_app_salva_o_rascunho(app, data_dir):
    app.input_box.insert("1.0", "rascunho em andamento")
    app.close()

    salvo = json.loads(data_dir.joinpath("estado.json").read_text(encoding="utf-8"))
    assert salvo["rascunho"] == "rascunho em andamento"


# --------------------------------------------------------------------------
# Plano
# --------------------------------------------------------------------------

def test_save_plan_grava_o_arquivo_e_guarda_a_versao_anterior(app, data_dir):
    app.plan_box.delete("1.0", "end")
    app.plan_box.insert("1.0", "# Plano novo\n\nconteúdo")

    app.save_plan(confirm=False)

    assert "# Plano novo" in data_dir.joinpath("Plano.md").read_text(encoding="utf-8")
    versoes = list((data_dir / "versoes_plano").glob("Plano_*.md"))
    assert versoes, "a versão anterior do plano não foi guardada"


def test_save_plan_sem_mudanca_nao_cria_versao(app, data_dir):
    app.save_plan(confirm=False)
    antes = len(list((data_dir / "versoes_plano").glob("Plano_*.md")))

    app.save_plan(confirm=False)

    assert len(list((data_dir / "versoes_plano").glob("Plano_*.md"))) == antes


def test_save_plan_vazio_avisa_e_nao_grava(app, data_dir):
    app.plan_box.delete("1.0", "end")
    app.save_plan(confirm=False)

    assert "vazio" in app.status.cget("text").lower()
    assert data_dir.joinpath("Plano.md").exists()


def test_reload_plan_recarrega_o_disco(app, data_dir):
    data_dir.joinpath("Plano.md").write_text("# Plano do disco\n", encoding="utf-8")

    app.reload_plan()
    assert "Plano do disco" in app.plan_box.get("1.0", "end")


# --------------------------------------------------------------------------
# Avisos, status e histórico
# --------------------------------------------------------------------------

def test_set_status_muda_o_texto(app):
    app.set_status("mensagem de teste", "ok")
    assert app.status.cget("text") == "mensagem de teste"


def test_toast_aparece_e_pode_ser_dispensado(app):
    app.toast("salvo", "ok")
    assert app._toast is not None

    app._dismiss_toast()
    assert app._toast is None


def test_historico_registra_os_eventos(app):
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")
    app.save_note()

    eventos = [h["evento"] for h in app.state["historico"]]
    assert any("N-001" in e for e in eventos)
    assert app.history_tree.get_children(), "o histórico ficou vazio"


def test_refresh_all_atualiza_as_listas(app):
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")
    app.save_note()

    app.refresh_all()
    assert app.notes_tree.get_children()


def test_contador_de_caracteres(app):
    app.input_box.insert("1.0", "12345")
    app._update_count()
    assert "5" in app.count_label.cget("text")
