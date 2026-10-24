"""Confronta i produttori di vino nominati nelle box Peck con le cantine dell'enoteca.

Uso:  python -I src/vini_box.py      (dopo src/vini.py e src/extract.py)

Legge data/elementi.csv (box dello shop) e data/cantine.csv + data/vini.csv (carta dell'enoteca)
e scrive data/vini_nelle_box.csv: una riga per produttore nominato nelle box.
- corrispondenza: "esatta" (la cantina ha lo stesso nome), "approssimata" (c'e' solo una cantina
  collegata, con nome diverso) o "non in carta".
- etichetta_in_carta: "si" se nella carta c'e' un'etichetta con le stesse parole distintive del
  vino della box (annata inclusa, quando c'e'); e' un controllo per parole, da verificare a occhio.
"""
import csv
import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# produttore come lo scrive Peck: (modello per trovarlo in nome_elemento/produttore_nominato,
#   cantine di Winerim con lo stesso nome, cantine collegate ma con nome diverso, nota)
PRODUTTORI = [
    ("Krug", r"\bkrug\b", ["Krug"], [], ""),
    ("Ruinart", r"\bruinart\b", ["Ruinart"], [], ""),
    ("Dom Pérignon", r"perignon", ["Dom Pérignon"], ["Moët & Chandon"],
     "la box dice 'coffret Moët Hennessy': stesso gruppo di Moët & Chandon"),
    ("Bellavista", r"\bbellavista\b", ["Bellavista"], [], "nelle box il nome compare anche come titolo ('Bellavista per Pranzo')"),
    ("Berlucchi", r"\bberlucchi\b", ["Berlucchi"], [], ""),
    ("Banfi", r"\bbanfi\b", ["Banfi"], [], ""),
    ("Frescobaldi", r"\bfrescobaldi\b", ["Frescobaldi"],
     ["Castello Pomino", "Castello Nipozzano", "Tenuta Luce"],
     "Frescobaldi e' un gruppo: in carta alcune sue tenute hanno una cantina a parte"),
    ("Damilano", r"\bdamilano\b", ["Damilano"], [], ""),
    ("Ferrari", r"\bferrari\b", ["Ferrari"], ["Azienda Agricola Lunelli"],
     "la box ha 'Lunelli Riserva' di Ferrari; in carta c'e' anche l'Azienda Agricola Lunelli (famiglia Lunelli, altro marchio)"),
    ("Tenuta San Guido", r"san guido", ["Tenuta San Guido"], [], "nella box il vino e' il Guidalberto"),
    ("Ca' del Bosco", r"ca.? del bosco", ["Ca' del Bosco"], [], ""),
    ("Nonino", r"\bnonino\b", [], [], "distillati (grappa, amaro): l'enoteca ha un'altra carta per i distillati"),
    ("TV 1000", r"tv 1000|prosecco valdobbiadene", [], [],
     "il Prosecco 'PECK' della box e' spumantizzato da TV 1000, ma TV 1000 non e' in carta; in carta c'e' una cantina 'Peck' (marchio di Peck, con anche un Prosecco Valdobbiadene)"),
]
GENERICI = {"coffret", "brut", "riserva", "champagne", "franciacorta", "barolo", "brunello", "montalcino",
            "chianti", "trento", "doc", "docg", "peck", "edizione", "ed", "cuvee", "extra", "nature", "dom",
            "toscana", "valdobbiadene", "prosecco", "grappa", "amaro", "cl", "ml", "gr", "lt"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def leggi(nome):
    with open(DATA / nome, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parole(s, escludi=()):
    return {t for t in norm(s).split() if t not in GENERICI and t not in escludi and len(t) > 1}


def main():
    elementi, cantine, vini = leggi("elementi.csv"), leggi("cantine.csv"), leggi("vini.csv")
    carta = {norm(c["cantina"]): c for c in cantine}
    per_cantina = {}
    for v in vini:
        per_cantina.setdefault(v["cantina"], {}).setdefault(v["id"], v)  # un'etichetta una volta

    righe = []
    for nome, modello, esatte, collegate, nota in PRODUTTORI:
        rx = re.compile(modello)
        trovati = {}  # nome elemento -> insieme di pagine
        for e in elementi:
            if rx.search(norm(e["nome_elemento"])) or rx.search(norm(e["produttore_nominato"])):
                # niente 'Bellavista per Pranzo' & simili: conta solo l'elemento, non il titolo della box
                trovati.setdefault(e["nome_elemento"], set()).add(e["nome_pagina"])
        if not trovati:
            continue
        cant_esatte = [carta[norm(c)] for c in esatte if norm(c) in carta]
        cant_coll = [carta[norm(c)] for c in collegate if norm(c) in carta]
        if cant_esatte:
            corr = "esatta"
        elif cant_coll:
            corr = "approssimata"
        else:
            corr = "non in carta"
        usate = cant_esatte + cant_coll
        # stessa etichetta?
        etichette = [v for c in usate for v in per_cantina.get(c["cantina"], {}).values()]
        stesse = []
        for el in trovati:
            pw = parole(el, escludi=parole(nome))
            anno = re.findall(r"\b(?:19|20)\d\d\b", el)
            pw -= set(anno)
            for v in etichette:
                nw = parole(v["nome"])
                if pw and nw and len(pw & nw) / min(len(pw), len(nw)) >= 0.6 and (not anno or v["annata"] in anno):
                    stesse.append(v["nome"] + (f" {v['annata']}" if v["annata"] else ""))
                    break
        righe.append({
            "produttore_nelle_box": nome,
            "n_box": len({p for ps in trovati.values() for p in ps}),
            "box": " | ".join(sorted({p for ps in trovati.values() for p in ps})),
            "vini_nelle_box": " | ".join(sorted(trovati)),
            "corrispondenza": corr,
            "cantina_in_carta": " | ".join(c["cantina"] for c in usate),
            "n_etichette_in_carta": sum(int(c["n_etichette"]) for c in usate),
            "etichetta_in_carta": "si" if stesse else ("no" if usate else ""),
            "etichette_simili": " | ".join(stesse),
            "nota": nota,
        })
    colonne = list(righe[0])
    with open(DATA / "vini_nelle_box.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colonne)
        w.writeheader()
        w.writerows(righe)
    for r in righe:
        print(f"{r['produttore_nelle_box']:18} {r['corrispondenza']:13} {r['n_etichette_in_carta']:>3}  "
              f"{r['etichetta_in_carta']:3} {r['etichette_simili'][:80]}")


if __name__ == "__main__":
    main()
