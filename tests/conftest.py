"""Configuração dos testes do Javis.

Os dados de teste ficam numa pasta temporária: `javis.config` lê a variável
de ambiente `JAVIS_DATA_DIR` no momento da importação, então ela precisa estar
definida ANTES de qualquer `import javis.*`. Por isso o ajuste acontece aqui,
no conftest, que o pytest carrega antes dos testes.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import tkinter as tk
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="javis_teste_"))
os.environ["JAVIS_DATA_DIR"] = str(TEST_DATA_DIR)
# Não tenta falar com o Ollama durante os testes.
os.environ.setdefault("JAVIS_OLLAMA_URL", "http://127.0.0.1:11434")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture()
def data_dir(monkeypatch) -> Path:
    """Pasta de dados limpa para cada teste.

    Os módulos importam os caminhos por valor (`from .config import ...`), então
    é preciso redirecionar cada cópia, não só o módulo `config`.
    """
    from javis import config, storage

    target = Path(tempfile.mkdtemp(prefix="javis_dados_"))
    novos = {
        "DATA_DIR": target,
        "STATE_FILE": target / "estado.json",
        "PLAN_FILE": target / "Plano.md",
        "BACKUP_DIR": target / "versoes_plano",
        "STATE_BACKUP_DIR": target / "backups_estado",
        "LOG_FILE": target / "javis.log",
    }
    for module in (config, storage):
        for nome, valor in novos.items():
            if hasattr(module, nome):
                monkeypatch.setattr(module, nome, valor)
    try:
        import javis.ui as ui

        for nome, valor in novos.items():
            if hasattr(ui, nome):
                monkeypatch.setattr(ui, nome, valor)
    except Exception:  # pragma: no cover - a UI pode não importar sem display
        pass
    try:
        yield target
    finally:
        shutil.rmtree(target, ignore_errors=True)


@pytest.fixture()
def tk_root():
    """Raiz do Tk (precisa de uma sessão gráfica; no CI sem desktop, é pulado)."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - só acontece sem display
        pytest.skip(f"sem display disponível: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture()
def app(tk_root, data_dir):
    """Aplicação completa, com a janela escondida e dados temporários."""
    from javis.ui import JavisApp

    instance = JavisApp(tk_root)
    yield instance
    try:
        tk_root.destroy()
    except tk.TclError:
        pass
