"""Identificação e unificação das partes do polo passivo."""

import re

from .config import Config
from .texto import chave

PJ = "pj"
PF = "pf"
PUBLICO = "publico"

_SUFIXOS = re.compile(
    r"\b(S\s*/?\s*A|S\.A|LTDA|EIRELI|EPP|ME|MEI|SOCIEDADE\s+ANONIMA|EM\s+RECUPERACAO\s+JUDICIAL|"
    r"EM\s+LIQUIDACAO(\s+EXTRAJUDICIAL)?)\b\.?"
)
_INDICIOS_PJ = re.compile(
    r"\b(S\s*/?\s*A|S\.A|LTDA|EIRELI|EPP|ME|BANCO|BANK|CIA|COMPANHIA|SEGURADORA|SEGUROS|FINANCEIRA|"
    r"FINANCIAMENTO|CREDITO|INVESTIMENTO|PAGAMENTOS|INSTITUICAO|COOPERATIVA|ASSOCIACAO|FUNDACAO|"
    r"CONSORCIO|ADMINISTRADORA|COMERCIO|SERVICOS|INDUSTRIA|TELECOM|TELECOMUNICACOES|TELEFONICA|ENERGIA|"
    r"ELETRICIDADE|DISTRIBUIDORA|SAUDE|ASSISTENCIA|HOSPITAL|CLINICA|LINHAS\s+AEREAS|AIRLINES|TRANSPORTES|"
    r"EMPREENDIMENTOS|INCORPORADORA|CONSTRUTORA|IMOBILIARIA|EDUCACIONAL|FACULDADE|UNIVERSIDADE|ESCOLA|"
    r"CARTOES|CARD|PARTICIPACOES|HOLDING|GRUPO|NEGOCIOS|VAREJO|MAGAZINE|LOJAS|SUPERMERCADO|"
    r"TECNOLOGIA|DIGITAL|INTERNET|PLATAFORMA|MARKETPLACE|ONLINE|PREVIDENCIA|CAPITALIZACAO|SA)\b"
)
_PUBLICO = re.compile(
    r"^(MUNICIPIO|ESTADO\s+D[AEO]|UNIAO|INSTITUTO\s+NACIONAL\s+DO\s+SEGURO|INSS|DEFENSORIA|MINISTERIO\s+PUBLICO|"
    r"DEPARTAMENTO\s+ESTADUAL|DETRAN|PREFEITURA|CAMARA\s+MUNICIPAL|SECRETARIA)\b"
)


def normalizar(nome: str | None) -> str:
    k = chave(nome)
    k = re.sub(r"\(.*?\)", " ", k)                    # remove "(CNPJ ...)" e afins
    k = re.sub(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", " ", k)
    k = _SUFIXOS.sub(" ", k)
    k = re.sub(r"[^\w\s&]", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def tipo_parte(nome: str | None) -> str:
    k = chave(nome)
    if _PUBLICO.search(k):
        return PUBLICO
    if _INDICIOS_PJ.search(k) or re.search(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}", k):
        return PJ
    return PF


def nome_canonico(nome: str | None, cfg: Config) -> str:
    """Nome unificado da empresa segundo as regras de config/teses.toml."""
    base = normalizar(nome)
    for canonico, padroes in cfg.empresas:
        if any(p.search(base) for p in padroes):
            return canonico
    return base.title()


def eh_empresa_alias(nome: str | None, cfg: Config) -> bool:
    base = normalizar(nome)
    return any(any(p.search(base) for p in padroes) for _, padroes in cfg.empresas)
