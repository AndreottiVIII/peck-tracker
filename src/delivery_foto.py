"""Scarica le foto del catalogo delivery di Peck (le foto sono pubbliche, senza login).

    python -I src/delivery_foto.py

Legge data/locale/delivery_catalogo_2026-10-25.json (il catalogo resta sul computer, non si pubblica),
scarica ogni foto da https://delivery.peck.it/files/img_web/<img_web> in archivio/foto_delivery/ con lo
stesso nome, 0,5 secondi di pausa fra una richiesta e l'altra. Le foto gia' scaricate si saltano.
Le foto restano in archivio/ (escluso da git): sul sito si usa solo l'indirizzo web, mai il file.
"""
import json
import sys
import time
from pathlib import Path

import requests

RADICE = Path(__file__).resolve().parent.parent
CATALOGO = RADICE / "data" / "locale" / "delivery_catalogo_2026-10-25.json"
CARTELLA = RADICE / "archivio" / "foto_delivery"
BASE = "https://delivery.peck.it/files/img_web/"


def main():
    prodotti = json.loads(CATALOGO.read_text(encoding="utf-8"))["prodotti"]
    nomi = sorted({p["img_web"] for p in prodotti if p["img_web"]})
    CARTELLA.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (peck-tracker, progetto personale)"
    ok = saltate = errori = 0
    for i, nome in enumerate(nomi, 1):
        dest = CARTELLA / nome
        if dest.exists() and dest.stat().st_size > 0:
            saltate += 1
            continue
        try:
            r = s.get(BASE + nome, timeout=30)
            if r.status_code == 200 and r.content:
                dest.write_bytes(r.content)
                ok += 1
            else:
                errori += 1
                print("ERRORE", r.status_code, nome, flush=True)
        except requests.RequestException as e:
            errori += 1
            print("ERRORE", nome, e, flush=True)
        if i % 50 == 0:
            print(f"{i}/{len(nomi)}", flush=True)
        time.sleep(0.5)
    print(f"fatto: {ok} scaricate, {saltate} gia' presenti, {errori} errori su {len(nomi)}")


if __name__ == "__main__":
    sys.exit(main())
