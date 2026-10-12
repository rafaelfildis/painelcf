"""Armazenamento em SQLite (dados/teses.db)."""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import classificador
from .classificador import Analise
from .config import RAIZ, Config
from .empresas import PJ, eh_empresa_alias, nome_canonico, tipo_parte
from .texto import limpar_html

BANCO_PADRAO = RAIZ / "dados" / "teses.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS sentencas (
    id                   INTEGER PRIMARY KEY,   -- id da comunicação no DJEN
    hash                 TEXT,
    data_disponibilizacao TEXT NOT NULL,
    numero_processo      TEXT NOT NULL,
    processo_mascara     TEXT,
    orgao                TEXT,
    classe               TEXT,
    tipo_documento       TEXT,
    link                 TEXT,
    texto                TEXT,
    bruto                TEXT,                  -- JSON original da comunicação
    rito                 TEXT,
    resultado            TEXT,
    comarca              TEXT,
    codigo_origem        TEXT,
    juiz                 TEXT,
    juiz_leigo           TEXT,
    dano_moral           REAL,
    repeticao_dobro      INTEGER,
    inexistencia_debito  INTEGER,
    temas                TEXT,                  -- JSON (lista)
    versao_classificador INTEGER,
    coletado_em          TEXT
);
CREATE INDEX IF NOT EXISTS ix_sent_data ON sentencas(data_disponibilizacao);
CREATE INDEX IF NOT EXISTS ix_sent_proc ON sentencas(numero_processo);

CREATE TABLE IF NOT EXISTS partes (
    sentenca_id  INTEGER NOT NULL REFERENCES sentencas(id) ON DELETE CASCADE,
    nome         TEXT NOT NULL,
    polo         TEXT,
    tipo         TEXT,          -- pj | pf | publico
    empresa      TEXT,          -- nome unificado (somente polo passivo PJ)
    PRIMARY KEY (sentenca_id, nome, polo)
);
CREATE INDEX IF NOT EXISTS ix_partes_empresa ON partes(empresa);

CREATE TABLE IF NOT EXISTS coletas (
    data           TEXT PRIMARY KEY,
    total_api      INTEGER,
    sentencas      INTEGER,
    status         TEXT,        -- ok | erro
    mensagem       TEXT,
    executado_em   TEXT
);

-- Uma linha por processo: a sentença de mérito/terminativa mais recente.
-- Evita contar duas vezes a mesma sentença republicada ou intimada em datas diferentes.
CREATE VIEW IF NOT EXISTS sentencas_unicas AS
SELECT s.* FROM sentencas s
WHERE s.resultado NOT IN ('EMBARGOS_DECLARACAO', 'INDEFINIDO')
  AND s.id = (
    SELECT s2.id FROM sentencas s2
    WHERE s2.numero_processo = s.numero_processo
      AND s2.resultado NOT IN ('EMBARGOS_DECLARACAO', 'INDEFINIDO')
    ORDER BY s2.data_disponibilizacao DESC, s2.id DESC LIMIT 1
  );
"""


def conectar(caminho: Path | str | None = None) -> sqlite3.Connection:
    caminho = Path(caminho) if caminho else BANCO_PADRAO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(_ESQUEMA)
    return con


def _data_iso(item: dict) -> str:
    bruto = item.get("data_disponibilizacao") or item.get("datadisponibilizacao") or ""
    bruto = str(bruto)[:10]
    if "/" in bruto:
        d, m, a = bruto.split("/")
        return f"{a}-{m}-{d}"
    return bruto


def salvar(con: sqlite3.Connection, item: dict, analise: Analise, cfg: Config) -> None:
    sid = int(item["id"])
    numero = str(item.get("numero_processo") or "")
    con.execute(
        """INSERT OR REPLACE INTO sentencas
           (id, hash, data_disponibilizacao, numero_processo, processo_mascara, orgao, classe,
            tipo_documento, link, texto, bruto, rito, resultado, comarca, codigo_origem, juiz, juiz_leigo,
            dano_moral, repeticao_dobro, inexistencia_debito, temas, versao_classificador, coletado_em)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            sid, item.get("hash"), _data_iso(item), numero, item.get("numeroprocessocommascara"),
            item.get("nomeOrgao"), item.get("nomeClasse"), item.get("tipoDocumento"), item.get("link"),
            limpar_html(item.get("texto")), json.dumps(item, ensure_ascii=False),
            analise.rito, analise.resultado, analise.comarca, classificador.codigo_origem(numero),
            analise.juiz, analise.juiz_leigo, analise.dano_moral, int(analise.repeticao_dobro),
            int(analise.inexistencia_debito), json.dumps(analise.temas, ensure_ascii=False),
            classificador.VERSAO, datetime.now().isoformat(timespec="seconds"),
        ),
    )
    con.execute("DELETE FROM partes WHERE sentenca_id = ?", (sid,))
    for dest in item.get("destinatarios") or []:
        nome = (dest.get("nome") or "").strip()
        if not nome:
            continue
        polo = (dest.get("polo") or "").strip().upper()[:1] or None
        tipo = PJ if eh_empresa_alias(nome, cfg) else tipo_parte(nome)
        empresa = nome_canonico(nome, cfg) if (polo == "P" and tipo == PJ) else None
        con.execute(
            "INSERT OR IGNORE INTO partes (sentenca_id, nome, polo, tipo, empresa) VALUES (?,?,?,?,?)",
            (sid, nome, polo, tipo, empresa),
        )


def preencher_comarcas_por_codigo(con: sqlite3.Connection) -> int:
    """Completa comarcas não identificadas pelo nome do órgão usando o código de origem do processo,
    a partir de outras sentenças do mesmo código cuja comarca já é conhecida."""
    cur = con.execute(
        """UPDATE sentencas SET comarca = (
               SELECT s2.comarca FROM sentencas s2
               WHERE s2.codigo_origem = sentencas.codigo_origem AND s2.comarca IS NOT NULL
               GROUP BY s2.comarca ORDER BY COUNT(*) DESC LIMIT 1)
           WHERE comarca IS NULL AND codigo_origem IS NOT NULL"""
    )
    return cur.rowcount


def registrar_coleta(con: sqlite3.Connection, dia: date, total: int, sentencas: int,
                     status: str, mensagem: str = "") -> None:
    con.execute(
        "INSERT OR REPLACE INTO coletas (data, total_api, sentencas, status, mensagem, executado_em) "
        "VALUES (?,?,?,?,?,?)",
        (dia.isoformat(), total, sentencas, status, mensagem, datetime.now().isoformat(timespec="seconds")),
    )


def ultima_coleta_ok(con: sqlite3.Connection) -> date | None:
    row = con.execute("SELECT MAX(data) FROM coletas WHERE status = 'ok'").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None
