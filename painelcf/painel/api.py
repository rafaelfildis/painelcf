"""Rotas do painel: publicações (DJEN) e processos (DataJud).

GET /api/publicacoes?parte=&advogado=&oab=&uf=&processo=&tribunal=&ano=&mes=&limite=
GET /api/processos?numeros=n1,n2,...
GET /api/saude
"""

import calendar
import re
import time
from collections.abc import Callable
from datetime import date

from ..teses.djen import AcessoBloqueado, ClienteDJEN, ErroDJEN, _http_get
from ..teses.texto import limpar_html
from .datajud import ClienteDataJud, ErroDataJud

UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE",
       "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SE", "SP", "TO"}
TEXTO_MAX = 6000
PAGINAS_PADRAO, PAGINAS_MAX = 20, 50


class ErroPedido(ValueError):
    """Filtro inválido (HTTP 400)."""


def _djen_padrao() -> ClienteDJEN:
    # Poucas tentativas e pausa curta: a consulta responde a uma pessoa esperando na tela.
    return ClienteDJEN(itens_por_pagina=100, pausa=0.3,
                       buscar=lambda url: _http_get(url, tentativas=3, timeout=40))


def periodo(ano: str | None, mes: str | None, hoje: date | None = None) -> tuple[date, date]:
    hoje = hoje or date.today()
    try:
        a = int(ano) if ano else hoje.year
        m = int(mes) if mes else None
    except ValueError as e:
        raise ErroPedido("Ano e mês devem ser números.") from e
    if not 2000 <= a <= hoje.year or (m is not None and not 1 <= m <= 12):
        raise ErroPedido("Ano ou mês fora do intervalo.")
    if m:
        inicio, fim = date(a, m, 1), date(a, m, calendar.monthrange(a, m)[1])
    else:
        inicio, fim = date(a, 1, 1), date(a, 12, 31)
    if inicio > hoje:
        raise ErroPedido("O período escolhido ainda não começou.")
    return inicio, min(fim, hoje)


def _data_iso(item: dict) -> str:
    bruto = str(item.get("data_disponibilizacao") or item.get("datadisponibilizacao") or "")[:10]
    if "/" in bruto:
        d, m, a = bruto.split("/")
        return f"{a}-{m}-{d}"
    return bruto


def normalizar(item: dict) -> dict:
    """Comunicação do DJEN no formato enxuto usado pela tela."""
    advogados = []
    for da in item.get("destinatarioadvogados") or []:
        adv = da.get("advogado") or {}
        if adv.get("nome"):
            advogados.append({"nome": adv["nome"], "oab": str(adv.get("numero_oab") or ""),
                              "uf": adv.get("uf_oab") or ""})
    texto = limpar_html(item.get("texto"))
    return {
        "id": item.get("id"),
        "data": _data_iso(item),
        "tribunal": item.get("siglaTribunal"),
        "orgao": item.get("nomeOrgao"),
        "classe": item.get("nomeClasse"),
        "tipo_documento": item.get("tipoDocumento"),
        "tipo_comunicacao": item.get("tipoComunicacao"),
        "meio": item.get("meiocompleto") or item.get("meio"),
        "processo": re.sub(r"\D", "", str(item.get("numero_processo") or "")),
        "processo_mascara": item.get("numeroprocessocommascara"),
        "link": item.get("link"),
        "hash": item.get("hash"),
        "partes": [{"nome": d.get("nome"), "polo": (d.get("polo") or "").upper()[:1]}
                   for d in item.get("destinatarios") or [] if d.get("nome")],
        "advogados": advogados,
        "texto": texto[:TEXTO_MAX],
        "texto_cortado": len(texto) > TEXTO_MAX,
    }


def publicacoes(params: dict, djen: Callable[[], ClienteDJEN] = _djen_padrao) -> dict:
    parte = (params.get("parte") or "").strip()
    advogado = (params.get("advogado") or "").strip()
    oab = re.sub(r"\D", "", params.get("oab") or "")
    uf = (params.get("uf") or "").strip().upper()
    processo = re.sub(r"\D", "", params.get("processo") or "")
    tribunal = (params.get("tribunal") or "").strip().upper()
    if not (parte or advogado or oab or processo):
        raise ErroPedido("Informe ao menos um filtro: nome da parte, nome do advogado, OAB ou número do processo.")
    if uf and uf not in UFS:
        raise ErroPedido("UF da OAB inválida.")
    if processo and len(processo) != 20:
        raise ErroPedido("O número do processo deve ter 20 dígitos.")
    try:
        limite = min(int(params.get("limite") or PAGINAS_PADRAO), PAGINAS_MAX)
    except ValueError as e:
        raise ErroPedido("Limite inválido.") from e

    inicio, fim = periodo(params.get("ano"), params.get("mes"))
    filtros = {
        "nomeParte": parte, "nomeAdvogado": advogado, "numeroOab": oab, "ufOab": uf,
        "numeroProcesso": processo, "siglaTribunal": tribunal,
        "dataDisponibilizacaoInicio": inicio.isoformat(), "dataDisponibilizacaoFim": fim.isoformat(),
    }
    t0 = time.monotonic()
    itens, total, truncado = djen().consultar(filtros, max_paginas=limite)
    vistos, saida = set(), []
    for item in itens:
        if item.get("ativo") is False or item.get("id") in vistos:
            continue
        vistos.add(item.get("id"))
        saida.append(normalizar(item))
    saida.sort(key=lambda p: (p["data"], p["id"] or 0), reverse=True)
    return {
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "filtros": {k: v for k, v in filtros.items() if v and not k.startswith("data")},
        "total": total,
        "retornados": len(saida),
        "truncado": truncado,
        "segundos": round(time.monotonic() - t0, 1),
        "itens": saida,
    }


def processos(params: dict, datajud: Callable[[], ClienteDataJud] = ClienteDataJud) -> dict:
    numeros = [re.sub(r"\D", "", n) for n in (params.get("numeros") or "").split(",")]
    numeros = list(dict.fromkeys(n for n in numeros if len(n) == 20))
    if not numeros:
        raise ErroPedido("Informe os números dos processos (20 dígitos), separados por vírgula.")
    if len(numeros) > 100:
        raise ErroPedido("Máximo de 100 processos por consulta.")
    return {"processos": datajud().processos(numeros)}


def saude(djen: Callable[[], ClienteDJEN] = _djen_padrao) -> dict:
    """Testa o acesso ao DJEN a partir deste servidor (o CNJ bloqueia IPs fora do Brasil)."""
    ontem = date.fromordinal(date.today().toordinal() - 1).isoformat()
    try:
        _, total, _ = djen().consultar({"siglaTribunal": "TJBA", "dataDisponibilizacaoInicio": ontem,
                                        "dataDisponibilizacaoFim": ontem}, max_paginas=1)
        return {"djen": "ok", "teste": f"{total} comunicações do TJBA em {ontem}"}
    except AcessoBloqueado:
        return {"djen": "bloqueado", "teste": "O DJEN recusou este servidor (bloqueio a IPs fora do Brasil)."}
    except ErroDJEN as e:
        return {"djen": "erro", "teste": str(e)}


def responder(caminho: str, params: dict) -> tuple[int, dict]:
    """Despacha a rota; devolve (status HTTP, corpo JSON)."""
    rota = caminho.rstrip("/").rsplit("/", 1)[-1]
    try:
        if rota == "publicacoes":
            return 200, publicacoes(params)
        if rota == "processos":
            return 200, processos(params)
        if rota == "saude":
            return 200, saude()
        return 404, {"erro": "Rota não encontrada."}
    except ErroPedido as e:
        return 400, {"erro": str(e)}
    except AcessoBloqueado:
        return 502, {"erro": "O DJEN recusou o acesso deste servidor. O CNJ bloqueia IPs fora do Brasil.",
                     "bloqueado": True}
    except (ErroDJEN, ErroDataJud) as e:
        return 502, {"erro": str(e)}
