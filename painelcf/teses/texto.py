"""Normalização do teor das comunicações do DJEN."""

import html
import re
import unicodedata

_TAG_QUEBRA = re.compile(r"<\s*(br|/p|/div|/li|/tr|/h\d)\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"[ \t\r\f\v ]+")
_LINHAS = re.compile(r"\n\s*\n+")


def limpar_html(texto: str | None) -> str:
    """Remove marcação HTML preservando quebras de parágrafo."""
    if not texto:
        return ""
    t = _TAG_QUEBRA.sub("\n", texto)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    t = _ESPACOS.sub(" ", t)
    t = "\n".join(linha.strip() for linha in t.split("\n"))
    return _LINHAS.sub("\n", t).strip()


def sem_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave(texto: str | None) -> str:
    """Forma canônica para comparação: maiúsculas, sem acentos, espaços simples.

    Ordinais "1ª"/"2º" viram "1A"/"2O" para não se perderem na comparação.
    """
    if not texto:
        return ""
    t = texto.replace("ª", "A").replace("º", "O").replace("°", "O")
    t = sem_acentos(t).upper()
    return re.sub(r"\s+", " ", t).strip()


_VALOR = re.compile(r"R\$\s*([\d.]+(?:,\d{1,2})?)")


def valor_monetario(trecho: str) -> float | None:
    """Converte 'R$ 5.000,00' em 5000.0."""
    m = _VALOR.search(trecho)
    if not m:
        return None
    bruto = m.group(1).rstrip(".")
    try:
        return float(bruto.replace(".", "").replace(",", "."))
    except ValueError:
        return None
