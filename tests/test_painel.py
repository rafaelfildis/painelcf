import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

from painelcf.painel import api, datajud
from painelcf.painel.http import Manipulador
from painelcf.teses.djen import AcessoBloqueado, ClienteDJEN

ITEM = {
    "id": 10, "data_disponibilizacao": "2026-03-05", "siglaTribunal": "TJBA", "tipoComunicacao": "Intimação",
    "nomeOrgao": "13ª VARA DE RELAÇÕES DE CONSUMO", "texto": "<p>SENTENÇA</p><p>JULGO PROCEDENTE.</p>",
    "numero_processo": "80000011020258050001", "numeroprocessocommascara": "8000001-10.2025.8.05.0001",
    "tipoDocumento": "Sentença", "nomeClasse": "PROCEDIMENTO COMUM CÍVEL", "ativo": True, "hash": "abc",
    "link": "https://pje/x", "meiocompleto": "Diário de Justiça Eletrônico Nacional",
    "destinatarios": [{"nome": "FULANA", "polo": "A"}, {"nome": "BANCO X S.A.", "polo": "P"}],
    "destinatarioadvogados": [{"advogado": {"nome": "JONATHAN CORREA MILANEZ", "numero_oab": "74896", "uf_oab": "BA"}}],
}


def djen_falso(paginas, urls=None):
    def buscar(url):
        if urls is not None:
            urls.append(url)
        pagina = int(url.split("pagina=")[1].split("&")[0])
        return json.dumps({"count": sum(len(p) for p in paginas), "items": paginas[pagina - 1] if pagina <= len(paginas) else []}).encode()
    return lambda: ClienteDJEN(pausa=0, buscar=buscar)


class TestPeriodo(unittest.TestCase):
    def test_mes_e_ano(self):
        hoje = date(2026, 10, 29)
        self.assertEqual(api.periodo("2026", "2", hoje), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(api.periodo("2025", None, hoje), (date(2025, 1, 1), date(2025, 12, 31)))
        self.assertEqual(api.periodo("2026", None, hoje), (date(2026, 1, 1), hoje))  # não passa de hoje
        self.assertEqual(api.periodo(None, "10", hoje), (date(2026, 10, 1), hoje))
        for ano, mes in [("2026", "11"), ("2027", None), ("abc", None), ("2026", "13")]:
            with self.assertRaises(api.ErroPedido):
                api.periodo(ano, mes, hoje)


class TestPublicacoes(unittest.TestCase):
    def test_filtros_e_normalizacao(self):
        urls = []
        r = api.publicacoes({"oab": "74.896", "uf": "ba", "ano": "2026", "mes": "3"}, djen_falso([[ITEM]], urls))
        self.assertIn("numeroOab=74896", urls[0])
        self.assertIn("ufOab=BA", urls[0])
        self.assertIn("dataDisponibilizacaoInicio=2026-03-01", urls[0])
        self.assertIn("dataDisponibilizacaoFim=2026-03-31", urls[0])
        self.assertNotIn("nomeParte", urls[0])
        self.assertEqual(r["total"], 1)
        p = r["itens"][0]
        self.assertEqual(p["processo"], "80000011020258050001")
        self.assertEqual(p["texto"], "SENTENÇA\nJULGO PROCEDENTE.")
        self.assertEqual(p["partes"], [{"nome": "FULANA", "polo": "A"}, {"nome": "BANCO X S.A.", "polo": "P"}])
        self.assertEqual(p["advogados"], [{"nome": "JONATHAN CORREA MILANEZ", "oab": "74896", "uf": "BA"}])

    def test_paginacao_limite_e_duplicados(self):
        paginas = [[dict(ITEM, id=i) for i in range(p * 100, p * 100 + 100)] for p in range(3)]
        paginas[1][0] = dict(ITEM, id=0)  # repetido
        r = api.publicacoes({"parte": "BANCO X", "limite": "2"}, djen_falso(paginas))
        self.assertTrue(r["truncado"])
        self.assertEqual(r["total"], 300)
        self.assertEqual(r["retornados"], 199)

    def test_validacoes(self):
        for params in [{}, {"uf": "BA"}, {"oab": "1", "uf": "XX"}, {"processo": "123"}, {"parte": "x", "limite": "a"}]:
            with self.assertRaises(api.ErroPedido, msg=params):
                api.publicacoes(params, djen_falso([[]]))

    def test_bloqueio_vira_502(self):
        original = api._djen_padrao
        api._djen_padrao = lambda: ClienteDJEN(buscar=lambda u: (_ for _ in ()).throw(AcessoBloqueado("403")))
        try:
            status, corpo = api.responder("/api/publicacoes", {"oab": "1"})
        finally:
            api._djen_padrao = original
        self.assertEqual(status, 502)
        self.assertTrue(corpo["bloqueado"])


class TestDataJud(unittest.TestCase):
    def test_indice(self):
        self.assertEqual(datajud.indice("8000001-10.2025.8.05.0001"), "tjba")
        self.assertEqual(datajud.indice("0000001-10.2025.8.07.0001"), "tjdft")
        self.assertEqual(datajud.indice("0000001-10.2025.8.26.0100"), "tjsp")
        self.assertEqual(datajud.indice("1000001-10.2025.4.01.3300"), "trf1")
        self.assertEqual(datajud.indice("0000001-10.2025.5.05.0001"), "trt5")
        self.assertIsNone(datajud.indice("0000001-10.2025.6.05.0001"))
        self.assertIsNone(datajud.indice("123"))

    def test_resumo_une_graus(self):
        docs = [
            {"numeroProcesso": "80000011020258050001", "grau": "G1", "classe": {"nome": "Procedimento Comum Cível"},
             "assuntos": [{"nome": "Tarifas"}], "orgaoJulgador": {"nome": "13ª VARA"}, "dataAjuizamento": "20250110093000",
             "dataHoraUltimaAtualizacao": "2026-05-01T00:00:00Z",
             "movimentos": [{"codigo": 26, "nome": "Distribuição", "dataHora": "2025-01-10T00:00:00Z"},
                            {"codigo": 221, "nome": "Procedência em Parte", "dataHora": "2025-11-03T00:00:00Z"}]},
            {"numeroProcesso": "80000011020258050001", "grau": "G2", "dataHoraUltimaAtualizacao": "2026-06-01T00:00:00Z",
             "movimentos": [{"codigo": 848, "nome": "Trânsito em julgado", "dataHora": "2026-05-20T00:00:00Z"}]},
        ]
        r = datajud.resumir(docs)
        self.assertEqual(r["classe"], "Procedimento Comum Cível")
        self.assertEqual(r["ajuizamento"], "2025-01-10")
        self.assertEqual(r["sentenca"], {"resultado": "Procedente em parte", "data": "2025-11-03"})
        self.assertTrue(r["transitado"])
        self.assertEqual(r["ultimo_andamento"], {"nome": "Trânsito em julgado", "data": "2026-05-20"})
        self.assertEqual(r["graus"], ["G1", "G2"])

    def test_cliente_agrupa_por_tribunal(self):
        chamadas = []

        def postar(url, corpo):
            chamadas.append((url, corpo["query"]["terms"]["numeroProcesso"]))
            return {"hits": {"hits": [{"_source": {"numeroProcesso": n, "grau": "G1", "movimentos": []}}
                                      for n in corpo["query"]["terms"]["numeroProcesso"]]}}

        r = datajud.ClienteDataJud(postar=postar).processos(
            ["8000001-10.2025.8.05.0001", "1000001-10.2025.4.01.3300", "0000001-10.2025.6.05.0001"])
        self.assertEqual({u.rsplit("/", 2)[-2] for u, _ in chamadas}, {"api_publica_tjba", "api_publica_trf1"})
        self.assertIsNone(r["00000011020256050001"])
        self.assertIsNotNone(r["80000011020258050001"])

    def test_processos_valida(self):
        with self.assertRaises(api.ErroPedido):
            api.processos({"numeros": "123"})


class TestHTTP(unittest.TestCase):
    def setUp(self):
        class Local(Manipulador):
            servir_arquivos = True
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Local)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        self.srv.shutdown()
        os.environ.pop("PAINEL_TOKEN", None)

    def _get(self, caminho, cabecalhos=None):
        req = urllib.request.Request(self.base + caminho, headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_arquivos_e_rotas(self):
        status, corpo = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Painel de publica", corpo)
        self.assertEqual(self._get("/painel.js")[0], 200)
        self.assertEqual(self._get("/../pyproject.toml")[0], 404)
        status, corpo = self._get("/api/publicacoes")
        self.assertEqual(status, 400)
        self.assertIn("Informe ao menos um filtro", json.loads(corpo)["erro"])

    def test_senha(self):
        os.environ["PAINEL_TOKEN"] = "segredo"
        self.assertEqual(self._get("/api/processos?numeros=1")[0], 401)
        self.assertEqual(self._get("/api/processos?numeros=1", {"X-Painel-Token": "errado"})[0], 401)
        self.assertEqual(self._get("/api/processos?numeros=1", {"X-Painel-Token": "segredo"})[0], 400)


if __name__ == "__main__":
    unittest.main()
