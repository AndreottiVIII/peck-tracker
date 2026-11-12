"""Archivia IN LOCALE le foto dei prodotti dello shop Peck (per l'archivio personale del proprietario).

Uso:  python -I src/foto_shop.py [--data AAAA-MM-GG] [--pausa SECONDI]

Le foto vanno in archivio/foto_shop/<data della fotografia>/ con il loro nome originale, piu' un indice
(indice.csv: id_prodotto, id_woo, nome, url_pagina, foto_url, file, stato, tipo, byte). La cartella archivio/ e' nel
.gitignore: le foto NON finiscono mai su GitHub ne' in docs/. Il sito pubblico continua a collegare le foto dai
server di Peck (non le copia); queste copie servono solo a non perderle se Peck le cambia o le toglie.
(Condizioni di vendita Peck, art. 34: vietata la riproduzione dei contenuti del sito: uso solo personale, privato.)

Quali foto: tutte quelle di tutti i prodotti dell'ultima fotografia dell'API (data/raw/shop2/<data>/api_p*.json), piu'
gli indirizzi delle foto del vecchio shop (foto_vecchia_url di data/prodotti.csv) se caricano ancora. Una pausa
(default 1 s) fra una richiesta e l'altra, robots.txt rispettato. Una foto gia' archiviata in un'altra data (stesso
indirizzo) non si riscarica. In data/prodotti.csv la colonna foto_locale dice il file archiviato (mai un'immagine
nel repository: solo il percorso).

Non fa parte dell'aggiornamento settimanale (su GitHub non c'e' archivio/): si lancia a mano sul proprio computer.
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_shop2 import RAW2, UA, ultima_cartella  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ARCHIVIO = ROOT / "archivio" / "foto_shop"
CAMPI_INDICE = ["id_prodotto", "id_woo", "nome", "url_pagina", "foto_url", "file", "stato", "tipo", "byte"]


def leggi_csv(f):
    if not Path(f).exists():
        return []
    with open(f, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def nome_file(url):
    n = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or "foto"
    return re.sub(r'[<>:"/\\|?*]', "_", n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="")
    ap.add_argument("--pausa", type=float, default=1.0)
    a = ap.parse_args()
    cartella = (RAW2 / a.data) if a.data else ultima_cartella()
    if not cartella or not cartella.exists():
        sys.exit("nessuna fotografia in data/raw/shop2: lanciare prima src/fetch_shop2.py")
    data = cartella.name
    dest = ARCHIVIO / data
    dest.mkdir(parents=True, exist_ok=True)

    prodotti = leggi_csv(DATA / "prodotti.csv")
    per_woo = {p["id_woo"]: p for p in prodotti if p.get("id_woo")}
    # (url foto, id_woo o "", nome, url pagina)
    voci, visti = [], set()
    for f in sorted(cartella.glob("api_p*.json")):
        for p in json.loads(f.read_text(encoding="utf-8")):
            riga = per_woo.get(str(p["id"]), {})
            for img in p.get("images", []):
                u = img.get("src") or ""
                if u and u not in visti:
                    visti.add(u)
                    voci.append((u, str(p["id"]), riga.get("id_prodotto", ""), riga.get("nome", p["name"]), p["permalink"], "nuovo shop"))
    for r in prodotti:
        u = r.get("foto_vecchia_url") or ""
        if u and u not in visti:
            visti.add(u)
            voci.append((u, r.get("id_woo", ""), r["id_prodotto"], r["nome"], r.get("url_vecchio") or r["url"], "vecchio shop"))
    print(f"{len(voci)} indirizzi di foto da archiviare in {dest}", flush=True)

    # foto gia' archiviate in altre date
    gia = {}
    for ind in ARCHIVIO.glob("*/indice.csv"):
        if ind.parent.name == data:
            continue
        for r in leggi_csv(ind):
            if r["stato"] in ("scaricata", "gia archiviata") and r["file"]:
                gia.setdefault(r["foto_url"], f"archivio/foto_shop/{ind.parent.name}/{r['file']}")

    rp = urllib.robotparser.RobotFileParser()
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    rp.parse(s.get("https://peck.it/robots.txt", timeout=30).text.splitlines())
    ultima = 0.0
    righe, usati = [], set()
    for url, id_woo, idp, nome, pagina, quale in voci:
        base = {"id_prodotto": idp, "id_woo": id_woo, "nome": nome, "url_pagina": pagina, "foto_url": url,
                "file": "", "stato": "", "tipo": "", "byte": ""}
        if url in gia:
            righe.append({**base, "file": gia[url].rsplit("/", 1)[-1], "stato": "gia archiviata",
                          "tipo": gia[url]})
            continue
        if urlsplit(url).netloc.endswith("peck.it") and not rp.can_fetch(UA, url):
            righe.append({**base, "stato": "vietata da robots.txt"})
            continue
        attesa = a.pausa - (time.time() - ultima)
        if attesa > 0:
            time.sleep(attesa)
        try:
            r = s.get(url, timeout=60, allow_redirects=True)
        except requests.RequestException as e:
            ultima = time.time()
            righe.append({**base, "stato": f"errore: {type(e).__name__}"})
            continue
        ultima = time.time()
        tipo = r.headers.get("Content-Type", "").split(";")[0]
        if r.status_code != 200 or not tipo.startswith("image/"):
            righe.append({**base, "stato": f"non carica (HTTP {r.status_code}{', ' + tipo if tipo else ''}"
                                           f"{', ' + str(r.history[0].status_code) + ' ->' if r.history else ''})".replace(", )", ")")})
            print("  non carica:", url, r.status_code, tipo, flush=True)
            continue
        nome_f = nome_file(url)
        if nome_f in usati or (dest / nome_f).exists() and (dest / nome_f).stat().st_size != len(r.content):
            nome_f = f"{id_woo or idp}_{nome_f}"
        usati.add(nome_f)
        (dest / nome_f).write_bytes(r.content)
        righe.append({**base, "file": nome_f, "stato": "scaricata", "tipo": tipo, "byte": len(r.content)})
        print("  ok", nome_f, len(r.content), flush=True)

    with open(dest / "indice.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPI_INDICE)
        w.writeheader()
        w.writerows(righe)

    # foto_locale in data/prodotti.csv (solo il percorso, mai l'immagine)
    percorso = {}
    for r in righe:
        if r["stato"] == "scaricata":
            percorso[r["foto_url"]] = f"archivio/foto_shop/{data}/{r['file']}"
        elif r["stato"] == "gia archiviata":
            percorso[r["foto_url"]] = r["tipo"]
    if prodotti:
        campi = list(prodotti[0].keys())
        n = 0
        for p in prodotti:
            nuovo = percorso.get(p.get("foto_url", ""))
            if nuovo and p.get("foto_locale") != nuovo:
                p["foto_locale"] = nuovo
                n += 1
        with open(DATA / "prodotti.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=campi)
            w.writeheader()
            w.writerows(prodotti)
        print(f"foto_locale aggiornata per {n} prodotti")
    print(f"scaricate {sum(1 for r in righe if r['stato'] == 'scaricata')}, gia' archiviate "
          f"{sum(1 for r in righe if r['stato'] == 'gia archiviata')}, non caricano "
          f"{sum(1 for r in righe if r['stato'].startswith('non carica'))}; indice: {dest / 'indice.csv'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
