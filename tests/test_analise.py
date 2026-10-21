"""Testes do fluxo de análise: do pedido ao texto na tela e ao histórico."""

from __future__ import annotations

import time

import pytest

from javis import ui as ui_module

RESPOSTA = (
    "[RESUMO]\nUm resumo curto.\n"
    "[FATOS E EVIDÊNCIAS]\n- fato\n"
    "[POSSÍVEIS RELAÇÕES]\n- A-001: hipótese\n"
    "[RISCOS]\n- risco\n"
    "[PRÓXIMOS PASSOS]\n- passo\n"
    "[SUGESTÃO PARA O PLANO]\nTrocar o passo 2 por uma revisão.\n"
)


@pytest.fixture()
def ollama_falso(monkeypatch):
    """Substitui a chamada ao Ollama por uma resposta fixa."""
    chamadas = []

    def fake_stream(model_name, user_text, context_json, deep, cancel, put):
        chamadas.append({"modelo": model_name, "deep": deep, "contexto": context_json})
        put(("chunk", RESPOSTA))
        put(("done", ("pergunta de teste", RESPOSTA, "")))

    monkeypatch.setattr(ui_module.llm, "stream_chat", fake_stream)
    return chamadas


def _esperar(app, limite=5.0):
    """Deixa o app processar os eventos até a análise terminar."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        app.root.update()
        if not app.busy and app.analysis_result:
            break
        time.sleep(0.02)
    app.root.update()


def test_analise_mostra_o_resultado_e_guarda_no_historico(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.input_box.insert("1.0", "meu registro para analisar")

    app.analyze()
    _esperar(app)

    assert app.busy is False
    assert "Um resumo curto." in app.analysis_result
    assert "Um resumo curto." in app.analysis_box.get("1.0", "end")
    assert len(app.state["analises"]) == 1
    assert app.state["analises"][0]["id"] == "AN-001"


def test_analise_guarda_o_registro_e_marca_como_analisado(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro que vai ser analisado")

    app.analyze()
    _esperar(app)

    assert len(app.state["notas"]) == 1
    nota = app.state["notas"][0]
    assert nota["texto"] == "registro que vai ser analisado"
    assert nota["analisada"] is True


def test_analise_guarda_a_sugestao_para_o_plano(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")

    app.analyze()
    _esperar(app)

    assert "Trocar o passo 2" in app.plan_proposal


def test_analise_sem_sugestao_nao_ativa_o_botao_de_aprovacao(app, monkeypatch):
    resposta = RESPOSTA.replace("Trocar o passo 2 por uma revisão.", "Nenhuma atualização proposta.")

    def fake_stream(model_name, user_text, context_json, deep, cancel, put):
        put(("done", ("pergunta", resposta, "")))

    monkeypatch.setattr(ui_module.llm, "stream_chat", fake_stream)
    app.ollama_ready = True
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")

    app.analyze()
    _esperar(app)

    assert app.plan_proposal == ""


def test_analise_com_erro_do_ollama_mostra_a_mensagem(app, monkeypatch):
    def fake_stream(model_name, user_text, context_json, deep, cancel, put):
        put(("error", "Não consegui falar com o Ollama local."))

    monkeypatch.setattr(ui_module.llm, "stream_chat", fake_stream)
    app.ollama_ready = True
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")

    app.analyze()
    _esperar(app)

    assert app.busy is False
    assert "Ollama" in app.analysis_box.get("1.0", "end")
    assert app.state["analises"] == []


def test_analise_sem_ollama_pronto_nao_faz_nada(app, ollama_falso):
    app.ollama_ready = False
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")

    app.analyze()
    app.root.update()

    assert ollama_falso == []
    assert app.state["analises"] == []


def test_analise_aproveita_o_modelo_rapido_e_o_profundo(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)

    app.input_box.insert("1.0", "registro")
    app.analyze(deep=False)
    _esperar(app)

    app.input_box.insert("1.0", "outro registro")
    app.analyze(deep=True)
    _esperar(app)

    assert [c["deep"] for c in ollama_falso] == [False, True]
    assert all(c["contexto"] for c in ollama_falso)


def test_contexto_enviado_tem_o_plano_e_as_listas(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.input_box.insert("1.0", "registro")

    app.analyze()
    _esperar(app)

    contexto = ollama_falso[0]["contexto"]
    assert '"plano_atual"' in contexto
    assert '"registros_recentes"' in contexto


def test_relacao_sugerida_precisa_da_confirmacao_da_pessoa(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.state["acoes"].append({"id": "A-001", "texto": "ação relacionada", "status": "a fazer", "data": "2026-01-01"})
    app.input_box.insert("1.0", "registro que talvez seja da ação")

    app.analyze()
    _esperar(app)

    assert app.current_relation_id == "A-001"
    assert app.relation_frame.winfo_manager() == "grid"
    # nada é vinculado sem a confirmação
    assert app.state["relacoes"] == []


def test_confirmar_a_relacao_vincula_o_registro(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.state["acoes"].append({"id": "A-001", "texto": "ação relacionada", "status": "a fazer", "data": "2026-01-01"})
    app.input_box.insert("1.0", "registro que talvez seja da ação")

    app.analyze()
    _esperar(app)
    app.confirm_relation()

    assert len(app.state["relacoes"]) == 1
    assert app.state["relacoes"][0]["evento_id"] == "N-001"
    assert app.state["relacoes"][0]["relacionado_a"] == "A-001"
    assert app.state["relacoes"][0]["status"] == "confirmada"
    # o resultado também entra na ação
    assert app.state["acoes"][0]["resultados"]


def test_ignorar_a_relacao_deixa_o_registro_sem_vinculo(app, ollama_falso):
    app.ollama_ready = True
    app.auto_var.set(False)
    app.state["acoes"].append({"id": "A-001", "texto": "ação relacionada", "status": "a fazer", "data": "2026-01-01"})
    app.input_box.insert("1.0", "registro que talvez seja da ação")

    app.analyze()
    _esperar(app)
    app.ignore_relation()

    assert app.state["relacoes"][0]["status"] == "ignorada"
    assert not app.state["acoes"][0].get("resultados")
