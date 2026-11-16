import csv
import tempfile
import unittest
from pathlib import Path
from monitor_nuvem.public_export import build_anuncios, build_status, safe_text, valid_url, save_csv


class PublishTests(unittest.TestCase):
    def test_public_csv_keeps_only_approved_columns(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "input.csv"
            with file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["id","imobiliaria","titulo","cidade","quartos","sacada","vaga_coberta","total_mensal","aluguel","condominio","iptu","divergencia_preco","url","descoberto_em","observado_em","endereco_pessoal"],delimiter=";")
                writer.writeheader()
                writer.writerow({"id":"a"*20,"imobiliaria":"Imóveis Exemplo","titulo":"=malicious()","cidade":"São José","quartos":"2","total_mensal":"1380.0","url":"https://example.com/imovel/1","endereco_pessoal":"SEGREDO"})
            header, rows = build_anuncios(file)
            self.assertEqual(len(rows),1)
            self.assertNotIn("endereco_pessoal",header)
            self.assertNotIn("SEGREDO",str(rows))
            self.assertTrue(rows[0][2].startswith("'="))
            self.assertEqual(rows[0][4],2)
            self.assertEqual(rows[0][7],1380.0)
            dest=Path(d)/"out.csv"
            save_csv(dest,header,rows)
            self.assertIn("Imóveis Exemplo",dest.read_text(encoding="utf-8"))

    def test_reject_bad_urls(self):
        for x in ["http://example.com/imovel/1","file:///etc/passwd","https://user:pass@example.com","https://localhost"]:
            self.assertFalse(valid_url(x))
        self.assertTrue(valid_url("https://ibagy.com.br/imovel/123"))
