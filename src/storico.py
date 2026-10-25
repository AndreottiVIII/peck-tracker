"""Storico: le frasi di origine di Peck in date passate, confrontate con lo shop di oggi.

Ogni "fotografia" del passato e' un file JSON in data/storico_fonti/<data>.json, per esempio una
pagina dello shop salvata a mano dall'autore del progetto. Per aggiungere una data nuova basta
aggiungere un altro file in quella cartella e rilanciare questo programma:

    python -I src/storico.py

Formato di un file (tutti i testi sono frasi brevi sull'origine, copiate come stanno sull'etichetta;
niente ingredienti ne' descrizioni):

    {
      "data_fonte": "2025-11-29",
      "fonte": "pagina shop Peck salvata dall'autore: box Il cuore del regno, 1.200 €",
      "prodotti": [
        {"nome": "MOSTARDA DI FRUTTA CANDITA 500 g",
         "frasi": ["Prodotto in Via Alfieri 16 - loc. Oriolo, Voghera (PV)"]},
        {"nome": "ANACARDI SALATI AL CURRY 200 g", "solo_peck": true},
        ...
      ]
    }

Campi facoltativi di un prodotto:
  frasi        elenco di frasi di origine (stringhe, oppure {"frase": ..., "campi": {...}, "nota": ...}
               dove "campi" corregge a mano indirizzo/cap/comune/provincia/... se il parser sbaglia)
  solo_peck    true = sull'etichetta c'e' solo l'indirizzo di Peck (titolare del marchio), nessuna frase
  elem_2026    nomi esatti di data/elementi.csv da confrontare (se il nome oggi e' scritto diverso);
               [] = il prodotto non c'e' piu' nello shop
  esito        forza il confronto ("uguale" / "diverso" / "non in vendita online nel 2026")
  nota         nota sulla riga 2025
  nota_confronto  spiegazione del confronto

Il confronto con data/elementi.csv (lo shop del 24 ottobre 2026) guarda i LUOGHI: stesso indirizzo
(via + comune) o stesso bollo CE = `uguale`; luoghi diversi, o una frase che oggi non c'e' piu' =
`diverso`; nome non piu' presente nello shop = `non in vendita online nel 2026`. L'indirizzo di Peck
(via Spadari 9) conta come "Peck" in entrambi gli anni. Scrive data/storico.csv.
"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import analizza, CORREZIONI  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FONTI = ROOT / "data" / "storico_fonti"
ELEMENTI = ROOT / "data" / "elementi.csv"
USCITA = ROOT / "data" / "storico.csv"

CAMPI = ["data_fonte", "fonte", "nome_prodotto", "ruolo", "frase_origine", "indirizzo", "cap", "comune",
         "provincia", "paese", "produttore_nominato", "bollo_ce", "sede_peck", "nota", "confronto_2026",
         "nome_elemento_2026", "frase_2026", "nota_confronto"]
CONFRONTI = ("uguale", "diverso", "non in vendita online nel 2026")


# ---------------------------------------------------------------- normalizzazione

def senza_accenti(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def nome_norm(s):
    """Per riconoscere lo stesso prodotto scritto in modo un po' diverso (maiuscole, 'GR.' / 'g', virgola)."""
    s = senza_accenti(s).lower()
    s = re.sub(r"\(web e confezioni\)", " ", s)
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    s = re.sub(r"\bgr?\b\.?", "g", s)
    s = re.sub(r"\bkg\.?", "kg", s)
    s = re.sub(r"(\d)\s*(g|kg|ml|cl|l)\b", r"\1\2", s)
    return re.sub(r"[^a-z0-9.]+", "", s)


def _pulisci(s):
    s = senza_accenti(s or "").lower().replace("ortobello", "orbetello")
    s = re.sub(r"^(via|viale|corso|piazza|strada|str\.?|contrada|c\.da|zona|loc\.?|localita|frazione|fraz\.?|"
               r"regione|reg\.?|c/)\s*", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "", s)


def bollo_norm(b):
    b = senza_accenti(b).upper()
    b = re.sub(r"^\s*(CE|UE|EC)\s*", "", b)
    b = re.sub(r"\s*(CE|UE|EC)\s*$", "", b)
    b = re.sub(r"^\s*(IT|ES)\s*(?=\S)", "", b)
    return re.sub(r"[^A-Z0-9]", "", b)


def luogo(r):
    """Chiave di confronto di una frase: 'P' = Peck, 'B:..' = bollo CE, 'A:..' = indirizzo."""
    if "spadari" in (r.get("indirizzo") or "").lower():
        return "P"
    if r.get("bollo_ce"):
        return "B:" + bollo_norm(r["bollo_ce"])
    if r.get("indirizzo"):
        com = _pulisci((r.get("comune") or "").split()[0]) if r.get("comune") else ""
        return "A:" + _pulisci(r["indirizzo"]) + "|" + com
    if r.get("produttore_nominato"):
        return "N:" + _pulisci(r["produttore_nominato"])
    return ""


# ---------------------------------------------------------------- lettura

def carica_elementi():
    perno = {}
    with open(ELEMENTI, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            perno.setdefault(r["nome_elemento"], []).append(r)
    return perno


def righe_prodotto(p):
    """Le righe (una per frase) di un prodotto di una fotografia: lista di dict con i campi di origine."""
    frasi = p.get("frasi") or []
    if not frasi:
        nota = p.get("nota", "")
        if p.get("solo_peck"):
            extra = "sull'etichetta c'e' solo l'indirizzo di Peck (titolare del marchio), nessuna frase di origine"
            nota = (nota + "; " if nota else "") + extra
        else:
            nota = (nota + "; " if nota else "") + "nessuna frase di origine"
        return [{"frase": "", "ruolo": "", "indirizzo": "", "cap": "", "comune": "", "provincia": "",
                 "paese": "", "produttore_nominato": "", "bollo_ce": "", "nota": nota,
                 "peck": bool(p.get("solo_peck"))}]
    out = []
    for f in frasi:
        spec = f if isinstance(f, dict) else {"frase": f}
        frase = spec["frase"].strip().rstrip(".;, ")
        if frase in CORREZIONI:
            camp = {k: v for k, v in CORREZIONI[frase].items()}
        else:
            camp = {}
        a = analizza(frase)
        a.update({k: v for k, v in camp.items() if k != "nota"})
        a.update(spec.get("campi", {}))
        note = [x for x in (p.get("nota") if len(frasi) == 1 else "", a.get("nota"), camp.get("nota"),
                            spec.get("nota")) if x]
        out.append({"frase": frase, "ruolo": a["ruolo"], "indirizzo": a["indirizzo"], "cap": a["cap"],
                    "comune": a["comune"], "provincia": a["provincia"], "paese": a["paese"],
                    "produttore_nominato": a["produttore_nominato"], "bollo_ce": a["bollo_ce"],
                    "nota": "; ".join(dict.fromkeys(note)), "peck": False})
    if len(frasi) > 1 and p.get("nota"):
        out[0]["nota"] = (p["nota"] + "; " + out[0]["nota"]).strip("; ")
    return out


def confronta(p, righe, elementi, per_nome_norm):
    """Ritorna (esito, nomi_2026, frasi_2026, nota)."""
    if "elem_2026" in p:
        nomi = list(p["elem_2026"])
        mancanti = [n for n in nomi if n not in elementi]
        if mancanti:
            raise SystemExit(f"nome non trovato in elementi.csv: {mancanti}")
    else:
        nomi = per_nome_norm.get(nome_norm(p["nome"]), [])
    nota_man = p.get("nota_confronto", "")
    if not nomi:
        return p.get("esito", "non in vendita online nel 2026"), [], [], nota_man
    rs26 = [r for n in nomi for r in elementi[n]]
    frasi26 = list(dict.fromkeys(r["frase_origine"] for r in rs26 if r["frase_origine"]))
    l25 = {("P" if r["peck"] else luogo(r)) for r in righe} - {""}
    l26 = {luogo(r) for r in rs26} - {""}
    if p.get("esito"):
        return p["esito"], nomi, frasi26, nota_man
    auto = ""
    if l25 == l26:
        esito = "uguale"
        if not l25:
            auto = "nessun luogo di produzione ne' nel 2025 ne' nel 2026"
    else:
        esito = "diverso"
        if not l26:
            auto = "nel 2026 la scheda non ha piu' la frase di origine"
        else:
            f25 = [r["frase"] for r in righe if r["frase"]] or ["solo l'indirizzo di Peck"]
            auto = "2025: " + " | ".join(f25) + "; 2026: " + " | ".join(frasi26)
    return esito, nomi, frasi26, "; ".join(x for x in (nota_man, auto) if x)


def main():
    elementi = carica_elementi()
    per_nome_norm = {}
    for n in elementi:
        per_nome_norm.setdefault(nome_norm(n), []).append(n)
    tutte = []
    for f in sorted(FONTI.glob("*.json")):
        snap = json.loads(f.read_text(encoding="utf-8"))
        conta = {c: 0 for c in CONFRONTI}
        for p in snap["prodotti"]:
            righe = righe_prodotto(p)
            esito, nomi, frasi26, nota_c = confronta(p, righe, elementi, per_nome_norm)
            assert esito in CONFRONTI, esito
            conta[esito] += 1
            for r in righe:
                tutte.append({"data_fonte": snap["data_fonte"], "fonte": snap["fonte"],
                              "nome_prodotto": p["nome"], "ruolo": r["ruolo"], "frase_origine": r["frase"],
                              "indirizzo": r["indirizzo"], "cap": r["cap"], "comune": r["comune"],
                              "provincia": r["provincia"], "paese": r["paese"],
                              "produttore_nominato": r["produttore_nominato"], "bollo_ce": r["bollo_ce"],
                              "sede_peck": "si" if "spadari" in r["indirizzo"].lower() else "",
                              "nota": r["nota"], "confronto_2026": esito,
                              "nome_elemento_2026": " | ".join(nomi), "frase_2026": " | ".join(frasi26),
                              "nota_confronto": nota_c})
        print(f"{snap['data_fonte']}: {len(snap['prodotti'])} prodotti, {conta}")
    tutte.sort(key=lambda r: r["data_fonte"])
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, CAMPI)
        w.writeheader()
        w.writerows(tutte)
    print(f"scritte {len(tutte)} righe in {USCITA}")


if __name__ == "__main__":
    main()
