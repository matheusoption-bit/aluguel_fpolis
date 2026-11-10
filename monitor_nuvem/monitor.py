#!/usr/bin/env python3
"""Monitor diario de anuncios publicos. Piloto contido, sem bypass de bloqueios."""
import argparse
import base64
import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT, STATE = ROOT / "out", ROOT / "state"
AGENT = "MonitorPublicoAluguel/0.3 (contato via repositorio)"
CITIES = ("Florianópolis", "São José", "Biguaçu", "Palhoça")
PILOT = ("Ibagy Imóveis", "San Remo Imóveis", "Kabral Imóveis", "Adriano Imóveis", "Imobiliária Biguaçu")
RENT = re.compile(r"alugar|aluguel|loca[cç][aã]o|para[-/]alugar", re.I)
HOME = re.compile(r"\b(apartamento|casa|kitnet|studio|loft|quitinete|sobrado|flat)\b", re.I)
INDIVIDUAL = re.compile(r"/(?:im[oó]vel|imoveis|anuncio|apartamento|casa|propriedade)s?/(?:\d{3,}|[^/]+/\d{3,}|[^/]+/[^/]+/\d{3,})", re.I)
MONEY = re.compile(r"R\$\s*([\d.]+,\d{2})")
NUM = re.compile(r"\b(\d{1,2})\s*(?:quartos?|dormit[oó]rios?)\b", re.I)

def timestamp():
    return datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds")

def normalized(url):
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", p.path).rstrip("/") or "/"
    q = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not k.startswith("utm_") and k not in ("fbclid", "gclid")))
    return urlunparse(("https", host, path, "", q, ""))

def same_site(a, b):
    x, y = urlparse(a).hostname or "", urlparse(b).hostname or ""
    return x.lower().removeprefix("www.") == y.lower().removeprefix("www.")

def load_sources():
    with (ROOT / "fontes.tsv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def json_load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def json_save(path, data):
    path.parent.mkdir(exist_ok=True, parents=True)
    p = path.with_suffix(".tmp")
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    p.replace(path)

class PublicSession:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
        self.robot = {}
        self.last = {}
    def allowed(self, url):
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname:
            return False, "URL_NAO_HTTPS"
        host = p.hostname.lower()
        if host not in self.robot:
            try:
                r = self.session.get("https://" + host + "/robots.txt", timeout=12, allow_redirects=False)
                if r.status_code == 404:
                    self.robot[host] = None
                elif r.status_code == 200:
                    rp = RobotFileParser()
                    rp.parse(r.text.splitlines())
                    self.robot[host] = rp
                else:
                    return False, "ROBOTS_INDISPONIVEL"
            except requests.RequestException:
                return False, "ROBOTS_INDISPONIVEL"
        rp = self.robot[host]
        if rp is not None and not rp.can_fetch(AGENT, url):
            return False, "ROBOTS_BLOQUEIA"
        return True, "PERMITIDO_PELO_ROBOTS"
    def get(self, url, origin):
        if not same_site(url, origin):
            return None, "DOMINIO_DIFERENTE"
        for _ in range(3):
            ok, why = self.allowed(url)
            if not ok:
                return None, why
            host = urlparse(url).hostname
            wait = 1.5 - (time.monotonic() - self.last.get(host, -100))
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.monotonic()
            try:
                r = self.session.get(url, timeout=18, allow_redirects=False)
            except requests.RequestException as e:
                return None, "REQUISICAO_FALHOU_" + type(e).__name__
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                next_url = urljoin(url, r.headers["Location"])
                if not same_site(next_url, origin):
                    return None, "REDIRECIONAMENTO_EXTERNO"
                url = next_url
                continue
            if r.status_code != 200:
                return None, "HTTP_" + str(r.status_code)
            if "html" not in r.headers.get("Content-Type", "text/html").lower():
                return None, "NAO_HTML"
            if len(r.content) > 2_000_000:
                return None, "HTML_GRANDE"
            return (r.url, r.text), "OK"
        return None, "REDIRECIONAMENTOS_DEMAIS"

def discover(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    options = []
    for a in soup.select("a[href]"):
        url = urljoin(page_url, a.get("href", ""))
        if same_site(page_url, url) and urlparse(url).scheme == "https" and RENT.search(a.get_text(" ", strip=True) + " " + url):
            path = urlparse(url).path
            if len(path) < 105:
                options.append((len(path), url))
    return sorted(options)[0][1] if options else None

def detail_urls(html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select("a[href]"):
        u = urljoin(url, a.get("href", ""))
        if not same_site(u, url) or urlparse(u).scheme != "https":
            continue
        path = urlparse(u).path
        if INDIVIDUAL.search(path) and (not re.search(r"/(?:comprar|venda)/", path, re.I) or RENT.search(path)):
            value = normalized(u)
            if value not in out and value != normalized(url):
                out.append(value)
    return out[:8]

def money(s):
    m = MONEY.search(s)
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None

def price(text, name):
    m = re.search(name + r"\s*[:\-]?\s*(R\$\s*[\d.]+,\d{2})", text, re.I)
    return money(m.group(1)) if m else None

def extract(html, url, source):
    soup = BeautifulSoup(html, "html.parser")
    h = soup.find("h1")
    og = soup.find("meta", property="og:title")
    title_tag = soup.find("title")
    title = ((h.get_text(" ", strip=True) if h else "")
             or (og.get("content", "") if og else "")
             or (title_tag.get_text(" ", strip=True) if title_tag else ""))
    if not title or not HOME.search(title):
        return None
    visible = BeautifulSoup(html, "html.parser")
    for x in visible.select("script,style,footer,nav"):
        x.decompose()
    text = visible.get_text(" ", strip=True)[:6500]
    locations = [title]
    for tag in soup.select("[itemprop=addressLocality]")[:3]:
        locations.append(tag.get_text(" ", strip=True))
    locale = " ".join(locations).lower()
    city = next((c for c in CITIES if c.lower() in locale), "")
    total = price(text, r"(?:valor\s+total(?:\s+aprox\.)?|total\s+mensal|pacote\s+mensal)")
    rent = price(text, r"(?:valor\s+do\s+)?aluguel")
    condo = price(text, r"condom[ií]nio")
    iptu = price(text, r"iptu")
    if total is None and all(v is not None for v in (rent, condo, iptu)):
        total = round(rent + condo + iptu, 2)
    m = NUM.search(text)
    code = hashlib.sha256(normalized(url).encode()).hexdigest()[:20]
    return {"id": code, "imobiliaria": source, "url": normalized(url), "titulo": title[:220],
            "cidade": city, "quartos": int(m.group(1)) if m else None, "total_mensal": total,
            "aluguel": rent, "condominio": condo, "iptu": iptu,
            "sacada": "SIM" if re.search(r"\b(sacada|varanda)\b", text, re.I) else "NÃO INFORMADO",
            "vaga_coberta": "SIM" if re.search(r"\b(vaga\s+coberta|garagem\s+coberta)\b", text, re.I) else "NÃO INFORMADO",
            "observado_em": timestamp()}

def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})

def sheet_sync(new):
    secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")
    key = os.getenv("GOOGLE_SHEET_ID", "")
    if not secret or not key:
        return "AGUARDANDO_CREDENCIAL"
    try:
        import gspread
        creds = json.loads(base64.b64decode(secret).decode("utf-8"))
        ws = gspread.service_account_from_dict(creds).open_by_key(key).worksheet("Anúncios")
        existing = set(ws.col_values(19)[1:])
        rows = []
        def safe(v):
            s = "" if v is None else str(v)
            return "'" + s if s.startswith(("=", "+", "-", "@")) else s
        for d in new:
            if d["id"] in existing:
                continue
            row = ["", d["observado_em"], d["observado_em"], "", "", "", d["quartos"],
                   "", d["vaga_coberta"], d["sacada"], "", d["total_mensal"],
                   d["aluguel"], d["condominio"], d["iptu"], d["imobiliaria"],
                   d["imobiliaria"], d["url"], d["id"], "Novo / revisar"]
            rows.append([safe(v) for v in row])
        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        return "SINCRONIZADO_" + str(len(rows))
    except Exception as e:
        return "FALHOU_" + type(e).__name__

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--max-details", type=int, default=8)
    args = ap.parse_args()
    all_sources = load_sources()
    eligible = [s for s in all_sources if s["status"] in ("LISTAGEM", "SITE")]
    pilot = [next(s for s in eligible if s["nome"] == name) for name in PILOT]
    ordered = pilot + [s for s in eligible if s["nome"] not in PILOT]
    chosen = ordered[:max(0, min(args.limit, len(ordered)))]
    cache = json_load(STATE / "catalog.json", {})
    fresh, run_rows, statuses = [], [], []
    fetcher = PublicSession()
    for i, s in enumerate(chosen, 1):
        found, fresh_count = 0, 0
        issue_codes = []
        page, code = fetcher.get(s["url"], s["url"])
        if page and s["status"] == "SITE":
            discovered = discover(page[1], page[0])
            if discovered:
                page, code = fetcher.get(discovered, s["url"])
            else:
                code, page = "SEM_LISTAGEM_LOCALIZADA", None
        if page:
            links = detail_urls(page[1], page[0])[:max(0, min(args.max_details, 20))]
            code = "LISTAGEM_SEM_DETALHES" if not links else "COLETA_PARCIAL"
            for link in links:
                detail, subcode = fetcher.get(link, s["url"])
                if not detail:
                    issue_codes.append(subcode)
                    continue
                record = extract(detail[1], detail[0], s["nome"])
                if not record:
                    issue_codes.append("SEM_TIPO_RESIDENCIAL_NO_TITULO")
                    continue
                found += 1
                old = cache.get(record["id"])
                record["descoberto_em"] = old.get("descoberto_em", record["observado_em"]) if old else record["observado_em"]
                if not old:
                    fresh.append(record)
                    fresh_count += 1
                cache[record["id"]] = record
            if links and not found:
                code = "DETALHES_NAO_RECONHECIDOS"
        diagnostico = ";".join(sorted(set(issue_codes))) if issue_codes else ""
        statuses.append({"imobiliaria": s["nome"], "status": code, "detalhes": found, "novos": fresh_count, "diagnostico": diagnostico})
        print(f"{i}/{len(chosen)} {s['nome']}: {code}; {found} anúncios reconhecidos; {fresh_count} novos; diagnostico: {diagnostico}", flush=True)
    for s in all_sources:
        if s in chosen:
            continue
        code = "EXCLUIDA_SEM_RESIDENCIAL" if s["status"] == "EXCLUIDA" else "SEM_SITE" if s["status"] == "PENDENTE_SITE" else "FORA_DO_PILOTO"
        statuses.append({"imobiliaria": s["nome"], "status": code, "detalhes": 0, "novos": 0})
    json_save(STATE / "catalog.json", cache)
    fields = ["id", "imobiliaria", "titulo", "cidade", "quartos", "sacada", "vaga_coberta",
              "total_mensal", "aluguel", "condominio", "iptu", "descoberto_em", "observado_em", "url"]
    write_csv(OUT / "catalogo.csv", list(cache.values()), fields)
    write_csv(OUT / "novos.csv", fresh, fields)
    write_csv(OUT / "status_fontes.csv", statuses, ["imobiliaria", "status", "detalhes", "novos", "diagnostico"])
    sync = sheet_sync(fresh)
    result = {"executado_em": timestamp(), "cadastradas": len(all_sources), "elegiveis": 45,
              "com_url": len(eligible), "testadas": len(chosen), "anuncios_no_historico": len(cache),
              "anuncios_novos": len(fresh), "planilha": sync, "situacoes": {
                  s: len([x for x in statuses if x["status"] == s])
                  for s in sorted({x["status"] for x in statuses})}}
    json_save(OUT / "resumo.json", result)
    print("RESUMO " + json.dumps(result, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
