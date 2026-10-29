"""Cliente da API Pública do DataJud (CNJ).

Endpoint: https://api-publica.datajud.cnj.jus.br/api_publica_<tribunal>/_search (Elasticsearch).
Exige o cabeçalho "Authorization: APIKey <chave pública>", divulgada na wiki do DataJud.
Não há bloqueio geográfico. Limite informado pelo CNJ: 120 requisições por minuto.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable

BASE = "https://api-publica.datajud.cnj.jus.br"
CHAVE_PUBLICA = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="

# Segmento J.TR do número CNJ -> índice do DataJud.
_UF_ESTADUAL = ["ac", "al", "ap", "am", "ba", "ce", "dft", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb",
                "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc", "se", "sp", "to"]

# Andamentos da Tabela Processual Unificada (TPU/CNJ) usados no painel.
SENTENCA = {219: "Procedente", 221: "Procedente em parte", 220: "Improcedente",
            466: "Acordo homologado"}
TRANSITO = 848
BAIXA = 22

_CAMPOS = ["numeroProcesso", "grau", "classe.nome", "assuntos.nome", "orgaoJulgador.nome", "dataAjuizamento",
           "sistema.nome", "dataHoraUltimaAtualizacao", "movimentos.codigo", "movimentos.nome",
           "movimentos.dataHora"]

Postador = Callable[[str, dict], dict]


class ErroDataJud(RuntimeError):
    pass


def indice(numero: str) -> str | None:
    """Índice do DataJud para o número CNJ (20 dígitos): justiça estadual, federal e do trabalho."""
    d = re.sub(r"\D", "", numero or "")
    if len(d) != 20:
        return None
    justica, tr = d[13], int(d[14:16])
    if justica == "8" and 1 <= tr <= 27:
        return f"tj{_UF_ESTADUAL[tr - 1]}"
    if justica == "4" and 1 <= tr <= 6:
        return f"trf{tr}"
    if justica == "5" and 1 <= tr <= 24:
        return f"trt{tr}"
    return None


def _post(url: str, corpo: dict, chave: str, tentativas: int = 3) -> dict:
    dados = json.dumps(corpo).encode()
    for t in range(tentativas):
        req = urllib.request.Request(url, data=dados, headers={
            "Content-Type": "application/json", "Authorization": f"APIKey {chave}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and t < tentativas - 1:
                time.sleep(3 * (t + 1))
                continue
            raise ErroDataJud(f"DataJud HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if t < tentativas - 1:
                time.sleep(3 * (t + 1))
                continue
            raise ErroDataJud(f"Falha de rede no DataJud: {e}") from e
    raise ErroDataJud("Sem resposta do DataJud")


def _data(bruto: str | None) -> str | None:
    """Normaliza '20250610145338' ou '2025-06-10T...' para '2025-06-10'."""
    if not bruto:
        return None
    s = str(bruto)
    if re.fullmatch(r"\d{8,14}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def resumir(docs: list[dict]) -> dict:
    """Une os registros de um processo (um por grau) num resumo para o painel."""
    primeiro = next((d for d in docs if d.get("grau") in ("G1", "JE")), docs[0])
    movs = sorted((m for d in docs for m in d.get("movimentos") or [] if m.get("dataHora")),
                  key=lambda m: m["dataHora"])
    sentencas = [m for m in movs if m.get("codigo") in SENTENCA]
    ultimo = movs[-1] if movs else None
    return {
        "classe": (primeiro.get("classe") or {}).get("nome"),
        "assuntos": [a.get("nome") for a in primeiro.get("assuntos") or [] if a.get("nome")],
        "orgao": (primeiro.get("orgaoJulgador") or {}).get("nome"),
        "ajuizamento": _data(primeiro.get("dataAjuizamento")),
        "sistema": (primeiro.get("sistema") or {}).get("nome"),
        "graus": sorted({d.get("grau") for d in docs if d.get("grau")}),
        "sentenca": ({"resultado": SENTENCA[sentencas[-1]["codigo"]], "data": _data(sentencas[-1]["dataHora"])}
                     if sentencas else None),
        "transitado": any(m.get("codigo") == TRANSITO for m in movs),
        "baixado": any(m.get("codigo") == BAIXA for m in movs),
        "ultimo_andamento": ({"nome": ultimo.get("nome"), "data": _data(ultimo["dataHora"])} if ultimo else None),
        "atualizado_em": _data(max((d.get("dataHoraUltimaAtualizacao") or "") for d in docs)),
    }


class ClienteDataJud:
    def __init__(self, chave: str | None = None, postar: Postador | None = None):
        self.chave = chave or os.environ.get("DATAJUD_API_KEY") or CHAVE_PUBLICA
        self._postar = postar or (lambda url, corpo: _post(url, corpo, self.chave))

    def processos(self, numeros: list[str]) -> dict[str, dict | None]:
        """Resumo de cada processo (chave: número só com dígitos). None se o DataJud não o tiver."""
        por_indice: dict[str, list[str]] = defaultdict(list)
        resultado: dict[str, dict | None] = {}
        for n in numeros:
            d = re.sub(r"\D", "", n)
            idx = indice(d)
            resultado[d] = None
            if idx:
                por_indice[idx].append(d)
        for idx, lote_total in por_indice.items():
            for i in range(0, len(lote_total), 100):
                lote = lote_total[i:i + 100]
                corpo = {"size": len(lote) * 4, "_source": _CAMPOS,
                         "query": {"terms": {"numeroProcesso": lote}}}
                hits = self._postar(f"{BASE}/api_publica_{idx}/_search", corpo)["hits"]["hits"]
                docs: dict[str, list[dict]] = defaultdict(list)
                for h in hits:
                    docs[h["_source"]["numeroProcesso"]].append(h["_source"])
                for numero, lista in docs.items():
                    resultado[numero] = resumir(lista)
        return resultado
