"""Testes sem internet, sem credenciais e sem alterar a planilha."""
import base64
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path

from monitor_nuvem.monitor import (
    PILOT, PublicSession, detail_urls, discover, extract, json_load, json_save,
    load_sources, money_number, normalized, price, sheet_row, sheet_sync,
)

LIST_HTML = """<html><body>
<a href="/aluguel/residencial/">Alugar casas e apartamentos</a>
<a href="/imovel/134719/apartamento-1-quarto-estreito-florianopolis/">Apartamento no Estreito</a>
<a href="/imovel/134730/apartamento-2-quartos-barreiros/">Apartamento em Barreiros</a>
<a href="/comprar/apartamento/">Comprar</a>
</body></html>"""
DETAIL_HTML = """<html><body>
<h1>Apartamento 2 quartos - Estreito - Florianópolis</h1>
<main>Valor Total: R$ 2.450,00. Aluguel: R$ 1.900,00.
Condomínio: R$ 450,00. IPTU: R$ 100,00.
Tem sacada e vaga coberta.</main></body></html>"""


class MonitorTests(unittest.TestCase):
    def test_registry_and_pilot(self):
        s = load_sources()
        self.assertEqual(len(s), 50)
        self.assertEqual(sum(x["status"] != "EXCLUIDA" for x in s), 45)
        self.assertEqual(sum(x["status"] in ("LISTAGEM", "SITE") for x in s), 39)
        self.assertTrue(set(PILOT).issubset({x["nome"] for x in s}))

    def test_discover_rent_page(self):
        url = discover(LIST_HTML, "https://imobiliaria-teste.com.br/")
        self.assertEqual(url, "https://imobiliaria-teste.com.br/aluguel/residencial/")

    def test_listing_links_and_normalization(self):
        urls = detail_urls(LIST_HTML, "https://imobiliaria-teste.com.br/aluguel/residencial/")
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("/imovel/" in u for u in urls))
        self.assertEqual(normalized("https://www.imobiliaria-teste.com.br/imovel/134719?utm_source=a"),
                         "https://imobiliaria-teste.com.br/imovel/134719")

    def test_recognize_home_and_price(self):
        item = extract(DETAIL_HTML, "https://imobiliaria-teste.com.br/imovel/134719", "Teste")
        self.assertEqual(item["cidade"], "Florianópolis")
        self.assertEqual(item["quartos"], 2)
        self.assertEqual(item["total_mensal"], 2450.0)
        self.assertEqual(item["total_informado"], 2450.0)
        self.assertEqual(item["divergencia_preco"], "NAO")
        self.assertEqual(item["sacada"], "SIM")
        self.assertEqual(item["vaga_coberta"], "SIM")
        self.assertIsNotNone(item["id"])
        self.assertEqual(price("Aluguel R$ 1.900,00", "aluguel"), 1900.0)

    def test_sum_prices_and_city_from_url(self):
        html = """<h1>Kitnet/Conjugado 1 Quarto Fundos 25m²</h1><main>
        Valor Total: R$ 1.230,00. Aluguel: R$ 1.200,00.
        Condomínio: R$ 150,00. IPTU: R$ 30,00.</main>"""
        url = "https://imobiliariabiguacu.com.br/imovel/9853/kitnet-1-quarto-bigua%C3%A7u"
        d = extract(html, url, "Imobiliária Biguaçu")
        self.assertEqual(d["cidade"], "Biguaçu")
        self.assertEqual(d["total_informado"], 1230.0)
        self.assertEqual(d["total_mensal"], 1380.0)
        self.assertEqual(d["divergencia_preco"], "SIM")

    def test_missing_data_is_unknown(self):
        item = extract("<h1>Apartamento 1 quarto São José</h1><p>Aluguel: R$ 1.500,00</p>",
                       "https://imobiliaria-teste.com.br/imovel/9", "Teste")
        self.assertIsNone(item["total_mensal"])
        self.assertEqual(item["sacada"], "NÃO INFORMADO")
        self.assertEqual(item["vaga_coberta"], "NÃO INFORMADO")

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "state" / "catalog.json"
            self.assertEqual(json_load(p, {}), {})
            json_save(p, {"123": {"valor": 1000}})
            self.assertEqual(json_load(p, {})["123"]["valor"], 1000)

    def test_reject_insecure_url_before_request(self):
        scraper = PublicSession()
        self.assertEqual(scraper.allowed("http://imobiliaria-teste.com.br/")[0], False)
        self.assertEqual(scraper.allowed("file:///etc/passwd")[0], False)


    def test_sheet_row_contract_and_unknown_fields(self):
        d = {"id": "xyz123", "url": "https://example.com/imovel/100", "cidade": "Biguaçu",
             "imobiliaria": "Exemplo", "observado_em": "2026-11-10T08:21:00-03:00",
             "descoberto_em": "2026-11-10T08:21:00-03:00", "quartos": 1,
             "total_mensal": None, "aluguel": 1200.0, "divergencia_preco": "SIM"}
        row = sheet_row(d)
        self.assertEqual(len(row), 20)
        self.assertEqual(row[6], 1)
        self.assertEqual(row[11], "")
        self.assertEqual(row[18], "xyz123")
        self.assertEqual(row[19], "Revisar preco e atributos")
        self.assertEqual(money_number("R$ 1.380,00"), 1380.0)
        self.assertEqual(money_number("1380,00"), 1380.0)
        self.assertEqual(money_number("1380"), 1380.0)
        self.assertIsNone(money_number(""))

    def test_sheet_sync_creates_new_rows_and_marks_price_change(self):
        records = [
            {"id":"fresh","url":"https://example.com/imovel/1","cidade":"Biguaçu",
             "imobiliaria":"Exemplo","observado_em":"2026-11-10T08:00:00-03:00",
             "descoberto_em":"2026-11-10T08:00:00-03:00","total_mensal":1380.0,
             "aluguel":1200.0,"condominio":150.0,"iptu":30.0},
            {"id":"existing","url":"https://example.com/imovel/2","cidade":"Biguaçu",
             "imobiliaria":"Exemplo","observado_em":"2026-11-10T08:00:00-03:00",
             "descoberto_em":"2026-11-10T08:00:00-03:00","total_mensal":1700.0,
             "aluguel":1600.0,"condominio":80.0,"iptu":20.0}
        ]
        class Sheet:
            def __init__(self, existing=None):
                self.existing = existing or []
                self.appended = []
                self.updated = []
            def get(self,*args,**kwargs): return self.existing
            def append_rows(self,rows,**kwargs):
                self.appended.extend(rows)
                assert kwargs["value_input_option"] == "RAW"
            def batch_update(self,updates,**kwargs):
                self.updated.extend(updates)
                assert kwargs["value_input_option"] == "RAW"
        oldrow = [None]*20
        oldrow[11] = "R$ 1.500,00"
        oldrow[17] = "https://example.com/imovel/2"
        oldrow[18] = "existing"
        ads = Sheet([[""]*20,oldrow])
        hist = Sheet()
        class Document:
            def worksheet(self,name): return ads if name=="Anúncios" else hist
        class FakeClient:
            def open_by_key(self,key):
                assert key=="test-sheet"
                return Document()
        fake_gspread = types.SimpleNamespace(
            service_account_from_dict=lambda creds: FakeClient())
        encoded = base64.b64encode(json.dumps({"type":"service_account"}).encode()).decode()
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON_B64":encoded,
                                     "GOOGLE_SHEET_ID":"test-sheet"}), patch.dict(
                                         sys.modules,{"gspread":fake_gspread}):
            status = sheet_sync(records)
        self.assertEqual(status,"SINCRONIZADO_NOVOS_1_PRECOS_1")
        self.assertEqual(len(ads.appended),1)
        self.assertEqual(ads.appended[0][18],"fresh")
        self.assertEqual(len(ads.updated),3)
        self.assertEqual(len(hist.appended),1)
        self.assertEqual(hist.appended[0][3],1500.0)
        self.assertEqual(hist.appended[0][4],1700.0)

    def test_sheet_sync_requires_credentials(self):
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON_B64":"",
                                     "GOOGLE_SHEET_ID":""}):
            self.assertEqual(sheet_sync([]),"AGUARDANDO_CREDENCIAL")



if __name__ == "__main__":
    unittest.main()
