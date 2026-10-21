"""Caminhos, constantes e limites do Javis."""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

APP_NAME = "Javis"
APP_VERSION = "4.0"

# O Javis só conversa com o Ollama neste computador. A variável abaixo existe
# para mudar a porta; qualquer endereço que não seja local é ignorado.
_DEFAULT_OLLAMA = "http://127.0.0.1:11434"


def ollama_base() -> str:
    base = os.environ.get("JAVIS_OLLAMA_URL", _DEFAULT_OLLAMA).rstrip("/")
    host = urllib.parse.urlparse(base).hostname
    return base if host in {"127.0.0.1", "localhost", "::1"} else _DEFAULT_OLLAMA


OLLAMA_URL = ollama_base() + "/api/chat"
OLLAMA_TAGS_URL = ollama_base() + "/api/tags"

LOCAL_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
DATA_DIR = Path(os.environ.get("JAVIS_DATA_DIR") or (LOCAL_DATA / "Javis"))
# Pasta antiga, mantida só para migrar os dados existentes uma única vez.
LEGACY_DATA_DIR = LOCAL_DATA / "JavisBismarck"
STATE_FILE = DATA_DIR / "estado_javis.json"
PLAN_FILE = DATA_DIR / "Plano_Javis.md"
BACKUP_DIR = DATA_DIR / "versoes_plano"
STATE_BACKUP_DIR = DATA_DIR / "backups_estado"
LOG_FILE = DATA_DIR / "javis.log"

MODEL = "qwen3:4b-instruct"
FALLBACK_MODEL = "qwen3:4b"
QUICK_MODEL = "qwen3:1.7b"

# Limites de crescimento e de contexto.
MAX_IMPORT_BYTES = 8 * 1024 * 1024
HISTORY_LIMIT = 2000
ANALYSIS_LIMIT = 500
PLAN_BACKUP_LIMIT = 200
STATE_BACKUP_KEEP = 7

# Janela de contexto do modelo, em tokens. O app nunca envia mais que isso:
# o Ollama trunca o começo da conversa em silêncio, o que produzia respostas
# incompletas sem aviso (relatado na análise de 19/10/2026).
CTX_QUICK = 6144
CTX_DEEP = 10240
PREDICT_QUICK = 300
PREDICT_DEEP = 900
# Estimativa conservadora de tokens por caractere em português.
CHARS_PER_TOKEN = 3.0
# Margem de segurança para o que a tokenização real fizer de diferente.
TOKEN_SAFETY = 0.88

STATUSES = ["a fazer", "em andamento", "concluída", "cancelada"]
PRIORITIES = ["alta", "média", "baixa"]
DATE_HINT = "Aceita AAAA-MM-DD, DD/MM/AAAA, hoje, amanhã ou +7 (dias a partir de hoje). Opcional."
