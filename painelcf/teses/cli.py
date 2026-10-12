"""Linha de comando: python -m painelcf.teses <comando>.

Comandos:
  diario       coleta os dias pendentes e gera o relatório (use no agendador)
  coletar      coleta um dia ou período específico (--data / --inicio --fim)
  importar     importa um JSON salvo manualmente da API do DJEN
  relatorio    gera o relatório HTML/CSV a partir do banco
  reprocessar  reaplica as regras de classificação às sentenças já gravadas
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from . import coleta, config, db, relatorio


def _data(texto: str) -> date:
    return date.fromisoformat(texto)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="painelcf-teses", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, help="arquivo de configuração (padrão: config/teses.toml)")
    p.add_argument("--banco", type=Path, help="arquivo SQLite (padrão: dados/teses.db)")
    p.add_argument("--saida", type=Path, help="pasta dos relatórios (padrão: relatorios/)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("diario", help="coleta pendente + relatório")

    c = sub.add_parser("coletar", help="coleta dia(s) específico(s)")
    c.add_argument("--data", type=_data, help="AAAA-MM-DD (padrão: hoje)")
    c.add_argument("--inicio", type=_data)
    c.add_argument("--fim", type=_data)

    i = sub.add_parser("importar", help="importa JSON salvo da API")
    i.add_argument("arquivos", type=Path, nargs="+")

    r = sub.add_parser("relatorio", help="gera relatório")
    r.add_argument("--data", type=_data, help="dia de referência (padrão: último dia coletado)")
    r.add_argument("--dias", type=int, default=30, help="janela de análise em dias (padrão: 30)")

    sub.add_parser("reprocessar", help="reclassifica o que já está no banco")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%d/%m %H:%M:%S")
    cfg = config.carregar(args.config)
    con = db.conectar(args.banco)

    if args.comando == "diario":
        ok = coleta.coletar(con, cfg, coleta.dias_pendentes(con, cfg, date.today()))
        arquivo = relatorio.gerar(con, args.saida)
        print(f"Relatório: {arquivo}")
        return 0 if ok else 1

    if args.comando == "coletar":
        if args.inicio:
            fim = args.fim or date.today()
            dias = [args.inicio + timedelta(days=n) for n in range((fim - args.inicio).days + 1)]
        else:
            dias = [args.data or date.today()]
        return 0 if coleta.coletar(con, cfg, dias) else 1

    if args.comando == "importar":
        for arq in args.arquivos:
            lidos, gravados = coleta.importar_arquivo(con, cfg, arq)
            print(f"{arq}: {lidos} comunicações lidas, {gravados} sentenças admitidas")
        return 0

    if args.comando == "relatorio":
        arquivo = relatorio.gerar(con, args.saida, args.data, args.dias)
        print(f"Relatório: {arquivo}")
        return 0

    if args.comando == "reprocessar":
        lidos, gravados = coleta.reprocessar(con, cfg)
        print(f"{lidos} sentenças reprocessadas; {gravados} continuam admitidas")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
