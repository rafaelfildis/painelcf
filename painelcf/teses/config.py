"""Carga da configuração (config/teses.toml)."""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .texto import chave

RAIZ = Path(__file__).resolve().parents[2]
CONFIG_PADRAO = RAIZ / "config" / "teses.toml"


def _compilar(padroes: list[str]) -> list[re.Pattern]:
    return [re.compile(p) for p in padroes]


@dataclass
class Config:
    tribunal: str = "TJBA"
    modo: str = "auto"
    itens_por_pagina: int = 100
    pausa_entre_requisicoes: float = 1.0
    dias_iniciais: int = 3
    max_dias_por_execucao: int = 15
    incluir_varas_relacoes_consumo: bool = True
    varas_relacoes_consumo: list[re.Pattern] = field(default_factory=list)
    juizado: list[re.Pattern] = field(default_factory=list)
    orgaos_excluir: list[re.Pattern] = field(default_factory=list)
    # comarca (chave sem acentos) -> (números de vara admitidos, padrão exigido no nome ou None)
    juizados_consumo: dict[str, tuple[list[int], re.Pattern | None]] = field(default_factory=dict)
    codigos_origem: dict[str, str] = field(default_factory=dict)
    classes: dict[str, list[re.Pattern]] = field(default_factory=dict)
    temas: dict[str, list[re.Pattern]] = field(default_factory=dict)
    empresas: list[tuple[str, list[re.Pattern]]] = field(default_factory=list)


def carregar(caminho: Path | str | None = None) -> Config:
    caminho = Path(caminho) if caminho else CONFIG_PADRAO
    with open(caminho, "rb") as f:
        bruto = tomllib.load(f)

    coleta = bruto.get("coleta", {})
    filtros = bruto.get("filtros", {})
    return Config(
        tribunal=coleta.get("tribunal", "TJBA"),
        modo=coleta.get("modo", "auto"),
        itens_por_pagina=int(coleta.get("itens_por_pagina", 100)),
        pausa_entre_requisicoes=float(coleta.get("pausa_entre_requisicoes", 1.0)),
        dias_iniciais=int(coleta.get("dias_iniciais", 3)),
        max_dias_por_execucao=int(coleta.get("max_dias_por_execucao", 15)),
        incluir_varas_relacoes_consumo=bool(filtros.get("incluir_varas_relacoes_consumo", True)),
        varas_relacoes_consumo=_compilar(filtros.get("varas_relacoes_consumo", [])),
        juizado=_compilar(filtros.get("juizado", [])),
        orgaos_excluir=_compilar(filtros.get("orgaos_excluir", [])),
        juizados_consumo={
            chave(comarca): ([int(n) for n in v.get("varas", [])],
                             re.compile(v["exigir"]) if v.get("exigir") else None)
            for comarca, v in bruto.get("juizados_consumo", {}).items()
        },
        codigos_origem={str(k): v for k, v in bruto.get("codigos_origem", {}).items()},
        classes={rito: _compilar(p) for rito, p in filtros.get("classes", {}).items()},
        temas={tema: _compilar(p) for tema, p in bruto.get("temas", {}).items()},
        empresas=[(e["nome"], _compilar(e["padroes"])) for e in bruto.get("empresas", [])],
    )
