"""Classificação das sentenças publicadas no DJEN.

Tudo aqui é heurístico (expressões regulares sobre o teor publicado). Quando uma regra não
identifica o dado com segurança, o campo fica vazio ou como INDEFINIDO, em vez de chutar.
Para revisar a classificação depois de ajustar regras, use `painelcf-teses reprocessar`.
"""

import re
from dataclasses import dataclass, field

from .config import Config
from .texto import chave, limpar_html, sem_acentos, valor_monetario

VERSAO = 1

PROCEDENTE = "PROCEDENTE"
PARCIAL = "PARCIALMENTE_PROCEDENTE"
IMPROCEDENTE = "IMPROCEDENTE"
PRESCRICAO = "PRESCRICAO_DECADENCIA"
SEM_MERITO = "EXTINTO_SEM_MERITO"
ACORDO = "ACORDO_HOMOLOGADO"
EMBARGOS = "EMBARGOS_DECLARACAO"
INDEFINIDO = "INDEFINIDO"

# Resultados que contam como êxito do consumidor (autor) nas estatísticas.
FAVORAVEIS = (PROCEDENTE, PARCIAL)
# Resultados de mérito usados como denominador da taxa de procedência.
MERITO = (PROCEDENTE, PARCIAL, IMPROCEDENTE, PRESCRICAO)


# --------------------------------------------------------------------------- filtros

_NUMERO_VARA = re.compile(r"\b(\d{1,2})\s*[AO]?\b")


def numero_vara(nome_orgao: str | None) -> int | None:
    """Número ordinal da vara ("13ª VARA..." -> 13); None se não houver."""
    m = _NUMERO_VARA.search(chave(nome_orgao))
    return int(m.group(1)) if m else None


def comarca_do_orgao(nome_orgao: str | None, numero_processo: str | None, cfg: Config) -> str | None:
    """Comarca pelo nome do órgão, se for uma comarca conhecida; senão, pelo código de origem do processo."""
    pelo_nome = comarca(nome_orgao)
    if pelo_nome and (not cfg.comarcas_conhecidas or chave(pelo_nome) in cfg.comarcas_conhecidas):
        return pelo_nome
    return cfg.codigos_origem.get(codigo_origem(numero_processo) or "") or pelo_nome


def orgao_admitido(nome_orgao: str | None, cfg: Config, numero_processo: str | None = None) -> bool:
    """Admite (a) Juizados da lista [juizados_consumo] e (b) Varas de Relações de Consumo, se habilitadas."""
    k = chave(nome_orgao)
    if not k or any(p.search(k) for p in cfg.orgaos_excluir):
        return False
    if any(p.search(k) for p in cfg.juizado):
        regra = cfg.juizados_consumo.get(chave(comarca_do_orgao(nome_orgao, numero_processo, cfg)))
        if regra is None:
            return False
        varas, exigir = regra
        if exigir is not None and not exigir.search(k):
            return False
        numero = numero_vara(nome_orgao)
        # Nome sem número ("VARA DO SISTEMA DOS JUIZADOS - VALENÇA") equivale à 1ª/única vara.
        numero = numero or 1
        return numero in varas if varas else numero == 1
    return cfg.incluir_varas_relacoes_consumo and any(p.search(k) for p in cfg.varas_relacoes_consumo)


def rito(nome_classe: str | None, cfg: Config) -> str | None:
    """'comum' ou 'juizado' conforme a classe; None se a classe não é admitida."""
    k = chave(nome_classe)
    for nome_rito, padroes in cfg.classes.items():
        if any(p.search(k) for p in padroes):
            return nome_rito
    return None


# --------------------------------------------------------------------------- resultado

_MARCADORES = re.compile(
    r"\b(ANTE O EXPOSTO|ANTE O EXPENDIDO|DIANTE DO EXPOSTO|DIANTE DO QUE FOI EXPOSTO|PELO EXPOSTO|"
    r"POR TODO O EXPOSTO|EM FACE DO EXPOSTO|FACE AO EXPOSTO|DO EXPOSTO|ISTO POSTO|ISSO POSTO|"
    r"POSTO ISSO|EX POSITIS|DIANTE DISSO|ASSIM SENDO|POR ESSAS RAZOES|POR TAIS RAZOES|"
    r"POR TAIS FUNDAMENTOS|DISPOSITIVO)\b"
)

_VERBO = r"\b(?:JULGO(?:-[OA]S?)?|JULGA-SE|JULGAM-SE)\b"
_MERITO = [
    # "JULGO (PARCIALMENTE) (IM)PROCEDENTE(S) (EM PARTE)"
    re.compile(_VERBO + r"(?P<meio>[^.;:]{0,80}?)\b(?P<im>IM)?PROCEDENTES?\b"),
    # "DECLARO A (PARCIAL) (IM)PROCEDÊNCIA" / "OPINO PELA (PARCIAL) PROCEDÊNCIA" (projeto de sentença)
    re.compile(r"\b(?:DECLARO|OPINO|OPINA-SE|OPINAMOS)\b(?P<meio>[^.;:]{0,40}?)\b(?P<im>IM)?PROCEDENCIA\b"),
    # "ACOLHO (PARCIALMENTE) OS PEDIDOS"
    re.compile(r"\bACOLHO\b(?P<meio>[^.;:]{0,30}?)\bOS\s+PEDIDOS\b(?P<im>)"),
    # "REJEITO OS PEDIDOS (AUTORAIS / INICIAIS / FORMULADOS)"
    re.compile(r"\bREJEITO\b(?P<meio>[^.;:]{0,30}?)\bOS\s+PEDIDOS\s+(?P<im>)(?=AUTORA|INICIA|FORMULAD|DA\s+INICIAL|DO\s+AUTOR|DA\s+AUTORA|DA\s+PARTE)"),
]
_PARCIAL = re.compile(r"PARCIAL|EM\s+PARTE")
# Objetos que não são o pedido principal do consumidor.
_OBJETO_ACESSORIO = re.compile(
    r"CONTRAPOSTO|RECONVEN|EMBARGOS|IMPUGNA|EXCECAO|INCIDENTE|HABILITACAO|GRATUIDADE|"
    r"LIQUIDACAO|PRESTACAO\s+DE\s+CONTAS\s+APRESENTADA"
)

_FIM_OBJETO = re.compile(r"[.;]|\s+E\s+|,\s+(?!EM\s+PARTE)")

_ACORDO = re.compile(r"\bHOMOLOG\w*\b[^.]{0,80}?\b(ACORDO|TRANSACAO|COMPOSICAO\s+AMIGAVEL)\b")
_SEM_MERITO = re.compile(
    r"(\b(JULGO|DECLARO)\s+EXTINT[OA]S?\b|\bEXTINGO\b|\bHOMOLOGO\b[^.]{0,40}DESISTENCIA)"
    r"[^.]{0,160}?(SEM\s+(RESOLUCAO|JULGAMENTO|EXAME|APRECIACAO)\s+D[OE]\s+MERITO|ART\.?\s*485|DESISTENCIA)"
)
_PRESCRICAO = re.compile(
    r"\b(PRONUNCIO|RECONHECO|DECLARO|ACOLHO)\b[^.]{0,60}?\b(PRESCRICAO|DECADENCIA)\b"
)
_EMBARGOS_INICIO = re.compile(r"EMBARGOS\s+DE\s+DECLARACAO|EMBARGOS\s+DECLARATORIOS")


@dataclass
class _Achado:
    inicio: int
    resultado: str


def _achados_merito(u: str) -> list[_Achado]:
    achados = []
    for padrao in _MERITO:
        for m in padrao.finditer(u):
            # Objeto imediato do julgamento: até o fim da oração ou a próxima conjunção.
            objeto = _FIM_OBJETO.split(u[m.end(): m.end() + 60], maxsplit=1)[0]
            if _OBJETO_ACESSORIO.search(m.group("meio")) or _OBJETO_ACESSORIO.search(objeto):
                continue
            if m.group("im"):
                res = IMPROCEDENTE
            elif padrao is _MERITO[3]:
                res = IMPROCEDENTE
            elif _PARCIAL.search(m.group("meio")) or _PARCIAL.search(objeto[:40]):
                res = PARCIAL
            else:
                res = PROCEDENTE
            achados.append(_Achado(m.start(), res))
    achados.sort(key=lambda a: a.inicio)
    return achados


def _consolidar(achados: list[_Achado]) -> str:
    tipos = {a.resultado for a in achados}
    if PARCIAL in tipos or {PROCEDENTE, IMPROCEDENTE} <= tipos:
        return PARCIAL
    return achados[0].resultado


def resultado(texto: str) -> tuple[str, int | None]:
    """Retorna (resultado, posição do dispositivo no texto normalizado)."""
    u = chave(texto)
    if _EMBARGOS_INICIO.search(u[:400]):
        return EMBARGOS, None

    achados = _achados_merito(u)
    if achados:
        # O dispositivo é o trecho após o último marcador ("Ante o exposto...") que ainda tenha
        # julgamento depois dele. Assim, no Juizado, a homologação do projeto de sentença
        # ("Ante o exposto, homologo...") não esconde o dispositivo do projeto.
        for marcador in reversed([m.start() for m in _MARCADORES.finditer(u)]):
            apos = [a for a in achados if a.inicio > marcador]
            if apos:
                return _consolidar(apos), apos[0].inicio
        perto = [a for a in achados if a.inicio - achados[0].inicio <= 800]
        return _consolidar(perto), perto[0].inicio

    if m := _PRESCRICAO.search(u):
        return PRESCRICAO, m.start()
    if m := _ACORDO.search(u):
        return ACORDO, m.start()
    if m := _SEM_MERITO.search(u):
        return SEM_MERITO, m.start()
    return INDEFINIDO, None


def e_sentenca(tipo_documento: str | None, texto: str) -> bool:
    tipo = chave(tipo_documento)
    if "SENTENCA" in tipo:
        return True
    if any(t in tipo for t in ("DESPACHO", "DECISAO", "ACORDAO", "ATO ORDINATORIO", "EDITAL", "CERTIDAO")):
        return False
    # Intimações genéricas cujo teor traz a própria sentença.
    u = chave(texto)
    return u.startswith("SENTENCA") or bool(_achados_merito(u))


# --------------------------------------------------------------------------- magistrado

_MAIUSC = "A-ZÁÉÍÓÚÂÊÔÃÕÀÇÜ"
_TOKEN = rf"[{_MAIUSC}][{_MAIUSC}a-zà-ÿ'´.]*"
_CONECTOR = r"(?:d[aeo]s?|D[AEO]S?|e|E)"
_NOME = rf"{_TOKEN}(?:\s+(?:{_CONECTOR}\s+)?{_TOKEN}){{1,7}}"
_PAPEL = (
    r"(?i:ju[ií]z(?:a|\(a\)|\(íza\))?\s+(?:de\s+direito|substitut[oa]|titular|leig[oa])"
    r"|ju[ií]za\s+(?:de\s+direito|substituta|titular|leiga))"
)
_ANTES = re.compile(rf"(?P<nome>{_NOME})\s*[,\-–]?\s*(?P<papel>{_PAPEL})")
_DEPOIS = re.compile(rf"(?P<papel>{_PAPEL})\s*[:\-–]?\s*(?P<nome>[{_MAIUSC}]{{2,}}(?:\s+[{_MAIUSC}]{{1,}}){{1,7}})\b")
_CONECTORES = {"DE", "DA", "DO", "DOS", "DAS", "E"}
_NAO_NOME = {"DOCUMENTO", "ASSINADO", "ELETRONICAMENTE", "PODER", "JUDICIARIO", "TRIBUNAL",
             "ESTADO", "BAHIA", "COMARCA", "VARA", "JUIZADO", "SENTENCA", "DR", "DRA", "DR.", "DRA.",
             "EXMO", "EXMA", "MM", "MM.", "BEL", "BEL."}


def _limpar_nome(bruto: str) -> str | None:
    tokens = bruto.split()
    # Descarta o que vem antes do último token terminado em ponto (fim de frase, "Bel.", "Dr.").
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].endswith(".") and len(tokens[i]) > 2:
            tokens = tokens[i + 1:]
            break
    while tokens and (chave(tokens[0]).strip(".") in _NAO_NOME or chave(tokens[0]) in _CONECTORES):
        tokens = tokens[1:]
    while tokens and chave(tokens[-1]) in _CONECTORES:
        tokens = tokens[:-1]
    if len([t for t in tokens if chave(t) not in _CONECTORES]) < 2:
        return None
    return " ".join(t.capitalize() if chave(t) not in _CONECTORES else t.lower() for t in tokens)


def magistrados(texto: str) -> tuple[str | None, str | None]:
    """(juiz togado, juiz leigo) identificados pela assinatura no teor."""
    togado = leigo = None
    achados = [(m.start(), m.group("nome"), m.group("papel")) for m in _ANTES.finditer(texto)]
    if not achados:
        achados = [(m.start(), m.group("nome"), m.group("papel")) for m in _DEPOIS.finditer(texto)]
    for _, nome, papel in achados:
        nome = _limpar_nome(nome)
        if not nome:
            continue
        if "LEIG" in chave(papel):
            leigo = nome
        else:
            togado = nome  # a última assinatura de juiz togado prevalece (homologação)
    return togado, leigo


# --------------------------------------------------------------------------- comarca

_DESCRITORES = {
    "VARA", "VARAS", "V", "FEITOS", "FEITO", "REL", "RELACOES", "RELACAO", "CONS", "CONSUMO", "CONSUMIDOR",
    "CIV", "CIVEL", "CIVEIS", "COM", "COMERCIAL", "COMERCIAIS", "JUIZADO", "JUIZADOS", "ESPECIAL",
    "ESPECIAIS", "SISTEMA", "DEFESA", "JURISDICAO", "PLENA", "UNICA", "CRIME", "CRIMES", "CRIMINAL",
    "CRIMINAIS", "FAMILIA", "SUCESSOES", "ORFAOS", "INTERDITOS", "AUSENTES", "FAZENDA", "PUBLICA",
    "REGISTROS", "PUBLICOS", "ACIDENTES", "TRABALHO", "EXECUCOES", "FISCAIS", "INFANCIA", "JUVENTUDE",
    "CEJUSC", "NUCLEO", "AUXILIAR", "BANCARIOS", "CONTRATOS", "EMPRESARIAL", "EMPRESARIAIS", "TURMA",
    "GABINETE", "JUIZ", "JUIZA", "TITULAR", "SUBSTITUTO", "ADJUNTO", "UNIDADE", "JUDICIARIA", "CARTORIO",
    "SECRETARIA", "SERVENTIA", "PROJUDI", "PJE", "MISTA", "ESPEC", "VSJE", "E", "RELATIVOS", "RELATIVO",
    "AS", "A", "REGISTRO", "ACIDENTE", "FAZ", "CAUSAS", "COMUNS",
}
_CONEXOES = {"DE", "DA", "DO", "DOS", "DAS"}
# Turno da vara em Salvador/Itabuna: "(MATUTINO)", "(VESPERTINO)", "(MAT)", "(VESP)".
_TURNO = re.compile(r"\(\s*(MAT|VESP|NOT)[A-Z]*\.?\s*\)")
_ABREVIACOES = [
    (re.compile(r"\bVIT\.\s*"), "VITÓRIA "),
    (re.compile(r"\bSTO\.?\s+"), "SANTO "),
    (re.compile(r"\bSTA\.?\s+"), "SANTA "),
    (re.compile(r"\bS\.\s*"), "SÃO "),
    (re.compile(r"\bN\.\s*S(RA)?\.\s*"), "NOSSA SENHORA "),
]
_ORDINAL = re.compile(r"^\d+[AO]?$")


def comarca(nome_orgao: str | None) -> str | None:
    """Comarca a partir do nome do órgão (mantém a acentuação original)."""
    if not nome_orgao:
        return None
    k = nome_orgao.replace("ª", "A").replace("º", "O").replace("°", "O").upper()
    k = _TURNO.sub(" ", k)
    k = k.replace("(", " - ").replace(")", " ")  # "JUIZADOS ESPECIAIS (LIVRAMENTO DE NOSSA SENHORA"
    for abrev, extenso in _ABREVIACOES:
        k = abrev.sub(extenso, k)
    k = re.sub(r"\s+", " ", k).strip()
    sa = sem_acentos(k)  # mesmo comprimento de k: as posições coincidem
    if m := re.search(r"COMARCA\s+D[AEO]S?\s+(.+?)(\s*-.*)?$", sa):
        return _titulo(k[m.start(1): m.end(1)])
    partes = [p.strip() for p in re.split(r"\s*[-–]\s*|\s+/\s+|\s*/\s*BA$", k) if p.strip()]
    # "2O JUIZADO ESPECIAL DO CONSUMIDOR - SALVADOR": a última parte sem descritores é a comarca.
    if len(partes) > 1 and not (set(_tokens(partes[-1], sem_acento=True)) & (_DESCRITORES - {"E"})):
        return _titulo(partes[-1])
    tokens = _tokens(partes[0])
    nome: list[str] = []
    for tok in reversed(tokens):
        base = sem_acentos(tok)
        if base in _DESCRITORES or _ORDINAL.match(base):
            break
        nome.insert(0, tok)
    while nome and sem_acentos(nome[0]) in _CONEXOES:
        nome.pop(0)
    return _titulo(" ".join(nome)) if nome else None


def _tokens(texto: str, sem_acento: bool = False) -> list[str]:
    t = re.sub(r"[^\w\s]", " ", texto).split()
    return [sem_acentos(x) for x in t] if sem_acento else t


def _titulo(nome: str) -> str:
    nome = re.sub(r"\s+BA$", "", nome.strip())
    return " ".join(p.lower() if sem_acentos(p) in _CONEXOES else p.capitalize() for p in nome.split())


def codigo_origem(numero_processo: str | None) -> str | None:
    """Código da unidade de origem (últimos 4 dígitos do número CNJ)."""
    digitos = re.sub(r"\D", "", numero_processo or "")
    return digitos[-4:] if len(digitos) == 20 else None


# --------------------------------------------------------------------------- condenação

_DANO_MORAL = re.compile(r"DANOS?\s+MORA(?:L|IS)|DANO\s+EXTRAPATRIMONIAL|COMPENSACAO\s+MORAL")
_VALOR_POS = re.compile(r"R\$\s*[\d.]+(?:,\d{1,2})?")
_DOBRO = re.compile(r"EM\s+DOBRO|DOBRADA|ART\.?\s*42,?\s+PARAGRAFO\s+UNICO")
_RESTITUICAO = re.compile(r"RESTITUI|REPETI|DEVOLU|RESSARC|REEMBOLS")
_INEXISTENCIA = re.compile(
    r"\bDECLAR\w*\b[^.;]{0,40}?\b(INEXISTENCIA|NULIDADE|INEXIGIBILIDADE|INVALIDADE|RESCISAO|CANCELAMENTO)\b"
)


def dano_moral(u_dispositivo: str) -> float | None:
    """Valor fixado a título de dano moral, buscando o R$ mais próximo da expressão."""
    for m in _DANO_MORAL.finditer(u_dispositivo):
        candidatos = []
        ini = max(0, m.start() - 220)
        janela = u_dispositivo[ini: m.end() + 260]
        for v in _VALOR_POS.finditer(janela):
            pos = ini + v.start()
            dist = m.start() - pos if pos < m.start() else pos - m.end()
            candidatos.append((dist, v.group()))
        if candidatos:
            valor = valor_monetario(min(candidatos)[1])
            if valor and valor > 0:
                return valor
    return None


def repeticao_dobro(u_dispositivo: str) -> bool:
    for m in _DOBRO.finditer(u_dispositivo):
        janela = u_dispositivo[max(0, m.start() - 220): m.end() + 120]
        if _RESTITUICAO.search(janela):
            return True
    return False


def temas(u: str, cfg: Config) -> list[str]:
    return [tema for tema, padroes in cfg.temas.items() if any(p.search(u) for p in padroes)]


# --------------------------------------------------------------------------- análise completa

@dataclass
class Analise:
    rito: str | None
    resultado: str
    comarca: str | None
    juiz: str | None
    juiz_leigo: str | None
    dano_moral: float | None
    repeticao_dobro: bool
    inexistencia_debito: bool
    temas: list[str] = field(default_factory=list)


def analisar(item: dict, cfg: Config) -> Analise | None:
    """Analisa uma comunicação do DJEN. Retorna None se não for sentença de vara/classe admitida."""
    if not orgao_admitido(item.get("nomeOrgao"), cfg, item.get("numero_processo")):
        return None
    rito_ = rito(item.get("nomeClasse"), cfg)
    if not rito_:
        return None
    texto = limpar_html(item.get("texto"))
    if not e_sentenca(item.get("tipoDocumento"), texto):
        return None

    res, pos = resultado(texto)
    u = chave(texto)
    if pos is not None:
        dispositivo = u[pos:]
    else:
        dispositivo = u[int(len(u) * 0.6):]
    favoravel = res in FAVORAVEIS
    togado, leigo = magistrados(texto)
    return Analise(
        rito=rito_,
        resultado=res,
        comarca=comarca_do_orgao(item.get("nomeOrgao"), item.get("numero_processo"), cfg),
        juiz=togado,
        juiz_leigo=leigo,
        dano_moral=dano_moral(dispositivo) if favoravel else None,
        repeticao_dobro=favoravel and repeticao_dobro(dispositivo),
        inexistencia_debito=favoravel and bool(_INEXISTENCIA.search(dispositivo)),
        temas=temas(u, cfg),
    )
