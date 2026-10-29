"use strict";

const UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SE","SP","TO"];
const MESES = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"];
const POR_PAGINA = 50;
const LOTE_DATAJUD = 40;

const $ = (id) => document.getElementById(id);
const estado = { itens: [], filtrados: [], datajud: {}, pagina: 0, aberto: null, consulta: 0 };

// ------------------------------------------------------------------ utilidades
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => Number(n || 0).toLocaleString("pt-BR");
const dataBR = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—");
const mascara = (n) => (n && n.length === 20 ? `${n.slice(0,7)}-${n.slice(7,9)}.${n.slice(9,13)}.${n.slice(13,14)}.${n.slice(14,16)}.${n.slice(16)}` : n || "");
const pct = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : "—");

function guardar(chave, valor) { try { valor == null ? localStorage.removeItem(chave) : localStorage.setItem(chave, valor); } catch (_) {} }
function ler(chave) { try { return localStorage.getItem(chave); } catch (_) { return null; } }

function mensagem(texto, erro = false) {
  const m = $("mensagem");
  m.textContent = texto || "";
  m.classList.toggle("erro", !!erro);
}

async function api(rota, params) {
  const url = `/api/${rota}?${new URLSearchParams(params)}`;
  const headers = {};
  const senha = ler("painel-senha");
  if (senha) headers["X-Painel-Token"] = senha;
  const r = await fetch(url, { headers });
  let corpo = {};
  try { corpo = await r.json(); } catch (_) { corpo = { erro: `Resposta inválida do servidor (HTTP ${r.status}).` }; }
  if (r.status === 401) { $("senha-box").hidden = false; $("senha").focus(); }
  if (!r.ok) { const e = new Error(corpo.erro || `Erro HTTP ${r.status}`); e.corpo = corpo; throw e; }
  return corpo;
}

// ------------------------------------------------------------------ filtros
function montarFiltros() {
  $("f-uf").insertAdjacentHTML("beforeend", UFS.map((u) => `<option>${u}</option>`).join(""));
  $("f-mes").insertAdjacentHTML("beforeend", MESES.map((m, i) => `<option value="${i + 1}">${m[0].toUpperCase() + m.slice(1)}</option>`).join(""));
  const ano = new Date().getFullYear();
  const anos = [`<option value="3anos">Últimos 3 anos</option>`];
  for (let a = ano; a >= ano - 4; a--) anos.push(`<option value="${a}"${a === ano ? " selected" : ""}>${a}</option>`);
  $("f-ano").innerHTML = anos.join("");
  // Filtros vindos do endereço (?oab=...&uf=...) permitem compartilhar uma consulta.
  const q = new URLSearchParams(location.search);
  for (const campo of ["parte", "advogado", "oab", "uf", "mes", "ano", "tribunal", "processo", "limite"]) {
    if (q.has(campo)) $(`f-${campo}`).value = q.get(campo);
  }
  $("f-mes").disabled = $("f-ano").value === "3anos";
  return q.toString() !== "";
}

function lerFiltros() {
  const f = {};
  for (const campo of ["parte", "advogado", "oab", "uf", "mes", "ano", "tribunal", "processo", "limite"]) {
    const v = $(`f-${campo}`).value.trim();
    if (v) f[campo] = v;
  }
  if (f.ano === "3anos") delete f.mes;
  return f;
}

// ------------------------------------------------------------------ consulta
async function consultar(ev) {
  ev?.preventDefault();
  const f = lerFiltros();
  if (!f.parte && !f.advogado && !f.oab && !f.processo) {
    mensagem("Preencha ao menos um filtro: nome da parte, nome do advogado, OAB ou número do processo.", true);
    return;
  }
  history.replaceState(null, "", `?${new URLSearchParams(f)}`);
  const id = ++estado.consulta;
  $("consultar").disabled = true;
  estado.itens = []; estado.datajud = {}; estado.pagina = 0; estado.aberto = null;

  const anoAtual = new Date().getFullYear();
  const anos = f.ano === "3anos" ? [anoAtual - 2, anoAtual - 1, anoAtual] : [f.ano || String(anoAtual)];
  const avisos = [];
  let total = 0;
  try {
    for (const ano of anos) {
      mensagem(`Consultando o DJEN${anos.length > 1 ? ` (${ano})` : ""}…`);
      const r = await api("publicacoes", { ...f, ano });
      if (id !== estado.consulta) return;
      estado.itens.push(...r.itens);
      total += r.total;
      if (r.truncado) avisos.push(`${ano}: exibindo ${num(r.retornados)} de ${num(r.total)} publicações (aumente o limite em Mais filtros ou refine os filtros)`);
    }
  } catch (e) {
    mensagem(e.message, true);
    $("consultar").disabled = false;
    if (e.corpo?.bloqueado) statusDJEN("bloqueado");
    return;
  }
  $("consultar").disabled = false;
  estado.total = total;
  estado.anos = anos;
  estado.filtros = f;
  aplicarBusca();
  mensagem(avisos.join(" · ") || "", avisos.length > 0);
  enriquecer(id);
}

async function enriquecer(id) {
  const numeros = [...new Set(estado.itens.map((p) => p.processo).filter((n) => n && n.length === 20))];
  for (let i = 0; i < numeros.length; i += LOTE_DATAJUD) {
    if (id !== estado.consulta) return;
    const lote = numeros.slice(i, i + LOTE_DATAJUD);
    $("sub-resultado").dataset.dj = `DataJud: completando ${num(Math.min(i + lote.length, numeros.length))} de ${num(numeros.length)} processos…`;
    renderCabecalho();
    try {
      const r = await api("processos", { numeros: lote.join(",") });
      Object.assign(estado.datajud, r.processos);
    } catch (e) {
      for (const n of lote) estado.datajud[n] ??= { erro: true };
    }
    if (id !== estado.consulta) return;
    renderTudo();
  }
  $("sub-resultado").dataset.dj = numeros.length ? "DataJud: concluído." : "";
  renderCabecalho();
}

// ------------------------------------------------------------------ agregações
function contar(lista, chaveFn) {
  const m = new Map();
  for (const x of lista) for (const k of [].concat(chaveFn(x))) if (k) m.set(k, (m.get(k) || 0) + 1);
  return [...m].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "pt-BR"));
}

function processosUnicos(lista) {
  const m = new Map();
  for (const p of lista) if (!m.has(p.processo)) m.set(p.processo, p);
  return [...m.values()];
}

function lista(alvo, pares, max = 8, rotulo = (k) => k) {
  const el = $(alvo);
  if (!pares.length) { el.innerHTML = `<p class="nada">Sem dados.</p>`; return; }
  const topo = pares[0][1];
  el.innerHTML = `<ul class="lista">${pares.slice(0, max).map(([k, v]) =>
    `<li><span class="nome" title="${esc(k)}">${esc(rotulo(k))}</span><span class="qtd">${num(v)}</span>
     <span class="barra"><i style="width:${Math.max(2, (v / topo) * 100)}%"></i></span></li>`).join("")}</ul>`;
}

const CLASSE_SENTENCA = { "Procedente": "proc", "Procedente em parte": "parc", "Improcedente": "improc" };

function graficoSentencas(procs) {
  const el = $("g-sentenca");
  const comDados = procs.filter((p) => estado.datajud[p.processo]?.classe !== undefined);
  if (!comDados.length) { el.innerHTML = `<p class="nada">${Object.keys(estado.datajud).length ? "Sem sentença registrada." : "Aguardando o DataJud…"}</p>`; return; }
  const cont = contar(comDados, (p) => estado.datajud[p.processo]?.sentenca?.resultado || "Sem sentença registrada");
  const merito = comDados.filter((p) => ["Procedente", "Procedente em parte", "Improcedente"].includes(estado.datajud[p.processo]?.sentenca?.resultado));
  const fav = merito.filter((p) => estado.datajud[p.processo].sentenca.resultado !== "Improcedente").length;
  const topo = Math.max(...cont.map((c) => c[1]));
  el.innerHTML = `<ul class="lista sentenca">${cont.map(([k, v]) =>
    `<li><span class="nome">${esc(k)}</span><span class="qtd">${num(v)}</span>
     <span class="barra"><i class="${CLASSE_SENTENCA[k] || ""}" style="width:${Math.max(2, (v / topo) * 100)}%"></i></span></li>`).join("")}</ul>
    <p class="sub">Procedência no mérito: <b>${pct(fav, merito.length)}</b> de ${num(merito.length)} sentenças · ${num(comDados.length)} processos encontrados no DataJud</p>`;
}

function graficoMeses(itens) {
  const el = $("g-mes");
  const cont = new Map();
  for (const p of itens) { const k = (p.data || "").slice(0, 7); if (k) cont.set(k, (cont.get(k) || 0) + 1); }
  const anos = estado.anos || [];
  const chaves = [];
  if (estado.filtros?.mes) {
    chaves.push(`${anos[0]}-${String(estado.filtros.mes).padStart(2, "0")}`);
  } else {
    const hoje = new Date();
    for (const a of anos) for (let m = 1; m <= 12; m++) {
      if (+a === hoje.getFullYear() && m > hoje.getMonth() + 1) break;
      chaves.push(`${a}-${String(m).padStart(2, "0")}`);
    }
  }
  if (!chaves.length) { el.innerHTML = `<p class="nada">Sem dados.</p>`; return; }
  const max = Math.max(1, ...chaves.map((k) => cont.get(k) || 0));
  const L = 760, A = 210, base = 180, topoY = 22, esq = 6;
  const passo = (L - esq * 2) / chaves.length, larg = Math.max(4, passo * 0.68);
  const ab = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];
  const rotEvery = chaves.length > 18 ? 3 : 1;
  const barras = chaves.map((k, i) => {
    const v = cont.get(k) || 0, h = ((base - topoY) * v) / max;
    const x = esq + i * passo + (passo - larg) / 2, y = base - h;
    const [a, m] = k.split("-");
    const rot = i % rotEvery === 0 ? `<text x="${x + larg / 2}" y="${base + 15}" text-anchor="middle">${ab[+m - 1]}${chaves.length > 12 || m === "01" ? `/${a.slice(2)}` : ""}</text>` : "";
    const valor = v && chaves.length <= 18 ? `<text class="rot" x="${x + larg / 2}" y="${y - 5}" text-anchor="middle">${num(v)}</text>` : "";
    return `<rect class="b" x="${x}" y="${y}" width="${larg}" height="${Math.max(h, v ? 1 : 0)}" rx="2"><title>${ab[+m - 1]}/${a}: ${num(v)} publicações</title></rect>${valor}${rot}`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${L} ${A}" role="img" aria-label="Publicações por mês"><line x1="0" x2="${L}" y1="${base}" y2="${base}"/>${barras}</svg>`;
}

// ------------------------------------------------------------------ renderização
function renderCabecalho() {
  const f = estado.filtros || {};
  const quem = [f.parte && `parte “${f.parte}”`, f.advogado && `advogado ${f.advogado}`, f.oab && `OAB ${f.oab}${f.uf ? "/" + f.uf : ""}`,
    f.processo && `processo ${mascara(f.processo.replace(/\D/g, ""))}`, f.tribunal && f.tribunal.toUpperCase()].filter(Boolean).join(" · ");
  const per = estado.anos?.length > 1 ? `${estado.anos[0]} a ${estado.anos.at(-1)}`
    : f.mes ? `${MESES[f.mes - 1]} de ${estado.anos?.[0]}` : `ano de ${estado.anos?.[0]}`;
  $("titulo-resultado").textContent = quem || "Resultado";
  $("sub-resultado").textContent = `Publicações no DJEN, ${per}. ${$("sub-resultado").dataset.dj || ""}`;
}

function renderTudo() {
  const itens = estado.filtrados;
  const procs = processosUnicos(itens);
  const sentencas = itens.filter((p) => /senten/i.test(p.tipo_documento || "")).length;
  $("kpis").innerHTML = [
    [num(itens.length), estado.total > estado.itens.length ? `publicações (de ${num(estado.total)} no DJEN)` : "publicações"],
    [num(procs.length), "processos distintos"],
    [num(sentencas), "sentenças publicadas"],
    [num(new Set(itens.map((p) => p.tribunal)).size), new Set(itens.map((p) => p.tribunal)).size === 1 ? "tribunal" : "tribunais"],
    [num(new Set(itens.map((p) => p.orgao)).size), new Set(itens.map((p) => p.orgao)).size === 1 ? "vara ou órgão" : "varas e órgãos"],
  ].map(([v, t]) => `<div class="kpi"><b>${v}</b><span>${t}</span></div>`).join("");

  graficoMeses(itens);
  graficoSentencas(procs);
  lista("g-tipo", contar(itens, (p) => p.tipo_documento || p.tipo_comunicacao || "Não informado"));
  lista("g-orgao", contar(itens, (p) => `${p.tribunal} · ${p.orgao}`));
  lista("g-passivo", contar(procs, (p) => [...new Set(p.partes.filter((x) => x.polo === "P").map((x) => x.nome))]), 10);
  lista("g-ativo", contar(procs, (p) => [...new Set(p.partes.filter((x) => x.polo === "A").map((x) => x.nome))]), 10);
  lista("g-adv", contar(procs, (p) => [...new Set(p.advogados.map((a) => `${a.nome} — OAB ${a.oab}/${a.uf}`))]), 10);
  lista("g-assunto", contar(procs, (p) => estado.datajud[p.processo]?.assuntos || []), 8);
  renderCabecalho();
  renderTabela();
}

function celulaDataJud(n) {
  const d = estado.datajud[n];
  if (d === undefined) return `<span class="s">carregando…</span>`;
  if (d === null) return `<span class="s">não encontrado</span>`;
  if (d.erro) return `<span class="s">indisponível</span>`;
  const s = d.sentenca;
  const selo = s ? `<span class="selo ${CLASSE_SENTENCA[s.resultado] || "outro"}">${esc(s.resultado)}</span> <span class="s">${dataBR(s.data)}</span><br>` : "";
  return `${selo}${esc(d.classe || "")}<div class="s">${esc((d.assuntos || []).join(", "))}</div>` +
    (d.ultimo_andamento ? `<div class="s">Último: ${esc(d.ultimo_andamento.nome)} (${dataBR(d.ultimo_andamento.data)})${d.transitado ? " · transitado" : ""}</div>` : "");
}

function renderTabela() {
  const itens = estado.filtrados;
  const paginas = Math.max(1, Math.ceil(itens.length / POR_PAGINA));
  estado.pagina = Math.min(estado.pagina, paginas - 1);
  const pedaco = itens.slice(estado.pagina * POR_PAGINA, (estado.pagina + 1) * POR_PAGINA);
  $("linhas").innerHTML = pedaco.map((p) => {
    const partes = p.partes.map((x) => `<div><span class="polo">${x.polo === "A" ? "ATIVO" : x.polo === "P" ? "PASSIVO" : "—"}</span>${esc(x.nome)}</div>`).join("");
    const proc = esc(p.processo_mascara || mascara(p.processo));
    const linha = `<tr class="pub" data-id="${esc(p.id)}" tabindex="0" aria-expanded="${estado.aberto === p.id}">
      <td class="data">${dataBR(p.data)}</td>
      <td>${p.link ? `<a href="${esc(p.link)}" target="_blank" rel="noopener">${proc}</a>` : proc}<div class="s">${esc(p.classe || "")}</div></td>
      <td>${esc(p.orgao || "")}<div class="s">${esc(p.tribunal || "")}</div></td>
      <td>${esc(p.tipo_documento || "")}<div class="s">${esc(p.tipo_comunicacao || "")}</div></td>
      <td>${partes}</td>
      <td>${celulaDataJud(p.processo)}</td></tr>`;
    const teor = estado.aberto === p.id ? `<tr class="teor"><td colspan="6"><div class="teor-texto">${esc(p.texto)}${p.texto_cortado ? "\n\n[texto encurtado — abra o link do processo para o inteiro teor]" : ""}</div>
      ${p.advogados.length ? `<p class="s">Advogados intimados: ${esc(p.advogados.map((a) => `${a.nome} (OAB ${a.oab}/${a.uf})`).join("; "))}</p>` : ""}
      ${p.hash ? `<p class="s"><a href="https://comunicaapi.pje.jus.br/api/v1/comunicacao/${esc(p.hash)}/certidao" target="_blank" rel="noopener">Certidão de publicação</a></p>` : ""}</td></tr>` : "";
    return linha + teor;
  }).join("") || `<tr><td colspan="6" class="nada">Nenhuma publicação com esse filtro.</td></tr>`;
  $("pagina-info").textContent = `Página ${estado.pagina + 1} de ${paginas} · ${num(itens.length)} publicações`;
  $("anterior").disabled = estado.pagina === 0;
  $("proxima").disabled = estado.pagina >= paginas - 1;
}

function aplicarBusca() {
  const q = $("busca").value.trim().toLowerCase();
  estado.filtrados = !q ? estado.itens : estado.itens.filter((p) =>
    [p.processo, p.processo_mascara, p.orgao, p.tribunal, p.tipo_documento, p.classe, p.texto,
      ...p.partes.map((x) => x.nome), ...p.advogados.map((a) => a.nome)].join(" ").toLowerCase().includes(q));
  estado.pagina = 0;
  $("vazio").hidden = true;
  $("resultado").hidden = false;
  renderTudo();
}

// ------------------------------------------------------------------ CSV
function exportarCSV() {
  const col = ["data", "processo", "tribunal", "orgao", "classe", "tipo_documento", "tipo_comunicacao", "polo_ativo",
    "polo_passivo", "advogados", "dj_classe", "dj_assuntos", "dj_sentenca", "dj_data_sentenca", "dj_ultimo_andamento", "link"];
  const cel = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const linhas = estado.filtrados.map((p) => {
    const d = estado.datajud[p.processo] || {};
    return [dataBR(p.data), p.processo_mascara || mascara(p.processo), p.tribunal, p.orgao, p.classe, p.tipo_documento, p.tipo_comunicacao,
      p.partes.filter((x) => x.polo === "A").map((x) => x.nome).join("; "), p.partes.filter((x) => x.polo === "P").map((x) => x.nome).join("; "),
      p.advogados.map((a) => `${a.nome} (OAB ${a.oab}/${a.uf})`).join("; "), d.classe, (d.assuntos || []).join("; "),
      d.sentenca?.resultado, dataBR(d.sentenca?.data), d.ultimo_andamento ? `${d.ultimo_andamento.nome} (${dataBR(d.ultimo_andamento.data)})` : "", p.link].map(cel).join(";");
  });
  const blob = new Blob(["﻿" + [col.join(";"), ...linhas].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `publicacoes-djen-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ------------------------------------------------------------------ status do DJEN
function statusDJEN(s, texto) {
  const el = $("status-djen");
  el.className = `pill ${s === "ok" ? "ok" : s === "bloqueado" || s === "erro" ? "ruim" : "neutro"}`;
  el.textContent = s === "ok" ? "DJEN conectado" : s === "bloqueado" ? "DJEN bloqueado neste servidor" : s === "erro" ? "DJEN indisponível" : "Verificando DJEN…";
  if (texto) el.title = texto;
}

async function verificarDJEN() {
  try { const r = await api("saude", {}); statusDJEN(r.djen, r.teste); }
  catch (e) { statusDJEN("erro", e.message); }
}

// ------------------------------------------------------------------ eventos
$("filtros").addEventListener("submit", consultar);
$("f-ano").addEventListener("change", () => { $("f-mes").disabled = $("f-ano").value === "3anos"; });
$("limpar").addEventListener("click", () => {
  $("filtros").reset(); montarAnoPadrao(); history.replaceState(null, "", location.pathname);
  $("resultado").hidden = true; $("vazio").hidden = false; mensagem("");
});
$("busca").addEventListener("input", aplicarBusca);
$("anterior").addEventListener("click", () => { estado.pagina--; renderTabela(); });
$("proxima").addEventListener("click", () => { estado.pagina++; renderTabela(); });
$("csv").addEventListener("click", exportarCSV);
$("linhas").addEventListener("click", (ev) => {
  if (ev.target.closest("a")) return;
  const tr = ev.target.closest("tr.pub");
  if (!tr) return;
  const id = Number(tr.dataset.id) || tr.dataset.id;
  estado.aberto = estado.aberto === id ? null : id;
  renderTabela();
});
$("linhas").addEventListener("keydown", (ev) => {
  if ((ev.key === "Enter" || ev.key === " ") && ev.target.matches("tr.pub")) { ev.preventDefault(); ev.target.click(); }
});
$("senha-ok").addEventListener("click", () => {
  guardar("painel-senha", $("senha").value);
  $("senha-box").hidden = true;
  verificarDJEN();
  if (lerFiltros().parte || lerFiltros().advogado || lerFiltros().oab || lerFiltros().processo) consultar();
});
$("senha").addEventListener("keydown", (ev) => { if (ev.key === "Enter") $("senha-ok").click(); });

function montarAnoPadrao() { $("f-ano").value = String(new Date().getFullYear()); $("f-mes").disabled = false; }

const veioDoEndereco = montarFiltros();
verificarDJEN();
if (veioDoEndereco) consultar();
