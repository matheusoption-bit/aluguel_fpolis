#!/usr/bin/env python3
"""Publica somente campos de anuncios PUBLICOS em CSV para IMPORTDATA do Google Sheets.

Nao inclui preferências pessoais, credenciais, e-mails ou endereco completo.
"""
import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ANUNCIOS = [
    ("ID", "id"),
    ("Imobiliária", "imobiliaria"),
    ("Título público do anúncio", "titulo"),
    ("Cidade", "cidade"),
    ("Quartos", "quartos"),
    ("Sacada", "sacada"),
    ("Vaga coberta", "vaga_coberta"),
    ("Total mensal (R$)", "total_mensal"),
    ("Aluguel (R$)", "aluguel"),
    ("Condomínio (R$)", "condominio"),
    ("IPTU (R$)", "iptu"),
    ("Preço divergente?", "divergencia_preco"),
    ("Link do imóvel", "url"),
    ("Visto pela primeira vez", "descoberto_em"),
    ("Última observação", "observado_em"),
]
STATUS = ["imobiliaria", "status", "detalhes", "novos", "diagnostico"]
STATUS_HEADER = ["Imobiliária", "Resultado técnico", "Anúncios lidos", "Novos", "Diagnóstico"]


def safe_text(value):
    s = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    # Evita formula injection, mesmo em consumidores CSV que avaliam formulas.
    if s.startswith(("=", "+", "-", "@", "\t")):
        s = "'" + s
    return s[:500]


def as_number(value):
    s = str(value or "").strip()
    if not s:
        return ""
    try:
        n = float(s)
        if n != n or abs(n) > 1e10:
            return ""
        return round(n, 2)
    except ValueError:
        return ""


def valid_url(url):
    p = urlparse(str(url))
    return p.scheme == "https" and p.hostname and p.hostname != "localhost" and not p.username and not p.password


def build_anuncios(source):
    with source.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    data = []
    for row in rows:
        if not re.fullmatch(r"[a-f0-9]{20}", row.get("id", "")):
            continue
        if not valid_url(row.get("url", "")):
            continue
        record = []
        for title, key in ANUNCIOS:
            v = row.get(key, "")
            if key in ("total_mensal", "aluguel", "condominio", "iptu"):
                record.append(as_number(v))
            elif key == "quartos":
                record.append(int(v) if str(v).isdigit() else "")
            else:
                record.append(safe_text(v))
        data.append(record)
    return [x[0] for x in ANUNCIOS], data


def build_status(source):
    with source.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    return STATUS_HEADER, [[safe_text(row.get(k, "")) for k in STATUS] for row in rows]


def save_csv(destination, header, rows):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--statuses", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    args = p.parse_args()
    h, rows = build_anuncios(args.catalog)
    save_csv(args.destination / "anuncios_publicos.csv", h, rows)
    sh, sr = build_status(args.statuses)
    save_csv(args.destination / "status_fontes.csv", sh, sr)
    print(json.dumps({"anuncios_publicados": len(rows), "fontes": len(sr)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
