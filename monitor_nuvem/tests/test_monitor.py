"""Testes sem internet, sem credenciais e sem alterar a planilha."""
import tempfile
import unittest
from pathlib import Path

from monitor_nuvem.monitor import (
    PILOT, PublicSession, detail_urls, discover, extract, json_load, json_save,
    load_sources, normalized, price,
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


if __name__ == "__main__":
    unittest.main()
