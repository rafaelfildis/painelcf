"""Cliente da API pública do DJEN (Comunica PJe / CNJ).

Endpoint: https://comunicaapi.pje.jus.br/api/v1/comunicacao — sem autenticação.
Atenção: o CNJ bloqueia acessos de fora do Brasil (HTTP 403 do CloudFront). Execute a coleta
em máquina ou servidor com IP brasileiro.
"""

import io
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from datetime import date

BASE = "https://comunicaapi.pje.jus.br/api/v1"
USER_AGENT = "painelcf-teses/0.1 (Calmon & Freitas Advogados)"

log = logging.getLogger(__name__)


class ErroDJEN(RuntimeError):
    pass


class AcessoBloqueado(ErroDJEN):
    """403: normalmente bloqueio geográfico (IP fora do Brasil)."""


Buscador = Callable[[str], bytes]


def _http_get(url: str, tentativas: int = 6, timeout: int = 90) -> bytes:
    espera = 5.0
    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise AcessoBloqueado(
                    "DJEN respondeu 403. O CNJ bloqueia acessos de fora do Brasil: "
                    "execute a coleta em máquina/servidor com IP brasileiro."
                ) from e
            if e.code in (429, 500, 502, 503, 504) and tentativa < tentativas:
                retry = e.headers.get("Retry-After") if e.headers else None
                pausa = float(retry) if retry and retry.isdigit() else espera
                log.warning("DJEN HTTP %s; nova tentativa em %.0fs (%d/%d)", e.code, pausa, tentativa, tentativas)
                time.sleep(pausa)
                espera = min(espera * 2, 120)
                continue
            raise ErroDJEN(f"DJEN HTTP {e.code} em {url}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if tentativa < tentativas:
                log.warning("Falha de rede (%s); nova tentativa em %.0fs", e, espera)
                time.sleep(espera)
                espera = min(espera * 2, 120)
                continue
            raise ErroDJEN(f"Falha de rede ao acessar {url}: {e}") from e
    raise ErroDJEN(f"Sem resposta de {url}")


class ClienteDJEN:
    def __init__(self, tribunal: str = "TJBA", itens_por_pagina: int = 100, pausa: float = 1.0,
                 buscar: Buscador | None = None):
        self.tribunal = tribunal
        self.itens_por_pagina = itens_por_pagina
        self.pausa = pausa
        self._buscar = buscar or _http_get

    def _json(self, url: str) -> dict:
        try:
            return json.loads(self._buscar(url))
        except json.JSONDecodeError as e:
            raise ErroDJEN(f"Resposta não-JSON do DJEN em {url}") from e

    # ---------------------------------------------------------------- consulta paginada

    def comunicacoes_paginadas(self, dia: date, **filtros) -> Iterator[dict]:
        """Todas as comunicações do tribunal publicadas no dia, página a página."""
        pagina, recebidos, total = 1, 0, None
        while True:
            params = {
                "siglaTribunal": self.tribunal,
                "dataDisponibilizacaoInicio": dia.isoformat(),
                "dataDisponibilizacaoFim": dia.isoformat(),
                "pagina": pagina,
                "itensPorPagina": self.itens_por_pagina,
                **filtros,
            }
            url = f"{BASE}/comunicacao?{urllib.parse.urlencode(params)}"
            dados = self._json(url)
            itens = dados.get("items") or []
            if total is None:
                total = int(dados.get("count") or 0)
                log.info("%s %s: %d comunicações informadas pela API", self.tribunal, dia, total)
            yield from itens
            recebidos += len(itens)
            if not itens or recebidos >= total:
                break
            pagina += 1
            time.sleep(self.pausa)
        if total and recebidos < total:
            log.warning("%s %s: API informou %d comunicações, mas só %d foram entregues pela paginação",
                        self.tribunal, dia, total, recebidos)
        self.ultimo_total = total or 0

    # ---------------------------------------------------------------- consulta livre

    def consultar(self, filtros: dict, max_paginas: int = 20) -> tuple[list[dict], int, bool]:
        """Consulta com filtros da API (numeroOab, nomeParte, datas...).

        Retorna (itens, total informado pela API, truncado por max_paginas)."""
        itens: list[dict] = []
        total = None
        for pagina in range(1, max_paginas + 1):
            params = {**{k: v for k, v in filtros.items() if v}, "pagina": pagina,
                      "itensPorPagina": self.itens_por_pagina}
            dados = self._json(f"{BASE}/comunicacao?{urllib.parse.urlencode(params)}")
            lote = dados.get("items") or []
            if total is None:
                total = int(dados.get("count") or 0)
            itens += lote
            if not lote or len(itens) >= total:
                return itens, total, False
            time.sleep(self.pausa)
        return itens, total or len(itens), len(itens) < (total or 0)

    # ---------------------------------------------------------------- caderno do dia

    def comunicacoes_caderno(self, dia: date, meio: str = "D") -> Iterator[dict]:
        """Baixa o caderno completo do dia (arquivo compactado com as comunicações em JSON)."""
        info = self._json(f"{BASE}/caderno/{self.tribunal}/{dia.isoformat()}/{meio}")
        link = info.get("url") or info.get("link") or (info.get("data") or {}).get("url")
        if not link:
            raise ErroDJEN(f"Caderno de {dia} sem link de download: {str(info)[:200]}")
        conteudo = self._buscar(link)
        itens = list(_itens_do_caderno(conteudo))
        self.ultimo_total = len(itens)
        log.info("%s %s: caderno com %d comunicações", self.tribunal, dia, len(itens))
        yield from itens

    def comunicacoes_do_dia(self, dia: date, modo: str = "auto") -> Iterator[dict]:
        if modo == "paginado":
            yield from self.comunicacoes_paginadas(dia)
            return
        try:
            itens = list(self.comunicacoes_caderno(dia))
        except AcessoBloqueado:
            raise
        except ErroDJEN as e:
            if modo == "caderno":
                raise
            log.info("Caderno indisponível (%s); usando consulta paginada", e)
            yield from self.comunicacoes_paginadas(dia)
            return
        yield from itens


def _itens_do_caderno(conteudo: bytes) -> Iterator[dict]:
    if zipfile.is_zipfile(io.BytesIO(conteudo)):
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            for nome in z.namelist():
                if nome.lower().endswith(".json"):
                    yield from extrair_itens(json.loads(z.read(nome)))
    else:
        yield from extrair_itens(json.loads(conteudo))


def extrair_itens(dados) -> Iterator[dict]:
    if isinstance(dados, list):
        for d in dados:
            if isinstance(d, dict) and ("texto" in d or "nomeOrgao" in d):
                yield d
            else:
                yield from extrair_itens(d)
    elif isinstance(dados, dict):
        for chave_lista in ("items", "comunicacoes", "data"):
            if isinstance(dados.get(chave_lista), list):
                yield from extrair_itens(dados[chave_lista])
                return
        if "texto" in dados or "nomeOrgao" in dados:
            yield dados
