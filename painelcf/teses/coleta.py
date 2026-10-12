"""Coleta diária: DJEN -> classificação -> SQLite."""

import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import classificador, db
from .config import Config
from .djen import AcessoBloqueado, ClienteDJEN, ErroDJEN, extrair_itens

log = logging.getLogger(__name__)


def processar_itens(con: sqlite3.Connection, itens, cfg: Config) -> tuple[int, int]:
    """Classifica e grava as sentenças admitidas. Retorna (comunicações lidas, sentenças gravadas)."""
    lidos = gravados = 0
    for item in itens:
        lidos += 1
        if item.get("ativo") is False or not item.get("id"):
            continue
        analise = classificador.analisar(item, cfg)
        if analise is None:
            continue
        db.salvar(con, item, analise, cfg)
        gravados += 1
    return lidos, gravados


def dias_pendentes(con: sqlite3.Connection, cfg: Config, hoje: date) -> list[date]:
    ultima = db.ultima_coleta_ok(con)
    # Recoleta o último dia já coletado: a coleta pode ter rodado antes de o caderno fechar.
    inicio = ultima if ultima else hoje - timedelta(days=cfg.dias_iniciais - 1)
    inicio = max(inicio, hoje - timedelta(days=cfg.max_dias_por_execucao - 1))
    return [inicio + timedelta(days=i) for i in range((hoje - inicio).days + 1)]


def coletar(con: sqlite3.Connection, cfg: Config, dias: list[date], cliente: ClienteDJEN | None = None) -> bool:
    cliente = cliente or ClienteDJEN(cfg.tribunal, cfg.itens_por_pagina, cfg.pausa_entre_requisicoes)
    tudo_ok = True
    for dia in dias:
        try:
            lidos, gravados = processar_itens(con, cliente.comunicacoes_do_dia(dia, cfg.modo), cfg)
            total = getattr(cliente, "ultimo_total", lidos) or lidos
            db.registrar_coleta(con, dia, total, gravados, "ok")
            con.commit()
            log.info("%s: %d comunicações lidas, %d sentenças admitidas gravadas", dia, lidos, gravados)
        except AcessoBloqueado as e:
            con.rollback()
            db.registrar_coleta(con, dia, 0, 0, "erro", str(e))
            con.commit()
            log.error("%s", e)
            return False
        except ErroDJEN as e:
            con.rollback()
            db.registrar_coleta(con, dia, 0, 0, "erro", str(e))
            con.commit()
            log.error("%s: %s", dia, e)
            tudo_ok = False
    preenchidas = db.preencher_comarcas_por_codigo(con)
    con.commit()
    if preenchidas:
        log.info("%d comarcas completadas pelo código de origem do processo", preenchidas)
    return tudo_ok


def importar_arquivo(con: sqlite3.Connection, cfg: Config, caminho: Path) -> tuple[int, int]:
    """Importa um JSON salvo da API (resposta de /comunicacao ou lista de comunicações)."""
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    lidos, gravados = processar_itens(con, extrair_itens(dados), cfg)
    db.preencher_comarcas_por_codigo(con)
    con.commit()
    return lidos, gravados


def reprocessar(con: sqlite3.Connection, cfg: Config) -> tuple[int, int]:
    """Reaplica as regras atuais a todas as sentenças já gravadas (após ajustar config ou regras)."""
    linhas = con.execute("SELECT bruto FROM sentencas").fetchall()
    con.execute("DELETE FROM sentencas")
    lidos, gravados = processar_itens(con, (json.loads(r["bruto"]) for r in linhas), cfg)
    db.preencher_comarcas_por_codigo(con)
    con.commit()
    return lidos, gravados
