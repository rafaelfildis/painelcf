import json
import sqlite3
import unittest
from datetime import date
from pathlib import Path

from painelcf.teses import classificador as c
from painelcf.teses import coleta, config, db, relatorio
from painelcf.teses.djen import AcessoBloqueado, ClienteDJEN, ErroDJEN
from painelcf.teses.empresas import PF, PJ, PUBLICO, nome_canonico, tipo_parte

FIXTURE = Path(__file__).parent / "fixtures" / "djen_tjba_amostra.json"
CFG = config.carregar()


def _itens():
    return {i["id"] - 900000: i for i in json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]}


class TestFiltros(unittest.TestCase):
    def test_orgaos(self):
        admitidos = [
            "13ª VARA DE RELAÇÕES DE CONSUMO DE SALVADOR",
            "1ª V DOS FEITOS DE REL DE CONS CIV E COMERCIAIS DE FEIRA DE SANTANA",
            "5ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DO CONSUMIDOR - SALVADOR",
            "20ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DO CONSUMIDOR DE SALVADOR",
            "1ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE ALAGOINHAS",
            "VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE BRUMADO",            # vara única, sem número
            "1ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE BRUMADO",         # vara única, numerada
            "3ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE ILHÉUS",
            "VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE LUÍS EDUARDO MAGALHÃES",
            "2ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS CÍVEIS E CRIMINAIS DE JEQUIÉ",
        ]
        recusados = [
            "2ª VARA CÍVEL E COMERCIAL DE SALVADOR",
            "VARA CRIME DE ITABUNA",
            "2ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE ALAGOINHAS",       # só a 1ª está na lista
            "6ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE FEIRA DE SANTANA",
            "21ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DO CONSUMIDOR - SALVADOR",
            "3ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS CÍVEIS - SALVADOR",  # Salvador exige "do Consumidor"
            "VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE ITAPARICA",           # comarca fora da lista
            "2ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE BRUMADO",         # vara única
            "JUIZADO ESPECIAL DA FAZENDA PÚBLICA DE SALVADOR",
            "3ª TURMA RECURSAL",
        ]
        for o in admitidos:
            self.assertTrue(c.orgao_admitido(o, CFG), o)
        for o in recusados:
            self.assertFalse(c.orgao_admitido(o, CFG), o)

    def test_juizado_sem_comarca_no_nome_usa_codigo_de_origem(self):
        orgao = "7ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DO CONSUMIDOR"
        self.assertTrue(c.orgao_admitido(orgao, CFG, "8000001-10.2025.8.05.0001"))
        self.assertFalse(c.orgao_admitido(orgao, CFG, "8000001-10.2025.8.05.9999"))

    def test_varas_relacoes_consumo_desligaveis(self):
        from dataclasses import replace
        so_juizados = replace(CFG, incluir_varas_relacoes_consumo=False)
        self.assertFalse(c.orgao_admitido("13ª VARA DE RELAÇÕES DE CONSUMO DE SALVADOR", so_juizados))
        self.assertTrue(c.orgao_admitido("1ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE ALAGOINHAS", so_juizados))

    def test_nomes_reais_do_tjba(self):
        """Nomes de órgãos como constam do DataJud/TJBA (out/2026)."""
        ssa = "8000001-10.2025.8.05.0001"
        casos = [  # (órgão, processo, admitido, comarca)
            ("20ª VSJE DO CONSUMIDOR (VESPERTINO)", ssa, True, "Salvador"),
            ("1ª VSJE DO CONSUMIDOR (MATUTINO)", ssa, True, "Salvador"),
            ("4ª VSJE DE CAUSAS COMUNS (VESPERTINO)", ssa, False, "Salvador"),
            ("2ª VSJE DA FAZENDA PÚBLICA (VESPERTINO)", ssa, False, "Salvador"),
            ("1ª VSJE DE TRÂNSITO (MATUTINO)", ssa, False, "Salvador"),
            ("14ª VARA DE RELACOES DE CONSUMO", ssa, True, "Salvador"),
            ("3ª VARA DO SISTEMA DOS JUIZADOS - ITABUNA (MAT)", None, True, "Itabuna"),
            ("1ª VARA DO SISTEMA DOS JUIZADOS - ITABUNA (VESP)", None, True, "Itabuna"),
            ("2ª VARA DO SISTEMA DOS JUIZADOS- VIT. DA CONQUISTA", None, True, "Vitória da Conquista"),
            ("VARA DO SISTEMA DOS JUIZADOS-STO ANTÔNIO DE JESUS", None, True, "Santo Antônio de Jesus"),
            ("Vara do Sistema dos Juizados Especiais (Livramento de Nossa Senhora", None, True, "Livramento de Nossa Senhora"),
            ("VARA DO SISTEMA DOS JUIZADOS - ALAGOINHAS", None, True, "Alagoinhas"),
            ("VARA DO SISTEMA DOS JUIZADOS - VALENÇA", None, True, "Valença"),
            ("VARA DO SISTEMA DOS JUIZADOS - SANTO ESTEVÃO", None, True, "Santo Estevão"),
            ("1ª VARA JUIZADOS ESPECIAIS DE TEIXEIRA DE FREITAS", None, True, "Teixeira de Freitas"),
            ("5ª VARA DO SISTEMA DOS JUIZADOS - FEIRA DE SANTANA", None, True, "Feira de Santana"),
            ("2ª VARA DOS FEITOS RELATIVOS ÀS RELAÇÕES DE CONSUMO, CÍVEIS E COMERCIAIS DA COMARCA DE CANDEIAS",
             None, True, "Candeias"),
            ("3ª V DOS FEITOS REL ÀS RELAÇÕES DE CONSUMO, CÍVEIS, COMERCIAIS E FAZ. PÚBLICA DE IRECÊ", None, True, "Irecê"),
            ("2ª V DOS FEITOS RELATIVOS AS RELAÇÕES DE CONSUMO, CÍVEIS, COMERCIAIS E FAZENDA PÚBLICA DE CAMPO FORMOSO",
             None, True, "Campo Formoso"),
            ("3ª V DOS FEITOS DE REL. DE CONSUMO, CÍVEIS, COMERCIAIS E ACIDENTE DE TRABALHO DE CAMAÇARI",
             None, True, "Camaçari"),
        ]
        for orgao, processo, admitido, comarca in casos:
            self.assertEqual(c.orgao_admitido(orgao, CFG, processo), admitido, orgao)
            self.assertEqual(c.comarca_do_orgao(orgao, processo, CFG), comarca, orgao)

    def test_tabela_de_codigos_cobre_a_lista(self):
        conhecidas = {c.chave(v) for v in CFG.codigos_origem.values()}
        self.assertEqual([k for k in CFG.juizados_consumo if k not in conhecidas], [])
        self.assertEqual(CFG.codigos_origem["0001"], "Salvador")

    def test_lista_de_juizados_completa(self):
        self.assertEqual(len(CFG.juizados_consumo), 40)
        self.assertEqual(sum(max(len(v), 1) for v, _ in CFG.juizados_consumo.values()), 82)

    def test_rito(self):
        self.assertEqual(c.rito("PROCEDIMENTO COMUM CÍVEL", CFG), "comum")
        self.assertEqual(c.rito("PROCEDIMENTO DO JUIZADO ESPECIAL CÍVEL", CFG), "juizado")
        self.assertIsNone(c.rito("CUMPRIMENTO DE SENTENÇA", CFG))


class TestResultado(unittest.TestCase):
    def casos(self):
        return {
            "Ante o exposto, JULGO PROCEDENTE o pedido.": c.PROCEDENTE,
            "Ante o exposto, JULGO PROCEDENTES os pedidos.": c.PROCEDENTE,
            "Isto posto, julgo parcialmente procedentes os pedidos.": c.PARCIAL,
            "Pelo exposto, JULGO PROCEDENTE EM PARTE a ação.": c.PARCIAL,
            "Pelo exposto, JULGO PROCEDENTES, EM PARTE, os pedidos.": c.PARCIAL,
            "Ante o exposto, JULGO PROCEDENTES os embargos à execução.": c.INDEFINIDO,
            "Ante o exposto, JULGO IMPROCEDENTES os pedidos.": c.IMPROCEDENTE,
            "Ante o exposto, julgo, por sentença, improcedente o pedido.": c.IMPROCEDENTE,
            "Ante o exposto, JULGO PROCEDENTE o pedido de danos materiais e JULGO IMPROCEDENTE o de danos morais.": c.PARCIAL,
            "Ante o exposto, JULGO PROCEDENTE o pedido inicial e IMPROCEDENTE a reconvenção.": c.PROCEDENTE,
            "Ante o exposto, JULGO IMPROCEDENTE o pedido contraposto e PROCEDENTE o pedido autoral.": c.INDEFINIDO,
            "Ante o exposto, REJEITO os pedidos autorais.": c.IMPROCEDENTE,
            "Ante o exposto, ACOLHO PARCIALMENTE os pedidos.": c.PARCIAL,
            "Opino pela PROCEDÊNCIA PARCIAL dos pedidos.": c.PARCIAL,
            "A sentença que julgou procedente o pedido transitou. HOMOLOGO o acordo celebrado.": c.ACORDO,
            "Ante o exposto, JULGO EXTINTO o processo sem resolução do mérito.": c.SEM_MERITO,
            "HOMOLOGO o pedido de desistência e julgo extinto o feito, art. 485, VIII.": c.SEM_MERITO,
            "Ante o exposto, PRONUNCIO a prescrição e extingo o feito com resolução do mérito.": c.PRESCRICAO,
            "Trata-se de embargos de declaração. REJEITO-OS.": c.EMBARGOS,
            "Cite-se.": c.INDEFINIDO,
        }

    def test_resultados(self):
        for texto, esperado in self.casos().items():
            self.assertEqual(c.resultado(texto)[0], esperado, texto)

    def test_projeto_homologado_no_juizado(self):
        texto = ("Isto posto, JULGO PROCEDENTE o pedido. Submeto à homologação. "
                 "Ante o exposto, HOMOLOGO o projeto de sentença para que produza seus efeitos.")
        self.assertEqual(c.resultado(texto)[0], c.PROCEDENTE)

    def test_fundamentacao_nao_vence_dispositivo(self):
        texto = ("Quanto aos danos materiais, julgo procedente o pleito. Quanto aos morais, não há prova. "
                 "Ante o exposto, JULGO PARCIALMENTE PROCEDENTES os pedidos.")
        self.assertEqual(c.resultado(texto)[0], c.PARCIAL)


class TestExtracoes(unittest.TestCase):
    def test_comarca(self):
        casos = {
            "13ª VARA DE RELAÇÕES DE CONSUMO DE SALVADOR": "Salvador",
            "1ª V DOS FEITOS DE REL DE CONS CIV E COMERCIAIS DE SANTO ANTÔNIO DE JESUS": "Santo Antônio de Jesus",
            "VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DE VITÓRIA DA CONQUISTA": "Vitória da Conquista",
            "4ª VSJE DO CONSUMIDOR DE SALVADOR": "Salvador",
            "5ª VARA DO SISTEMA DOS JUIZADOS ESPECIAIS DO CONSUMIDOR - SALVADOR": "Salvador",
            "VARA DOS FEITOS DE RELAÇÕES DE CONSUMO, CÍVEIS E COMERCIAIS DA COMARCA DE CONCEIÇÃO DO COITÉ": "Conceição do Coité",
            "VARA DOS JUIZADOS ESPECIAIS CÍVEIS E CRIMINAIS DE SÃO FÉLIX": "São Félix",
            "2ª VARA DE RELAÇÕES DE CONSUMO": None,
        }
        for orgao, esperado in casos.items():
            self.assertEqual(c.comarca(orgao), esperado, orgao)

    def test_codigo_origem(self):
        self.assertEqual(c.codigo_origem("8000002-10.2025.8.05.0080"), "0080")
        self.assertIsNone(c.codigo_origem("123"))

    def test_magistrados(self):
        self.assertEqual(c.magistrados("P.R.I. Salvador, 8 de outubro de 2026. MARIA DA CONCEIÇÃO SANTOS Juíza de Direito"),
                         ("Maria da Conceição Santos", None))
        self.assertEqual(c.magistrados("Publique-se. Intimem-se. Bel. JOSÉ CARLOS LIMA, Juiz de Direito Titular"),
                         ("José Carlos Lima", None))
        self.assertEqual(c.magistrados("JOÃO PEDRO ALMEIDA Juiz Leigo. Homologo. Ana Beatriz Costa Lima Juíza de Direito"),
                         ("Ana Beatriz Costa Lima", "João Pedro Almeida"))
        self.assertEqual(c.magistrados("JUIZ(A) DE DIREITO: PEDRO HENRIQUE SOUZA"), ("Pedro Henrique Souza", None))
        self.assertEqual(c.magistrados("Sem assinatura."), (None, None))

    def test_dano_moral(self):
        self.assertEqual(c.dano_moral(c.chave("condenar ao pagamento de R$ 5.000,00 (cinco mil reais) a título de danos morais")), 5000.0)
        self.assertEqual(c.dano_moral(c.chave("indenização por danos morais no valor de R$ 10.000,00, corrigidos")), 10000.0)
        self.assertEqual(c.dano_moral(c.chave("restituir R$ 300,00 em dobro, e R$ 4.000,00 por dano moral")), 4000.0)
        self.assertIsNone(c.dano_moral(c.chave("improcedente o pedido de danos morais")))

    def test_dobro(self):
        self.assertTrue(c.repeticao_dobro(c.chave("condenar o réu a restituir, em dobro, os valores descontados")))
        self.assertFalse(c.repeticao_dobro(c.chave("restituição simples dos valores")))


class TestEmpresas(unittest.TestCase):
    def test_unificacao(self):
        self.assertEqual(nome_canonico("BANCO BRADESCO S.A.", CFG), "Banco Bradesco (grupo)")
        self.assertEqual(nome_canonico("Bradesco Saúde S/A", CFG), "Bradesco Saúde")
        self.assertEqual(nome_canonico("COMPANHIA DE ELETRICIDADE DO ESTADO DA BAHIA COELBA", CFG), "Coelba (Neoenergia)")
        self.assertEqual(nome_canonico("TELEFONICA BRASIL S.A.", CFG), "Vivo (Telefônica Brasil)")
        self.assertEqual(nome_canonico("ITAÚ UNIBANCO S.A.", CFG), "Itaú Unibanco (grupo)")
        self.assertEqual(nome_canonico("Empresa Desconhecida Comércio LTDA", CFG), "Empresa Desconhecida Comercio")

    def test_tipo(self):
        self.assertEqual(tipo_parte("BANCO BMG SA"), PJ)
        self.assertEqual(tipo_parte("JOSÉ DA SILVA"), PF)
        self.assertEqual(tipo_parte("MUNICÍPIO DE SALVADOR"), PUBLICO)
        self.assertEqual(tipo_parte("ESTADO DA BAHIA"), PUBLICO)


class TestFluxoCompleto(unittest.TestCase):
    def setUp(self):
        self.con = self._mem()

    def _mem(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(db._ESQUEMA)
        return con

    def test_importacao_e_analise(self):
        lidos, gravados = coleta.processar_itens(self.con, _itens().values(), CFG)
        self.assertEqual(lidos, 9)
        # 4 (vara cível), 5 (despacho) e 6 (cumprimento de sentença) ficam de fora.
        self.assertEqual(gravados, 6)
        s = {r["id"] - 900000: dict(r) for r in self.con.execute("SELECT * FROM sentencas")}

        self.assertEqual(s[1]["resultado"], c.PROCEDENTE)
        self.assertEqual(s[1]["comarca"], "Salvador")
        self.assertEqual(s[1]["juiz"], "Maria da Conceição Santos")
        self.assertEqual(s[1]["dano_moral"], 5000.0)  # não confunde com os R$ 20.000,00 pedidos
        self.assertEqual(s[1]["repeticao_dobro"], 1)
        self.assertEqual(s[1]["inexistencia_debito"], 1)
        self.assertIn("Tarifas bancárias", json.loads(s[1]["temas"]))

        self.assertEqual(s[2]["resultado"], c.PARCIAL)
        self.assertEqual(s[2]["rito"], "juizado")
        self.assertEqual(s[2]["comarca"], "Feira de Santana")
        self.assertEqual(s[2]["juiz"], "Ana Beatriz Costa Lima")
        self.assertEqual(s[2]["juiz_leigo"], "João Pedro Almeida")
        self.assertEqual(s[2]["dano_moral"], 3000.0)

        self.assertEqual(s[3]["resultado"], c.IMPROCEDENTE)
        self.assertEqual(s[3]["comarca"], "Santo Antonio de Jesus")
        self.assertIsNone(s[3]["dano_moral"])

        self.assertEqual(s[7]["resultado"], c.SEM_MERITO)
        self.assertEqual(s[8]["resultado"], c.EMBARGOS)
        self.assertEqual(s[9]["resultado"], c.PARCIAL)
        self.assertEqual(s[9]["juiz"], "Rita de Cássia Oliveira")
        self.assertEqual(s[9]["comarca"], "Vitória da Conquista")

        empresas = {r["empresa"] for r in self.con.execute("SELECT empresa FROM partes WHERE empresa IS NOT NULL")}
        self.assertEqual(empresas, {"Banco Bradesco (grupo)", "Coelba (Neoenergia)", "Banco BMG",
                                    "Vivo (Telefônica Brasil)", "Claro/NET"})

    def test_relatorio(self):
        coleta.processar_itens(self.con, _itens().values(), CFG)
        d = relatorio.montar(self.con, date(2026, 10, 9), 30)
        self.assertEqual(len(d["do_dia"]), 3)  # 1 procedente + 2 parcialmente procedentes
        self.assertEqual(d["resumo"]["merito"], 4)
        self.assertEqual(d["resumo"]["favoraveis"], 3)
        empresas = {e["nome"]: e for e in d["empresas"]}
        self.assertEqual(empresas["Banco Bradesco (grupo)"]["favoraveis"], 1)
        self.assertEqual(empresas["Banco BMG"]["improcedente"], 1)
        self.assertEqual(empresas["Banco BMG"]["taxa"], 0.0)
        html_ = relatorio.gerar_html(d)
        self.assertIn("Maria da Conceição Santos", html_)
        self.assertIn("R$ 5.000,00", html_)

    def test_republicacao_conta_uma_vez(self):
        itens = _itens()
        copia = dict(itens[1], id=999999, data_disponibilizacao="2026-10-10")
        coleta.processar_itens(self.con, [itens[1], copia], CFG)
        n = self.con.execute("SELECT COUNT(*) FROM sentencas_unicas").fetchone()[0]
        self.assertEqual(n, 1)

    def test_mesma_sentenca_duas_comunicacoes_no_dia(self):
        itens = _itens()
        coleta.processar_itens(self.con, [itens[1], dict(itens[1], id=999997)], CFG)
        d = relatorio.montar(self.con, date(2026, 10, 9), 30)
        self.assertEqual(len(d["do_dia"]), 1)

    def test_comarca_por_codigo(self):
        itens = _itens()
        sem_comarca = dict(itens[1], id=999998, nomeOrgao="2ª VARA DE RELAÇÕES DE CONSUMO",
                           numero_processo="80999991020258050001")
        coleta.processar_itens(self.con, [itens[1], sem_comarca], CFG)
        db.preencher_comarcas_por_codigo(self.con)
        r = self.con.execute("SELECT comarca FROM sentencas WHERE id = 999998").fetchone()
        self.assertEqual(r["comarca"], "Salvador")


class TestCliente(unittest.TestCase):
    def test_paginacao(self):
        paginas = {1: [{"id": 1}, {"id": 2}], 2: [{"id": 3}]}
        urls = []

        def buscar(url):
            urls.append(url)
            pagina = int(url.split("pagina=")[1].split("&")[0])
            return json.dumps({"count": 3, "items": paginas.get(pagina, [])}).encode()

        cli = ClienteDJEN("TJBA", itens_por_pagina=2, pausa=0, buscar=buscar)
        itens = list(cli.comunicacoes_paginadas(date(2026, 10, 9)))
        self.assertEqual([i["id"] for i in itens], [1, 2, 3])
        self.assertIn("siglaTribunal=TJBA", urls[0])
        self.assertIn("dataDisponibilizacaoInicio=2026-10-09", urls[0])
        self.assertEqual(cli.ultimo_total, 3)

    def test_caderno_com_fallback(self):
        def buscar(url):
            if "/caderno/" in url:
                raise ErroDJEN("404")
            return json.dumps({"count": 1, "items": [{"id": 7}]}).encode()

        cli = ClienteDJEN(pausa=0, buscar=buscar)
        self.assertEqual([i["id"] for i in cli.comunicacoes_do_dia(date(2026, 10, 9))], [7])

    def test_caderno_zip(self):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("tjba.json", json.dumps({"items": [{"id": 1, "texto": "a"}, {"id": 2, "texto": "b"}]}))

        def buscar(url):
            if "/caderno/" in url:
                return json.dumps({"url": "https://exemplo/caderno.zip"}).encode()
            return buf.getvalue()

        cli = ClienteDJEN(pausa=0, buscar=buscar)
        self.assertEqual(len(list(cli.comunicacoes_do_dia(date(2026, 10, 9)))), 2)

    def test_bloqueio_interrompe_coleta(self):
        def buscar(url):
            raise AcessoBloqueado("403")

        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(db._ESQUEMA)
        cli = ClienteDJEN(pausa=0, buscar=buscar)
        ok = coleta.coletar(con, CFG, [date(2026, 10, 8), date(2026, 10, 9)], cli)
        self.assertFalse(ok)
        status = [r["status"] for r in con.execute("SELECT status FROM coletas")]
        self.assertEqual(status, ["erro"])


class TestDiasPendentes(unittest.TestCase):
    def test_primeira_execucao_e_retomada(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(db._ESQUEMA)
        hoje = date(2026, 10, 12)
        self.assertEqual(coleta.dias_pendentes(con, CFG, hoje),
                         [date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)])
        db.registrar_coleta(con, date(2026, 10, 11), 10, 1, "ok")
        self.assertEqual(coleta.dias_pendentes(con, CFG, hoje), [date(2026, 10, 11), date(2026, 10, 12)])


if __name__ == "__main__":
    unittest.main()
