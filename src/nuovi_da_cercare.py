"""Elenca gli indirizzi di produzione, i bolli CE e i produttori nominati che compaiono in data/elementi.csv ma NON hanno
ancora una riga in data/aziende.csv (cioe' non sono mai stati cercati). Scrive data/nuovi_da_cercare.csv.

Uso:  python -I src/nuovi_da_cercare.py

Si usa lo stesso abbinamento di src/sito.py (indirizzo esatto, senza provincia, stessa via, approssimato; poi bollo CE;
poi produttore nominato): quello che il sito mostrerebbe come «azienda non cercata». Chi fa la ricerca successiva
(un agente o una persona) parte da questo elenco e aggiunge le righe a data/aziende.csv con fonte e certezza.
Le sedi di Peck (via Spadari 9) non si cercano.
"""
import csv
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sito  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAMPI = ["tipo_chiave", "chiave", "frase_esempio", "paese", "n_prodotti", "prodotti", "pagine_peck", "prima_vista",
         "ultima_vista", "in_vendita", "nota"]


def main():
    elementi = sito.leggi_csv("elementi")
    az = sito.Aziende(sito.leggi_csv("aziende"))
    gruppi = OrderedDict()
    for r in elementi:
        if r["sede_peck"] == "si" or not (r["indirizzo"] or r["comune"] or r["bollo_ce"] or r["produttore_nominato"]):
            continue
        a, _ = az.cerca(r)
        if a:
            continue
        if r["indirizzo"] or r["comune"]:
            tipo, chiave = "indirizzo", sito.chiave_indirizzo(r)
        elif r["bollo_ce"]:
            tipo, chiave = "bollo_ce", r["bollo_ce"]
        else:
            tipo, chiave = "produttore", r["produttore_nominato"]
        gruppi.setdefault((tipo, sito.nz(chiave)), []).append((chiave, r))
    righe = []
    for (tipo, _), lst in gruppi.items():
        rs = [r for _, r in lst]
        prima = [r["prima_vista"] for r in rs if r.get("prima_vista")]
        ultima = [r["ultima_vista"] for r in rs if r.get("ultima_vista")]
        prodotti = list(OrderedDict.fromkeys(r["nome_elemento"] for r in rs))
        pagine = list(OrderedDict.fromkeys(r["nome_pagina"] for r in rs))
        righe.append({
            "tipo_chiave": tipo, "chiave": lst[0][0], "frase_esempio": rs[0]["frase_origine"],
            "paese": next((r["paese"] for r in rs if r["paese"]), ""),
            "n_prodotti": len(prodotti), "prodotti": " | ".join(prodotti), "pagine_peck": " | ".join(pagine),
            "prima_vista": min(prima) if prima else "", "ultima_vista": max(ultima) if ultima else "",
            "in_vendita": "si" if any(r.get("in_vendita") == "si" for r in rs) else "no",
            "nota": rs[0]["nota"]})
    righe.sort(key=lambda r: (r["in_vendita"] != "si", r["tipo_chiave"], r["chiave"].lower()))
    with open(ROOT / "data" / "nuovi_da_cercare.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPI)
        w.writeheader()
        w.writerows(righe)
    print(f"nuovi_da_cercare.csv: {len(righe)} voci non presenti in aziende.csv "
          f"({sum(1 for r in righe if r['tipo_chiave'] == 'indirizzo')} indirizzi, "
          f"{sum(1 for r in righe if r['tipo_chiave'] == 'bollo_ce')} bolli CE, "
          f"{sum(1 for r in righe if r['tipo_chiave'] == 'produttore')} produttori nominati)")
    for r in righe:
        print("  ", r["in_vendita"], r["tipo_chiave"], r["chiave"], "<-", r["prodotti"][:90])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
