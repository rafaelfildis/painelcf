"""Relatório de teses: HTML autocontido + CSVs."""

import csv
import html
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .classificador import FAVORAVEIS, IMPROCEDENTE, MERITO, PARCIAL, PRESCRICAO, PROCEDENTE
from .config import RAIZ

PASTA_PADRAO = RAIZ / "relatorios"

ROTULOS = {
    "PROCEDENTE": "Procedente",
    "PARCIALMENTE_PROCEDENTE": "Parcialmente procedente",
    "IMPROCEDENTE": "Improcedente",
    "PRESCRICAO_DECADENCIA": "Prescrição/decadência",
    "EXTINTO_SEM_MERITO": "Extinto sem mérito",
    "ACORDO_HOMOLOGADO": "Acordo homologado",
    "EMBARGOS_DECLARACAO": "Embargos de declaração",
    "INDEFINIDO": "Não identificado",
}
RITOS = {"comum": "Rito comum", "juizado": "Juizado"}


# --------------------------------------------------------------------------- dados

def _sentencas(con: sqlite3.Connection, inicio: date, fim: date, unicas: bool = True) -> list[dict]:
    tabela = "sentencas_unicas" if unicas else "sentencas"
    linhas = con.execute(
        f"SELECT * FROM {tabela} WHERE data_disponibilizacao BETWEEN ? AND ? "
        "ORDER BY data_disponibilizacao DESC, id DESC",
        (inicio.isoformat(), fim.isoformat()),
    ).fetchall()
    sentencas = [dict(r) for r in linhas]
    if not sentencas:
        return []
    ids = [s["id"] for s in sentencas]
    reus: dict[int, list[str]] = defaultdict(list)
    empresas: dict[int, list[str]] = defaultdict(list)
    for i in range(0, len(ids), 900):
        lote = ids[i:i + 900]
        marcas = ",".join("?" * len(lote))
        for p in con.execute(f"SELECT * FROM partes WHERE sentenca_id IN ({marcas}) AND polo = 'P'", lote):
            reus[p["sentenca_id"]].append(p["nome"])
            if p["empresa"] and p["empresa"] not in empresas[p["sentenca_id"]]:
                empresas[p["sentenca_id"]].append(p["empresa"])
    for s in sentencas:
        s["reus"] = reus.get(s["id"], [])
        s["empresas"] = empresas.get(s["id"], [])
        s["temas"] = json.loads(s["temas"] or "[]")
    return sentencas


def _indicadores(grupo: list[dict]) -> dict:
    res = Counter(s["resultado"] for s in grupo)
    merito = sum(res[r] for r in MERITO)
    favoraveis = sum(res[r] for r in FAVORAVEIS)
    danos = [s["dano_moral"] for s in grupo if s["dano_moral"]]
    com_condenacao = [s for s in grupo if s["resultado"] in FAVORAVEIS]
    return {
        "total": len(grupo),
        "procedente": res[PROCEDENTE],
        "parcial": res[PARCIAL],
        "improcedente": res[IMPROCEDENTE] + res[PRESCRICAO],
        "merito": merito,
        "favoraveis": favoraveis,
        "taxa": (favoraveis / merito) if merito else None,
        "dano_medio": statistics.mean(danos) if danos else None,
        "dano_mediano": statistics.median(danos) if danos else None,
        "dano_qtd": len(danos),
        "dobro": (sum(1 for s in com_condenacao if s["repeticao_dobro"]) / len(com_condenacao))
        if com_condenacao else None,
    }


def _agrupar(sentencas: list[dict], chave_fn) -> list[dict]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for s in sentencas:
        for k in chave_fn(s):
            if k:
                grupos[k].append(s)
    linhas = []
    for nome, grupo in grupos.items():
        ind = _indicadores(grupo)
        ind["nome"] = nome
        ind["temas"] = ", ".join(t for t, _ in Counter(t for s in grupo for t in s["temas"]).most_common(3))
        ind["comarcas"] = ", ".join(c for c, _ in Counter(s["comarca"] for s in grupo if s["comarca"]).most_common(3))
        linhas.append(ind)
    linhas.sort(key=lambda l: (-l["favoraveis"], -l["total"], l["nome"]))
    return linhas


def montar(con: sqlite3.Connection, dia: date | None = None, dias: int = 30) -> dict:
    if dia is None:
        row = con.execute("SELECT MAX(data_disponibilizacao) FROM sentencas").fetchone()
        dia = date.fromisoformat(row[0]) if row and row[0] else date.today()
    inicio = dia - timedelta(days=dias - 1)
    periodo = _sentencas(con, inicio, dia)
    # Uma linha por processo: a mesma sentença pode gerar mais de uma comunicação no dia.
    do_dia = list({s["numero_processo"]: s for s in reversed(_sentencas(con, dia, dia, unicas=False))
                   if s["resultado"] in FAVORAVEIS}.values())[::-1]
    coleta = con.execute("SELECT * FROM coletas WHERE data = ?", (dia.isoformat(),)).fetchone()
    return {
        "dia": dia,
        "inicio": inicio,
        "dias": dias,
        "coleta": dict(coleta) if coleta else None,
        "resumo": _indicadores(periodo),
        "por_resultado": Counter(s["resultado"] for s in periodo),
        "por_rito": {RITOS.get(r, r): _indicadores([s for s in periodo if s["rito"] == r])
                     for r in sorted({s["rito"] for s in periodo if s["rito"]})},
        "do_dia": do_dia,
        "empresas": _agrupar(periodo, lambda s: s["empresas"]),
        "juizes": _agrupar(periodo, lambda s: [s["juiz"]]),
        "comarcas": _agrupar(periodo, lambda s: [s["comarca"]]),
        "orgaos": _agrupar(periodo, lambda s: [s["orgao"]]),
        "temas": _agrupar(periodo, lambda s: s["temas"]),
        "sem_juiz": sum(1 for s in periodo if not s["juiz"]),
        "sem_comarca": sum(1 for s in periodo if not s["comarca"]),
    }


# --------------------------------------------------------------------------- formatação

def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _moeda(v: float | None) -> str:
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%".replace(".", ",")


def _data_br(d) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%d/%m/%Y")


def _tabela_ranking(id_: str, titulo_col: str, linhas: list[dict], extra: str = "temas") -> str:
    if not linhas:
        return '<p class="vazio">Sem dados no período.</p>'
    corpo = []
    for l in linhas:
        corpo.append(
            "<tr>"
            f"<td>{_e(l['nome'])}</td>"
            f"<td class=n data-v=\"{l['favoraveis']}\"><b>{l['favoraveis']}</b></td>"
            f"<td class=n data-v=\"{l['procedente']}\">{l['procedente']}</td>"
            f"<td class=n data-v=\"{l['parcial']}\">{l['parcial']}</td>"
            f"<td class=n data-v=\"{l['improcedente']}\">{l['improcedente']}</td>"
            f"<td class=n data-v=\"{l['taxa'] if l['taxa'] is not None else -1}\">{_pct(l['taxa'])}</td>"
            f"<td class=n data-v=\"{l['dano_mediano'] or 0}\">{_moeda(l['dano_mediano'])}</td>"
            f"<td class=n data-v=\"{l['dobro'] if l['dobro'] is not None else -1}\">{_pct(l['dobro'])}</td>"
            f"<td class=s>{_e(l[extra])}</td>"
            "</tr>"
        )
    rotulo_extra = {"temas": "Principais temas", "comarcas": "Principais comarcas"}[extra]
    return (
        f'<div class="tabela"><table id="{id_}" class="ordenavel"><thead><tr>'
        f"<th>{titulo_col}</th><th class=n title='Procedentes + parcialmente procedentes'>Condenações</th>"
        "<th class=n>Proc.</th><th class=n>Parc.</th>"
        "<th class=n title='Improcedentes + prescrição/decadência'>Improc.</th>"
        "<th class=n title='Condenações ÷ sentenças de mérito'>Taxa de procedência</th>"
        "<th class=n title='Mediana do dano moral fixado'>Dano moral (mediana)</th>"
        "<th class=n title='Condenações com repetição do indébito em dobro'>Dobro</th>"
        f"<th>{rotulo_extra}</th></tr></thead><tbody>{''.join(corpo)}</tbody></table></div>"
    )


def _tabela_do_dia(sentencas: list[dict]) -> str:
    if not sentencas:
        return '<p class="vazio">Nenhuma sentença procedente publicada neste dia nas varas monitoradas.</p>'
    corpo = []
    for s in sentencas:
        proc = _e(s["processo_mascara"] or s["numero_processo"])
        if s["link"]:
            proc = f'<a href="{_e(s["link"])}" target="_blank" rel="noopener">{proc}</a>'
        reus = ", ".join(s["empresas"]) or ", ".join(s["reus"])
        selo = "proc" if s["resultado"] == PROCEDENTE else "parc"
        extras = []
        if s["repeticao_dobro"]:
            extras.append("dobro")
        if s["inexistencia_debito"]:
            extras.append("inexistência/nulidade")
        corpo.append(
            "<tr>"
            f"<td class=s>{proc}</td>"
            f"<td><span class=\"selo {selo}\">{_e(ROTULOS[s['resultado']])}</span></td>"
            f"<td>{_e(reus)}</td>"
            f"<td>{_e(s['comarca'])}<div class=s>{_e(s['orgao'])}</div></td>"
            f"<td>{_e(s['juiz'] or '—')}</td>"
            f"<td>{_e(RITOS.get(s['rito'], s['rito']))}</td>"
            f"<td class=n data-v=\"{s['dano_moral'] or 0}\">{_moeda(s['dano_moral'])}</td>"
            f"<td class=s>{_e(', '.join(s['temas']))}{'<br>' if extras and s['temas'] else ''}{_e(' · '.join(extras))}</td>"
            "</tr>"
        )
    return (
        '<div class="tabela"><table id="t-dia" class="ordenavel"><thead><tr>'
        "<th>Processo</th><th>Resultado</th><th>Réu(s)</th><th>Comarca / Vara</th><th>Juiz(a)</th>"
        "<th>Rito</th><th class=n>Dano moral</th><th>Temas</th>"
        f"</tr></thead><tbody>{''.join(corpo)}</tbody></table></div>"
    )


_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1f23;--sub:#5d6670;--line:#e3e0da;--accent:#7a1f2b;
--ok:#1f6b45;--okbg:#e3f1e8;--mid:#8a5a00;--midbg:#fbf0d9;--th:#faf9f6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171a;--card:#1d2024;--ink:#e8e6e1;
--sub:#a2a9b1;--line:#30343a;--accent:#e08a96;--ok:#7fd1a2;--okbg:#1d3326;--mid:#f0c46b;--midbg:#3a2f17;--th:#23262b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:28px 16px 8px;max-width:1240px;margin:auto}
h1{font:600 24px/1.2 Georgia,"Times New Roman",serif;margin:0 0 4px;color:var(--accent)}
h2{font:600 18px/1.3 Georgia,"Times New Roman",serif;margin:0 0 4px}
.sub{color:var(--sub);margin:0}main{max-width:1240px;margin:auto;padding:8px 16px 48px}
nav{display:flex;gap:6px;flex-wrap:wrap;margin:16px 0}nav a{color:var(--ink);text-decoration:none;
border:1px solid var(--line);background:var(--card);padding:6px 12px;border-radius:999px;font-size:13px}
nav a:hover{border-color:var(--accent)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:8px 0 24px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.kpi span{color:var(--sub);font-size:13px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:0 0 20px}
section>p.sub{margin-bottom:12px}.tabela{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--th);font-weight:600;position:sticky;top:0;cursor:pointer;white-space:nowrap;user-select:none}
th.n,td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td .s,td.s,.s{color:var(--sub);font-size:12.5px}a{color:var(--accent)}
.selo{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;white-space:nowrap}
.selo.proc{background:var(--okbg);color:var(--ok)}.selo.parc{background:var(--midbg);color:var(--mid)}
.filtro{width:100%;max-width:360px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--ink);margin:0 0 10px}
.vazio{color:var(--sub);font-style:italic}.aviso{font-size:12.5px;color:var(--sub);margin-top:24px}
"""

_JS = """
document.querySelectorAll('table.ordenavel').forEach(t=>{
  t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
    const tb=t.tBodies[0],rows=[...tb.rows],asc=th.dataset.asc!=='1';
    t.querySelectorAll('th').forEach(h=>delete h.dataset.asc);th.dataset.asc=asc?'1':'0';
    rows.sort((a,b)=>{const x=a.cells[i],y=b.cells[i];
      const vx=x.dataset.v??x.textContent.trim(),vy=y.dataset.v??y.textContent.trim();
      const nx=parseFloat(vx),ny=parseFloat(vy);
      const r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:vx.localeCompare(vy,'pt-BR');return asc?r:-r});
    rows.forEach(r=>tb.appendChild(r))}))});
document.querySelectorAll('input.filtro').forEach(inp=>inp.addEventListener('input',()=>{
  const q=inp.value.toLowerCase();document.querySelectorAll('#'+inp.dataset.alvo+' tbody tr')
  .forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q)?'':'none')}));
"""


def _secao(id_: str, titulo: str, sub: str, corpo: str, filtro: str | None = None) -> str:
    busca = (f'<input class="filtro" data-alvo="{filtro}" placeholder="Filtrar…" aria-label="Filtrar tabela">'
             if filtro else "")
    return f'<section id="{id_}"><h2>{titulo}</h2><p class="sub">{sub}</p>{busca}{corpo}</section>'


def gerar_html(d: dict) -> str:
    r = d["resumo"]
    periodo = f"{_data_br(d['inicio'])} a {_data_br(d['dia'])}"
    coleta = d["coleta"]
    status = ""
    if coleta and coleta["status"] != "ok":
        status = f'<p class="sub" style="color:var(--accent)">Coleta de {_data_br(d["dia"])} com erro: {_e(coleta["mensagem"])}</p>'

    kpis = [
        (len(d["do_dia"]), f"procedentes publicadas em {_data_br(d['dia'])}"),
        (r["total"], f"sentenças analisadas ({d['dias']} dias)"),
        (r["favoraveis"], "condenações (proc. + parcial)"),
        (_pct(r["taxa"]), "taxa de procedência no mérito"),
        (_moeda(r["dano_mediano"]), "dano moral mediano"),
        (_pct(r["dobro"]), "condenações com indébito em dobro"),
    ]
    kpi_html = "".join(f'<div class="kpi"><b>{_e(v)}</b><span>{_e(t)}</span></div>' for v, t in kpis)
    ritos = " · ".join(f"{nome}: {ind['total']} sentenças, {_pct(ind['taxa'])} de procedência"
                       for nome, ind in d["por_rito"].items())
    resultados = " · ".join(f"{ROTULOS.get(k, k)}: {v}" for k, v in d["por_resultado"].most_common())

    secoes = [
        _secao("dia", f"Sentenças procedentes de {_data_br(d['dia'])}",
               "Juizados de consumo da lista do escritório e Varas de Relações de Consumo do TJBA. Inclui parcialmente procedentes.",
               _tabela_do_dia(d["do_dia"]), "t-dia"),
        _secao("empresas", "Empresas mais condenadas",
               f"Polo passivo, {periodo}. Cada processo é contado uma vez, pela sentença mais recente.",
               _tabela_ranking("t-emp", "Empresa", d["empresas"]), "t-emp"),
        _secao("juizes", "Por magistrado",
               f"Juiz(a) togado(a) identificado(a) pela assinatura no teor publicado, {periodo}. "
               f"{d['sem_juiz']} sentença(s) sem assinatura identificável.",
               _tabela_ranking("t-juiz", "Juiz(a)", d["juizes"], "comarcas"), "t-juiz"),
        _secao("comarcas", "Por comarca", f"{periodo}. {d['sem_comarca']} sentença(s) sem comarca identificada.",
               _tabela_ranking("t-com", "Comarca", d["comarcas"]), "t-com"),
        _secao("varas", "Por vara/juizado", periodo, _tabela_ranking("t-vara", "Órgão", d["orgaos"]), "t-vara"),
        _secao("temas", "Por tema (tese)", f"Identificação por palavras-chave, {periodo}. Uma sentença pode ter vários temas.",
               _tabela_ranking("t-tema", "Tema", d["temas"], "comarcas"), "t-tema"),
    ]
    nav = "".join(f'<a href="#{i}">{t}</a>' for i, t in
                  [("dia", "Do dia"), ("empresas", "Empresas"), ("juizes", "Juízes"), ("comarcas", "Comarcas"),
                   ("varas", "Varas"), ("temas", "Temas")])
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Teses TJBA</title>
<style>{_CSS}</style></head><body>
<header><h1>Teses — sentenças de consumo do TJBA</h1>
<p class="sub">Calmon &amp; Freitas Advogados · DJEN · referência {_data_br(d['dia'])} · período {periodo}</p>{status}</header>
<main><nav>{nav}</nav><div class="kpis">{kpi_html}</div>
<p class="sub">{_e(ritos)}</p><p class="sub" style="margin-bottom:20px">{_e(resultados)}</p>
{''.join(secoes)}
<p class="aviso">Classificação automática por análise do teor publicado no DJEN (resultado, juiz, comarca, dano moral e temas).
Confira o inteiro teor antes de usar em peça. Taxa de procedência = (procedentes + parcialmente procedentes) ÷ sentenças de mérito
(inclui improcedentes e prescrição/decadência; exclui extinções sem mérito e acordos).</p>
</main><script>{_JS}</script></body></html>"""


# --------------------------------------------------------------------------- CSV

def _csv(caminho: Path, linhas: list[dict], colunas: list[str]) -> None:
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for l in linhas:
            w.writerow({k: _celula(v) for k, v in l.items()})


def _celula(v):
    if isinstance(v, list):
        return ", ".join(v)
    if isinstance(v, float):
        return f"{v:.2f}".replace(".", ",")  # Excel em português
    return v


def gerar(con: sqlite3.Connection, pasta: Path | None = None, dia: date | None = None, dias: int = 30) -> Path:
    pasta = Path(pasta) if pasta else PASTA_PADRAO
    pasta.mkdir(parents=True, exist_ok=True)
    d = montar(con, dia, dias)
    conteudo = gerar_html(d)
    arquivo = pasta / f"teses_{d['dia'].isoformat()}.html"
    arquivo.write_text(conteudo, encoding="utf-8")
    (pasta / "index.html").write_text(conteudo, encoding="utf-8")

    cols_rank = ["nome", "favoraveis", "procedente", "parcial", "improcedente", "merito", "taxa",
                 "dano_mediano", "dano_medio", "dobro", "temas", "comarcas"]
    _csv(pasta / "empresas.csv", d["empresas"], cols_rank)
    _csv(pasta / "juizes.csv", d["juizes"], cols_rank)
    _csv(pasta / "comarcas.csv", d["comarcas"], cols_rank)
    _csv(pasta / f"procedentes_{d['dia'].isoformat()}.csv", d["do_dia"],
         ["processo_mascara", "numero_processo", "resultado", "empresas", "reus", "comarca", "orgao", "juiz",
          "juiz_leigo", "rito", "dano_moral", "repeticao_dobro", "inexistencia_debito", "temas", "link"])
    return arquivo
