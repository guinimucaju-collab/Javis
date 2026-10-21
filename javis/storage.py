"""Persistência do estado do Javis: leitura, gravação, migração e backups."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import date, datetime
from pathlib import Path

from .config import (
    ANALYSIS_LIMIT,
    DATA_DIR,
    HISTORY_LIMIT,
    LEGACY_DATA_DIR,
    LEGACY_PLAN_FILE,
    LEGACY_STATE_FILE,
    LOG_FILE,
    PLAN_BACKUP_LIMIT,
    PLAN_FILE,
    STATE_BACKUP_DIR,
    STATE_BACKUP_KEEP,
    STATE_FILE,
    BACKUP_DIR,
)

log = logging.getLogger("javis")

STATE_VERSION = 3


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def br_date(value: str | None) -> str:
    try:
        return date.fromisoformat((value or "")[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return value or ""


def br_datetime(value: str | None) -> str:
    return f"{br_date(value)} {(value or '')[11:16]}".strip()


def parse_date(text: str) -> str:
    """Converte a data digitada para AAAA-MM-DD. Vazio devolve ''. Inválido levanta ValueError."""
    import re

    raw = (text or "").strip().lower()
    if not raw:
        return ""
    today = date.today()
    if raw == "hoje":
        return today.isoformat()
    if raw in {"amanhã", "amanha"}:
        return (today + _one_day()).isoformat()
    match = re.fullmatch(r"\+(\d{1,4})\s*d?", raw)
    if match:
        return (today + _one_day() * int(match.group(1))).isoformat()
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if match:
        y, m, d = map(int, match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?", raw)
        if not match:
            raise ValueError(f"Data não reconhecida: {text!r}")
        d, m = int(match.group(1)), int(match.group(2))
        y = int(match.group(3)) if match.group(3) else today.year
        if y < 100:
            y += 2000
    return date(y, m, d).isoformat()  # ValueError se o dia não existir


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def read_text_safe(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def find_by_id(records: list, record_id: str | None) -> dict | None:
    return next((r for r in records if r.get("id") == record_id), None)


def next_id(prefix: str, records: list) -> str:
    nums = []
    for item in records:
        try:
            nums.append(int(str(item.get("id", "")).split("-")[-1]))
        except (ValueError, AttributeError):
            pass
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def add_history(state: dict, text: str) -> None:
    state["historico"].append({"data": now_iso(), "evento": text})
    if len(state["historico"]) > HISTORY_LIMIT:
        del state["historico"][: len(state["historico"]) - HISTORY_LIMIT]


def initial_state() -> dict:
    return {
        "projeto": "Javis",
        "visao": "Javis como segundo cérebro operacional: registra contexto, analisa, sugere próximos passos e atualiza decisões confirmadas pela pessoa.",
        "objetivo": "",
        "notas": [],
        "decisoes": [],
        "acoes": [],
        "relacoes": [],
        "analises": [],
        "historico": [],
        "auto_analysis_enabled": True,
        "ai_consent_local": True,
        "versao": STATE_VERSION,
    }


def make_initial_plan(state: dict) -> str:
    parts = ["# Plano", "", "## Objetivo", "", state.get("objetivo") or "Defina aqui o objetivo principal do plano.",
             "", "## Plano de trabalho", "", "Registre neste arquivo as frentes, prioridades e critérios de sucesso.",
             "", "## Atualizações aprovadas", "", "<!-- JAVIS:DECISOES:INICIO -->", "## Decisões", ""]
    decisions = state.get("decisoes", [])
    if decisions:
        for item in decisions:
            parts.append(f"- **{item.get('id', '')}** — {item.get('texto', '')}  ")
            parts.append(f"  Status: {item.get('status', 'vigente')} · Registrada: {item.get('data', '')[:10]}")
            if item.get("motivo"):
                parts.append(f"  Motivo: {item.get('motivo')}")
    else:
        parts.append("- Nenhuma decisão registrada.")
    parts += ["", "<!-- JAVIS:DECISOES:FIM -->", ""]
    return "\n".join(parts)


def migrate_state(state: dict) -> dict:
    """Leva estados de versões antigas para o formato atual.

    O arquivo pode ter sido gravado pela versão 2 (sem 'relacoes') ou pela 1
    (sem 'relacoes', 'auto_analysis_enabled' e 'ai_consent_local'). Sem esta
    passagem, os campos ausentes simplesmente sumiriam do painel.
    """
    state.setdefault("relacoes", [])
    state.setdefault("auto_analysis_enabled", True)
    state.setdefault("ai_consent_local", True)
    state.setdefault("decisoes", [])
    state.setdefault("acoes", [])
    state.setdefault("analises", [])
    state.setdefault("historico", [])
    state.setdefault("vidro", True)   # efeito de vidro ligado por padrão
    # Estados antigos ainda traziam o nome antigo do projeto.
    if state.get("projeto") in {"Plano Bismarck", "Bismarck"}:
        state["projeto"] = "Javis"
    # Arquivos antigos vinham sem 'status' em cada relação.
    for relation in state.get("relacoes", []):
        if isinstance(relation, dict) and "status" not in relation:
            relation["status"] = "confirmada"
    state["versao"] = STATE_VERSION
    return state


def _read_state_file(path: Path) -> dict:
    saved = json.loads(read_text_safe(path))
    if not isinstance(saved, dict):
        raise ValueError("O arquivo de estado não é um objeto JSON.")
    return saved


def migrate_legacy_data() -> str:
    """Move os dados da pasta antiga (JavisBismarck) para a pasta do Javis.

    Só roda quando a pasta nova ainda não tem dados. Devolve uma aviso para o
    app mostrar, ou string vazia.
    """
    if not LEGACY_DATA_DIR.exists() or STATE_FILE.exists():
        return ""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LEGACY_STATE_FILE.exists():
            shutil.move(str(LEGACY_STATE_FILE), str(STATE_FILE))
        if LEGACY_PLAN_FILE.exists():
            shutil.move(str(LEGACY_PLAN_FILE), str(PLAN_FILE))
        old_versions = LEGACY_DATA_DIR / "versoes_plano"
        if old_versions.exists():
            old_versions.mkdir(parents=True, exist_ok=True)
            for item in old_versions.glob("Plano_Bismarck_*.md"):
                item.rename(old_versions / item.name.replace("Plano_Bismarck_", "Plano_"))
            shutil.rmtree(old_versions, ignore_errors=True)
        for folder in ("backups_estado",):
            old_folder = LEGACY_DATA_DIR / folder
            if old_folder.exists():
                shutil.copytree(old_folder, DATA_DIR / folder, dirs_exist_ok=True)
        log_file = LEGACY_DATA_DIR / "javis.log"
        if log_file.exists():
            shutil.copy2(str(log_file), str(LOG_FILE))
        shutil.rmtree(LEGACY_DATA_DIR, ignore_errors=True)
        return f"Os seus dados foram movidos de {LEGACY_DATA_DIR.name} para {DATA_DIR.name}."
    except OSError:
        log.exception("Falha ao migrar os dados da pasta antiga")
        return ""


def load_state() -> tuple[dict, str]:
    """Carrega o estado. Se o arquivo estiver corrompido, guarda uma cópia e tenta o backup mais recente."""
    notice = migrate_legacy_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = initial_state()
    if STATE_FILE.exists():
        try:
            state.update(_read_state_file(STATE_FILE))
        except (ValueError, OSError) as exc:
            log.exception("Estado ilegível")
            broken = STATE_FILE.with_name(f"estado_corrompido_{datetime.now():%Y%m%d_%H%M%S}.json")
            try:
                STATE_FILE.replace(broken)
            except OSError:
                pass
            notice = f"O arquivo de dados estava ilegível e foi guardado como {broken.name}. ({exc})"
            for backup in sorted(STATE_BACKUP_DIR.glob("estado_*.json"), reverse=True):
                try:
                    state.update(_read_state_file(backup))
                    notice += f" Recuperei os dados do backup {backup.name}."
                    break
                except (ValueError, OSError):
                    continue
    state = migrate_state(state)
    for key in ("notas", "decisoes", "acoes", "relacoes", "analises", "historico"):
        value = state.get(key)
        state[key] = [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []
    if PLAN_FILE.exists():
        state["plano"] = read_text_safe(PLAN_FILE)  # o .md editável é a fonte da verdade
        # Planos escritos pela versão antiga ainda começavam com o nome antigo.
        if state["plano"].lstrip().startswith("# Plano Bismarck"):
            state["plano"] = state["plano"].replace("# Plano Bismarck", "# Plano", 1)
            try:
                PLAN_FILE.write_text(state["plano"], encoding="utf-8")
            except OSError:
                log.exception("Falha ao renomear o título do plano")
    else:
        state["plano"] = state.get("plano") or make_initial_plan(state)
        PLAN_FILE.write_text(state["plano"], encoding="utf-8")
    return state, notice


def save_state(state: dict) -> None:
    if len(state.get("analises", [])) > ANALYSIS_LIMIT:
        del state["analises"][: len(state["analises"]) - ANALYSIS_LIMIT]
    atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False, separators=(",", ":")))


def rotate_state_backup() -> None:
    """Uma cópia do estado por dia; mantém as mais recentes."""
    try:
        if not STATE_FILE.exists():
            return
        STATE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target = STATE_BACKUP_DIR / f"estado_{datetime.now():%Y%m%d}.json"
        if not target.exists():
            target.write_bytes(STATE_FILE.read_bytes())
        for old in sorted(STATE_BACKUP_DIR.glob("estado_*.json"), reverse=True)[STATE_BACKUP_KEEP:]:
            old.unlink(missing_ok=True)
    except OSError:
        log.exception("Falha ao rodar backup do estado")


def backup_plan(previous: str) -> None:
    """Guarda a versão anterior do plano e descarta as mais antigas."""
    if not previous:
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(BACKUP_DIR / f"Plano_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.md", previous)
    for old in sorted(BACKUP_DIR.glob("Plano_*.md"), reverse=True)[PLAN_BACKUP_LIMIT:]:
        old.unlink(missing_ok=True)
