"""Gera config/codigos_origem_tjba.json: código de origem do número CNJ (8.05.OOOO) -> comarca.

Fonte: DataJud (CNJ), que informa o município IBGE do órgão julgador de cada processo, e a API de
localidades do IBGE, para o nome do município. Funciona de qualquer lugar (o DataJud não tem
bloqueio geográfico). Rode de tempos em tempos ou quando surgir comarca não identificada.

    python scripts/gerar_codigos_origem.py
"""

import gzip
import json
import os
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

DATAJUD = "https://api-publica.datajud.cnj.jus.br/api_publica_tjba/_search"
# Chave pública divulgada na wiki do DataJud; se o CNJ trocar, informe a nova em DATAJUD_API_KEY.
CHAVE = os.environ.get("DATAJUD_API_KEY", "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==")
IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/29/municipios"
SAIDA = Path(__file__).resolve().parents[1] / "config" / "codigos_origem_tjba.json"


def _json(url: str, corpo: dict | None = None) -> dict | list:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
    if corpo is not None:
        req.add_header("Authorization", f"APIKey {CHAVE}")
    with urllib.request.urlopen(req, timeout=300) as resp:
        bruto = resp.read()
    return json.loads(gzip.decompress(bruto) if bruto[:2] == b"\x1f\x8b" else bruto)  # o IBGE responde em gzip


def main() -> None:
    municipios = {m["id"]: m["nome"] for m in _json(IBGE)}
    consulta = {
        "size": 0,
        "query": {"range": {"movimentos.dataHora": {"gte": "now-120d"}}},
        "aggs": {"mun": {"terms": {"field": "orgaoJulgador.codigoMunicipioIBGE", "size": 1000},
                         "aggs": {"ex": {"top_hits": {"size": 10, "_source": ["numeroProcesso"]}}}}},
    }
    baldes = _json(DATAJUD, consulta)["aggregations"]["mun"]["buckets"]
    votos: dict[str, Counter] = defaultdict(Counter)
    for b in baldes:
        for h in b["ex"]["hits"]["hits"]:
            numero = h["_source"]["numeroProcesso"]
            if len(numero) == 20 and numero[13:16] == "805":
                votos[numero[-4:]][b["key"]] += 1
    tabela = {cod: municipios.get(c.most_common(1)[0][0], "") for cod, c in sorted(votos.items())}
    tabela = {k: v for k, v in tabela.items() if v}
    SAIDA.write_text(json.dumps(tabela, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(tabela)} códigos gravados em {SAIDA}")


if __name__ == "__main__":
    main()
