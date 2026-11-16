"""Scarica lo shop NUOVO di Peck (peck.it/shop, WooCommerce) in una cartella datata di data/raw/shop2/.

Uso:  python -I src/fetch_shop2.py [--pausa SECONDI] [--data AAAA-MM-GG] [--forza]

Lo shop vecchio (shop.peck.it, Drupal) non esiste piu': dal 12/11/2026 reindirizza a peck.it.
Il nuovo shop ha una API pubblica (Store API di WooCommerce) che il robots.txt non vieta:

    https://peck.it/wp-json/wc/store/v1/products?per_page=100&page=1

L'API da' nome, prezzo, categorie, foto e la «Descrizione» (per le box: l'elenco dei contenuti).
Le frasi di origine ("Prodotto in...", "Confezionato da...", bolli CE) NON sono nell'API: stanno
solo nella pagina HTML del prodotto, nel riquadro «Scheda prodotto». Per questo si scarica anche
la pagina di ogni prodotto (una al giorno di fotografia, 2 secondi di pausa).

Scrive in data/raw/shop2/<data>/ (cartella esclusa da git):
    api_p1.json, api_p2.json ...     le pagine dell'API, come arrivano
    p<id>.html                      la pagina di ogni prodotto
    indice.json                     id, slug, indirizzo e data di scarico di ogni pagina

Rispetta robots.txt (riletto a ogni giro) e fa una richiesta alla volta. Non salva ne' pubblica
nulla di nuovo: i testi di Peck restano in data/raw (non su git); in data/ finiscono solo le
frasi brevi sull'origine, come per lo shop vecchio (condizioni di vendita Peck, art. 34: vietata
la riproduzione di immagini e testi del sito).
"""
import argparse
import json
import sys
import time
import urllib.robotparser
from datetime import date
from pathlib import Path

import requests

BASE = "https://peck.it"
API = BASE + "/wp-json/wc/store/v1/products"
RAW2 = Path(__file__).resolve().parent.parent / "data" / "raw" / "shop2"
UA = "peck-tracker (github.com/AndreottiVIII/peck-tracker)"
PER_PAGINA = 100
MAX_PAGINE = 10   # paracadute


class Scaricatore:
    def __init__(self, pausa):
        self.pausa = pausa
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        self.ultima = 0.0
        self.rp = urllib.robotparser.RobotFileParser()
        r = self.s.get(BASE + "/robots.txt", timeout=30)
        r.raise_for_status()
        self.rp.parse(r.text.splitlines())

    def consentito(self, url):
        return self.rp.can_fetch(UA, url) and self.rp.can_fetch("*", url)

    def get(self, url, **kw):
        if not self.consentito(url):
            raise RuntimeError("vietato da robots.txt: " + url)
        attesa = self.pausa - (time.time() - self.ultima)
        if attesa > 0:
            time.sleep(attesa)
        r = self.s.get(url, timeout=60, **kw)
        self.ultima = time.time()
        r.raise_for_status()
        return r


def scarica(data, pausa, forza=False):
    """Scarica lo shop in data/raw/shop2/<data>/. Restituisce la cartella, o None se l'API non risponde."""
    cartella = RAW2 / data
    cartella.mkdir(parents=True, exist_ok=True)
    d = Scaricatore(pausa)
    prodotti = []
    for n in range(1, MAX_PAGINE + 1):
        r = d.get(API, params={"per_page": PER_PAGINA, "page": n})
        pagina = r.json()
        (cartella / f"api_p{n}.json").write_bytes(r.content)
        prodotti += pagina
        totale = int(r.headers.get("X-WP-Total", len(prodotti)))
        print(f"API pagina {n}: {len(pagina)} prodotti (totale dichiarato {totale})", flush=True)
        if len(pagina) < PER_PAGINA or len(prodotti) >= totale:
            break
    if not prodotti:
        print("l'API non ha restituito nessun prodotto", flush=True)
        return None

    indice = []
    for p in prodotti:
        f = cartella / f"p{p['id']}.html"
        if not (f.exists() and not forza):
            try:
                r = d.get(p["permalink"])
                r.encoding = "utf-8"
                f.write_text(r.text, encoding="utf-8")
                print("scaricata", p["permalink"], len(r.text), "caratteri", flush=True)
            except Exception as e:      # una pagina che manca non ferma le altre
                print("ERRORE", p["permalink"], e, flush=True)
                continue
        indice.append({"id": p["id"], "slug": p["slug"], "url": p["permalink"], "file": f.name,
                       "data": data})
    (cartella / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"fatto: {len(prodotti)} prodotti dall'API, {len(indice)} pagine in {cartella}", flush=True)
    return cartella


def ultima_cartella():
    """La fotografia piu' recente gia' su disco (o None)."""
    if not RAW2.exists():
        return None
    c = sorted(x for x in RAW2.iterdir() if x.is_dir() and (x / "api_p1.json").exists())
    return c[-1] if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--data", default=date.today().isoformat())
    ap.add_argument("--forza", action="store_true")
    a = ap.parse_args()
    return 0 if scarica(a.data, a.pausa, a.forza) else 1


if __name__ == "__main__":
    sys.exit(main())
