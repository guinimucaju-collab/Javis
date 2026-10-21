"""Testes da persistência: estado, migrações, backups e datas."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from javis import storage
from javis.config import HISTORY_LIMIT
from javis.storage import (add_history, atomic_write, backup_plan, br_date, br_datetime, find_by_id,
                           initial_state, load_state, make_initial_plan, migrate_state, next_id,
                           parse_date, read_text_safe, rotate_state_backup, save_state)


# --------------------------------------------------------------------------
# Leitura e gravação do estado
# --------------------------------------------------------------------------

def test_load_state_cria_arquivos(data_dir):
    estado, aviso = load_state()

    assert aviso == ""
    assert data_dir.joinpath("estado.json").exists()
    assert data_dir.joinpath("Plano.md").exists()
    assert estado["notas"] == [] and estado["decisoes"] == []
    assert estado["projeto"] == "Javis"
    assert estado["plano"].startswith("# Plano")


def test_save_e_reload_preserva_o_que_salvo(data_dir):
    estado, _ = load_state()
    estado["notas"].append({"id": "N-001", "texto": "primeiro registro"})
    estado["objetivo"] = "objetivo de teste"
    save_state(estado)

    recarregado, _ = load_state()
    assert recarregado["notas"][0]["texto"] == "primeiro registro"
    assert recarregado["objetivo"] == "objetivo de teste"


def test_plano_no_disco_e_a_fonte_da_verdade(data_dir):
    """O .md do disco manda: o que está no estado não sobrescreve o arquivo."""
    estado, _ = load_state()
    estado["plano"] = "plano que só existe no estado"
    save_state(estado)

    recarregado, _ = load_state()
    assert recarregado["plano"] != "plano que só existe no estado"

    # ao salvar o plano de verdade, o arquivo é o que vale
    data_dir.joinpath("Plano.md").write_text("plano salvo no disco", encoding="utf-8")
    recarregado, _ = load_state()
    assert recarregado["plano"] == "plano salvo no disco"


def test_estado_corrompido_e_recuperado_do_backup(data_dir):
    estado, _ = load_state()
    estado["objetivo"] = "salvado no backup"
    save_state(estado)

    backups = data_dir / "backups_estado"
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "estado_20200101.json").write_text(json.dumps(estado), encoding="utf-8")
    data_dir.joinpath("estado.json").write_text("{ isso nao e json", encoding="utf-8")

    recarregado, aviso = load_state()
    assert "ilegível" in aviso
    assert recarregado["objetivo"] == "salvado no backup"
    # o arquivo quebrado é guardado, não apagado em silêncio
    assert any(p.name.startswith("estado_corrompido_") for p in data_dir.iterdir())


def test_atomic_write_nao_deixa_arquivo_temporario(data_dir):
    alvo = data_dir / "sub" / "arquivo.txt"
    atomic_write(alvo, "conteúdo")

    assert alvo.read_text(encoding="utf-8") == "conteúdo"
    assert list(alvo.parent.glob("*.tmp")) == []


def test_backup_diario_do_estado(data_dir):
    estado, _ = load_state()
    estado["objetivo"] = "x"
    save_state(estado)

    rotate_state_backup()
    backups = list((data_dir / "backups_estado").glob("estado_*.json"))
    assert backups, "o backup diário não foi criado"


def test_backup_do_plano_guarda_versao(data_dir):
    backup_plan("versão anterior do plano")

    versoes = list((data_dir / "versoes_plano").glob("Plano_*.md"))
    assert len(versoes) == 1
    assert versoes[0].read_text(encoding="utf-8") == "versão anterior do plano"


def test_backup_do_plano_ignora_texto_vazio(data_dir):
    backup_plan("")
    assert list((data_dir / "versoes_plano").glob("*.md")) == []


# --------------------------------------------------------------------------
# Migrações
# --------------------------------------------------------------------------

def test_migrate_state_preenche_campos_ausentes():
    estado = migrate_state({})

    assert estado["relacoes"] == []
    assert estado["decisoes"] == [] and estado["acoes"] == []
    assert estado["auto_analysis_enabled"] is True
    assert estado["ai_consent_local"] is True
    assert estado["vidro"] is True
    assert estado["versao"] == storage.STATE_VERSION


def test_migrate_state_troca_o_nome_antigo_do_projeto():
    estado = migrate_state({"projeto": "Plano Bismarck"})
    assert estado["projeto"] == "Javis"


def test_migrate_state_normaliza_relacoes_sem_status():
    estado = migrate_state({"relacoes": [{"a": "N-001", "b": "A-001"}]})
    assert estado["relacoes"][0]["status"] == "confirmada"


def test_load_state_descarta_listas_corrompidas(data_dir):
    estado, _ = load_state()
    estado["notas"] = "isto nao e uma lista"
    estado["acoes"] = {"id": "A-001"}
    save_state(estado)

    recarregado, _ = load_state()
    assert recarregado["notas"] == [] and recarregado["acoes"] == []


def test_migracao_da_pasta_antiga(data_dir, tmp_path, monkeypatch):
    """A pasta antiga (JavisBismarck) deve virar a pasta nova, sem perder dados."""
    antiga = tmp_path / "JavisBismarck"
    (antiga / "versoes_plano").mkdir(parents=True)
    (antiga / "estado_plano_bismarck.json").write_text(
        json.dumps({"projeto": "Plano Bismarck", "objetivo": "objetivo antigo"}), encoding="utf-8")
    (antiga / "Plano_Bismarck.md").write_text("# Plano Bismarck\n\nconteúdo", encoding="utf-8")
    (antiga / "versoes_plano" / "Plano_Bismarck_20200101_000000_000000.md").write_text("v1", encoding="utf-8")

    monkeypatch.setattr(storage, "LEGACY_DATA_DIR", antiga)
    monkeypatch.setattr(storage, "LEGACY_STATE_FILE", antiga / "estado_plano_bismarck.json")
    monkeypatch.setattr(storage, "LEGACY_PLAN_FILE", antiga / "Plano_Bismarck.md")

    aviso = storage.migrate_legacy_data()

    assert "JavisBismarck" in aviso and "Javis" in aviso
    assert data_dir.joinpath("estado.json").exists()
    assert data_dir.joinpath("Plano.md").read_text(encoding="utf-8").startswith("# Plano Bismarck")
    # as versões antigas do plano também migram, com o nome novo
    assert list((data_dir / "versoes_plano").glob("Plano_*.md"))
    assert not antiga.exists()


def test_migracao_não_roda_de_novo_quando_os_dados_novos_já_existem(data_dir, tmp_path, monkeypatch):
    """Depois da primeira migração, a pasta antiga não pode ser mexida de novo."""
    antiga = tmp_path / "JavisBismarck"
    antiga.mkdir()
    (antiga / "estado_plano_bismarck.json").write_text('{"objetivo": "antigo"}', encoding="utf-8")
    monkeypatch.setattr(storage, "LEGACY_DATA_DIR", antiga)
    monkeypatch.setattr(storage, "LEGACY_STATE_FILE", antiga / "estado_plano_bismarck.json")
    monkeypatch.setattr(storage, "LEGACY_PLAN_FILE", antiga / "Plano_Bismarck.md")

    load_state()  # primeira abertura: migra e cria os dados novos
    assert data_dir.joinpath("estado.json").exists()

    outra = tmp_path / "JavisBismarck2"
    outra.mkdir()
    (outra / "estado_plano_bismarck.json").write_text('{"objetivo": "outro"}', encoding="utf-8")
    monkeypatch.setattr(storage, "LEGACY_DATA_DIR", outra)
    monkeypatch.setattr(storage, "LEGACY_STATE_FILE", outra / "estado_plano_bismarck.json")

    assert storage.migrate_legacy_data() == ""
    assert outra.exists(), "a pasta antiga não pode ser apagada se os dados novos já existem"
    assert json.loads(data_dir.joinpath("estado.json").read_text(encoding="utf-8"))["objetivo"] == "antigo"


def test_plano_antigo_ganha_o_titulo_novo(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.joinpath("Plano.md").write_text("# Plano Bismarck\n\n## Objetivo\n\ntexto", encoding="utf-8")

    estado, _ = load_state()
    assert estado["plano"].startswith("# Plano")
    assert "Bismarck" not in estado["plano"]


# --------------------------------------------------------------------------
# Regras de negócio pequenas
# --------------------------------------------------------------------------

def test_initial_state_tem_os_campos_esperados():
    estado = initial_state()
    for campo in ("notas", "decisoes", "acoes", "relacoes", "analises", "historico"):
        assert estado[campo] == []
    assert estado["projeto"] == "Javis"


def test_make_initial_plan_inclui_as_decisoes():
    estado = initial_state()
    estado["decisoes"] = [{"id": "D-001", "texto": "decidir X", "status": "vigente", "data": "2026-01-01"}]

    plano = make_initial_plan(estado)
    assert "D-001" in plano and "decidir X" in plano
    assert "JAVIS:DECISOES:INICIO" in plano and "JAVIS:DECISOES:FIM" in plano


def test_next_id_continua_a_sequencia():
    assert next_id("N", []) == "N-001"
    assert next_id("N", [{"id": "N-001"}, {"id": "N-007"}]) == "N-008"
    assert next_id("A", [{"id": "N-001"}]) == "A-001"


def test_find_by_id():
    notas = [{"id": "N-001", "texto": "a"}, {"id": "N-002", "texto": "b"}]
    assert find_by_id(notas, "N-002")["texto"] == "b"
    assert find_by_id(notas, "N-999") is None
    assert find_by_id(notas, None) is None


def test_add_history_corta_o_que_passou_do_limite():
    estado = initial_state()
    for i in range(HISTORY_LIMIT + 25):
        add_history(estado, f"evento {i}")

    assert len(estado["historico"]) == HISTORY_LIMIT
    assert estado["historico"][-1]["evento"] == f"evento {HISTORY_LIMIT + 24}"


# --------------------------------------------------------------------------
# Datas
# --------------------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("hoje", date.today().isoformat()),
    ("HOJE", date.today().isoformat()),
    ("amanhã", (date.today() + timedelta(days=1)).isoformat()),
    ("amanha", (date.today() + timedelta(days=1)).isoformat()),
    ("+7", (date.today() + timedelta(days=7)).isoformat()),
    ("+0", date.today().isoformat()),
    ("2026-01-31", "2026-01-31"),
    ("31/01/2026", "2026-01-31"),
    ("31.01.26", "2026-01-31"),
])
def test_parse_date_aceita_os_formatos_do_ajuda(entrada, esperado):
    assert parse_date(entrada) == esperado


@pytest.mark.parametrize("entrada", ["31/02/2026", "amanhã depois", "2026-13-01", "abc"])
def test_parse_date_rejeita_entradas_invalidas(entrada):
    with pytest.raises(ValueError):
        parse_date(entrada)


def test_parse_date_com_texto_vazio_devolve_vazio():
    assert parse_date("") == ""
    assert parse_date("   ") == ""


def test_parse_date_aceita_data_inexistente_com_erro():
    with pytest.raises(ValueError):
        parse_date("2026-02-30")


def test_br_date_e_br_datetime():
    assert br_date("2026-01-31T10:20:00") == "31/01/2026"
    assert br_date(None) == ""
    assert br_datetime("2026-01-31T10:20:00") == "31/01/2026 10:20"
    assert br_datetime("2026-01-31") == "31/01/2026"


def test_read_text_safe_lê_utf8_e_cp1252(tmp_path):
    utf8 = tmp_path / "a.txt"
    utf8.write_text("acentuação", encoding="utf-8")
    assert read_text_safe(utf8) == "acentuação"

    cp = tmp_path / "b.txt"
    cp.write_bytes("acentuação".encode("cp1252"))
    assert read_text_safe(cp) == "acentuação"
