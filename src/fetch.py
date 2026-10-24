"""Scarica le pagine elenco e le pagine prodotto dello shop Peck in data/raw/.

Uso:  python -I src/fetch.py [--pausa SECONDI] [--forza]

- Una sola richiesta alla volta, con pausa fra l'una e l'altra
  (default 10 secondi: e' il Crawl-delay dichiarato in robots.txt dello shop).
- I file gia' scaricati vengono saltati (usare --forza per riscaricarli).
- Solo pagine in italiano (/it/...).
"""
import argparse
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://shop.peck.it"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Elenchi da percorrere (il secondo e' la categoria "gift box", incluso per controllo)
ELENCHI = {
    "negozio-online": "/it/negozio-online",
    "gift-box": "/it/negozio-online/gift-box",
}
MAX_PAGINE = 20  # paracadute

# nell'elenco ogni prodotto e' un <div class="col-item ..."> con un link /it/<slug>
RE_ITEM = re.compile(r'class="col-item[^"]*"[^>]*>\s*<div class="cont_img"><a href="(/it/[^"?#]+)"')


class Scaricatore:
    def __init__(self, pausa, forza):
        self.pausa = pausa
        self.forza = forza
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        self.ultima = 0.0

    def get(self, path, nome_file):
        """Restituisce il testo della pagina, scaricandola solo se non e' gia' su disco."""
        f = RAW / nome_file
        if f.exists() and not self.forza:
            return f.read_text(encoding="utf-8")
        attesa = self.pausa - (time.time() - self.ultima)
        if attesa > 0:
            time.sleep(attesa)
        r = self.s.get(BASE + path, timeout=30)
        self.ultima = time.time()
        r.raise_for_status()
        r.encoding = "utf-8"
        f.write_text(r.text, encoding="utf-8")
        print("scaricato", path, len(r.text), "caratteri", flush=True)
        return r.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pausa", type=float, default=10.0)
    ap.add_argument("--forza", action="store_true")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    d = Scaricatore(a.pausa, a.forza)

    prodotti = []  # slug in ordine di apparizione
    for nome, path in ELENCHI.items():
        for p in range(MAX_PAGINE):
            html = d.get(f"{path}?page={p}", f"elenco_{nome}_p{p}.html")
            slugs = RE_ITEM.findall(html)
            if not slugs:
                break  # pagina vuota: finito (il file resta, cosi' un secondo giro non lo riscarica)
            for s in slugs:
                if s not in prodotti:
                    prodotti.append(s)
    print(len(prodotti), "prodotti trovati negli elenchi", flush=True)

    for s in prodotti:
        d.get(s, "prodotto_" + s.rsplit("/", 1)[1] + ".html")
    print("fatto")


if __name__ == "__main__":
    sys.exit(main())
