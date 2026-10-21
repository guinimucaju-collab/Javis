"""Testes doBudget de contexto, dos prompts e da leitura das respostas."""

from __future__ import annotations

from javis.config import CTX_QUICK, PREDICT_QUICK
from javis.llm import (SYSTEM_DEEP, SYSTEM_QUICK, ContextBudget, build_context, clip_middle,
                       compact_json, estimate_tokens, extract_proposal, extract_relation_candidate,
                       extract_relation_section)


def _estado():
    return {
        "objetivo": "objetivo",
        "notas": [{"id": f"N-{i:03d}", "texto": f"registro {i} " * 20} for i in range(1, 8)],
        "acoes": [{"id": f"A-{i:03d}", "texto": f"ação {i}", "status": "a fazer"} for i in range(1, 5)],
        "decisoes": [{"id": f"D-{i:03d}", "texto": f"decisão {i}", "status": "vigente"} for i in range(1, 4)],
        "relacoes": [{"id": "R-001", "status": "confirmada", "nota": "N-001", "acao": "A-001"}],
        "plano": "plano " * 200,
    }


# --------------------------------------------------------------------------
# Orçamento de tokens
# --------------------------------------------------------------------------

def test_estimate_tokens_cresce_com_o_texto():
    assert estimate_tokens("a" * 300) > estimate_tokens("a" * 30)
    assert estimate_tokens("") > 0


def test_clip_middle_mantem_comeco_e_fim():
    texto = "INICIO " + ("x" * 500) + " FIM"
    cortado = clip_middle(texto, 100)

    assert len(cortado) <= 110
    assert cortado.startswith("INICIO")
    assert cortado.endswith("FIM")
    assert "[…]" in cortado


def test_clip_middle_nao_toca_texto_curto():
    assert clip_middle("curto", 100) == "curto"


def test_budget_reserva_espaco_para_o_prompt():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)

    assert budget.remaining < CTX_QUICK
    assert budget.remaining >= 600
    assert budget.dropped == []


def test_budget_registra_o_que_foi_cortado():
    budget = ContextBudget(2000, 500, SYSTEM_QUICK)
    budget.take("plano", "x" * 100000, 8000)

    assert "plano" in budget.dropped
    assert budget.summary().startswith("Contexto reduzido")


def test_budget_reserve_devolve_zero_quando_nao_ha_espaco():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)
    budget.reserve("tudo", 10_000_000)

    assert budget.remaining <= budget.start


def test_budget_reserve_diminui_o_que_sobra():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)
    antes = budget.remaining
    budget.reserve("ações", 700)

    assert budget.remaining < antes


# --------------------------------------------------------------------------
# Montagem do contexto
# --------------------------------------------------------------------------

def test_build_context_tem_as_partes_esperadas():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)
    contexto = build_context(_estado(), "plano", None, False, budget)

    for chave in ("objetivo", "plano_atual", "decisoes_vigentes", "acoes",
                  "registros_recentes", "registro_em_foco", "relacoes_confirmadas"):
        assert chave in contexto
    assert contexto["registro_em_foco"] is None


def test_build_context_pega_o_registro_em_foco():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)
    contexto = build_context(_estado(), "plano", "N-003", False, budget)

    assert contexto["registro_em_foco"]["id"] == "N-003"
    assert "N-003" not in [n["id"] for n in contexto["registros_recentes"]]


def test_build_context_respeita_o_orcamento():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)
    contexto = build_context(_estado(), "plano " * 5000, None, False, budget)

    # o contexto serializado precisa caber na janela do modelo
    assert len(compact_json(contexto)) < CTX_QUICK * 4


def test_build_context_considera_acoes_e_decisoes():
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)
    contexto = build_context(_estado(), "plano", None, True, budget)

    assert contexto["acoes"], "nenhuma ação entrou no contexto"
    assert contexto["decisoes_vigentes"], "nenhuma decisão vigente entrou no contexto"


def test_build_context_ignora_relacao_nao_confirmada():
    estado = _estado()
    estado["relacoes"] = [{"id": "R-002", "status": "hipotetica"}]
    budget = ContextBudget(CTX_QUICK, PREDICT_QUICK, SYSTEM_QUICK)

    contexto = build_context(estado, "plano", None, False, budget)
    assert contexto["relacoes_confirmadas"] == []


def test_compact_json_nao_tem_espacos():
    assert compact_json({"a": 1, "b": "x"}) == '{"a":1,"b":"x"}'


# --------------------------------------------------------------------------
# Leitura das respostas do modelo
# --------------------------------------------------------------------------

def test_extract_relation_candidate_acha_o_id():
    texto = "[RESUMO]\nnada\n[POSSÍVEIS RELAÇÕES]\nTalvez A-001 e N-002\n[RISCOS]\nnada"
    achado = extract_relation_candidate(texto, "N-001", {"A-001", "N-002"}, set())

    assert achado == "A-001"


def test_extract_relation_candidate_ignora_o_proprio_id():
    texto = "[POSSÍVEIS RELAÇÕES]\nN-001 e A-002"
    achado = extract_relation_candidate(texto, "N-001", {"N-001", "A-002"}, set())

    assert achado == "A-002"


def test_extract_relation_candidate_ignora_id_desconhecido():
    texto = "[POSSÍVEIS RELAÇÕES]\nA-999"
    assert extract_relation_candidate(texto, "N-001", {"A-001"}, set()) is None


def test_extract_relation_candidate_ignora_par_ja_tratado():
    texto = "[POSSÍVEIS RELAÇÕES]\nA-001"
    achado = extract_relation_candidate(texto, "N-001", {"A-001"}, {("N-001", "A-001")})

    assert achado is None


def test_extract_relation_candidate_sem_registro_atual():
    assert extract_relation_candidate("[POSSÍVEIS RELAÇÕES]\nA-001", None, {"A-001"}, set()) is None


def test_extract_relation_section():
    texto = "[POSSÍVEIS RELAÇÕES]\n- A-001: hipótese\n[RISCOS]\n- risco"
    secao = extract_relation_section(texto)

    assert "A-001" in secao
    assert "RISCOS" not in secao


def test_extract_relation_section_sem_secao():
    assert extract_relation_section("texto solto") == ""


def test_extract_proposal():
    texto = "[SUGESTÃO PARA O PLANO]\nTrocar o passo 2 por uma revisão.\n"
    assert "revisão" in extract_proposal(texto)


def test_extract_proposal_trata_resposta_vazia():
    texto = "[SUGESTÃO PARA O PLANO]\nNenhuma atualização proposta."
    assert extract_proposal(texto) == ""


def test_extract_proposal_sem_secao():
    assert extract_proposal("nada aqui") == ""


def test_prompts_nao_prometem_que_ja_salvaram():
    for prompt in (SYSTEM_QUICK, SYSTEM_DEEP):
        assert "Plano Bismarck" not in prompt
        assert "Nunca diga que salvou" in prompt


# --------------------------------------------------------------------------
# Protocolo de eventos com a interface
# --------------------------------------------------------------------------

class _RespostaFalsa:
    """Resposta SSE falsa do Ollama."""

    def __init__(self, linhas):
        self._linhas = linhas

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._linhas)


def test_stream_chat_entrega_chunk_e_done_com_pergunta_e_resposta(monkeypatch):
    import json
    import threading

    from javis import llm

    linhas = [
        json.dumps({"message": {"content": "parte 1 "}}).encode(),
        json.dumps({"message": {"content": "parte 2"}, "done": True}).encode(),
    ]
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: _RespostaFalsa(linhas))

    eventos = []
    llm.stream_chat("modelo", {"id": "N-001", "texto": "minha pergunta"}, "{}", False,
                    threading.Event(), eventos.append)

    assert [e[0] for e in eventos] == ["chunk", "chunk", "done"]
    # o "done" precisa levar (pergunta, resposta, erro): a interface usa a
    # pergunta para guardar a análise no histórico
    payload = eventos[-1][1]
    assert isinstance(payload, tuple) and len(payload) == 3
    assert payload[0] == "minha pergunta"
    assert "parte 1 parte 2" in payload[1]
    assert payload[2] == ""


def test_stream_chat_entrega_erro_quando_o_ollama_nao_responde(monkeypatch):
    import threading
    import urllib.error

    from javis import llm

    def falha(*args, **kwargs):
        raise urllib.error.URLError("conexão recusada")

    monkeypatch.setattr(llm.urllib.request, "urlopen", falha)

    eventos = []
    llm.stream_chat("modelo", {"id": "N-001", "texto": "pergunta"}, "{}", False,
                    threading.Event(), eventos.append)

    assert eventos and eventos[-1][0] == "error"
    assert "Ollama" in eventos[-1][1]


def test_stream_chat_para_quando_o_cancelamento_e_acionado(monkeypatch):
    import json
    import threading

    from javis import llm

    linhas = [json.dumps({"message": {"content": "trecho"}}).encode()]
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *a, **k: _RespostaFalsa(linhas))

    cancel = threading.Event()
    cancel.set()
    eventos = []
    llm.stream_chat("modelo", {"id": "N-001", "texto": "pergunta"}, "{}", False, cancel, eventos.append)

    assert [e[0] for e in eventos] == []
