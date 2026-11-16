"""Confronto prezzi: carta dei vini di Peck contro Tannico, per litro.

    python -I src/confronto_vini.py

Legge data/vini.csv (una riga per formato), data/tannico.csv (abbinamenti) e il catalogo Tannico gia'
scaricato (data/raw/tannico/). Per ogni vino abbinato cerca fra i prodotti Tannico dello stesso vino quello
che ha lo stesso formato (e l'annata piu' vicina); scrive data/confronto/vini_tannico.csv.
Entrambi i prezzi sono prezzi al consumatore con IVA. Se a un prodotto Tannico manca il prezzo si guarda
la scheda gia' scaricata (data/raw/tannico/prodotti/); se non c'e', la si scarica (pausa 3 s).
Confrontabile = si solo se: stesso vino (nome uguale e cantina identica), stesso formato in litri, annata
uguale o entro 2 anni (senza annata: solo se manca da entrambe), prezzi presenti.
"""
import csv
import json
import re
import statistics
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tannico as T  # noqa: E402

RADICE = T.RADICE
USCITA = RADICE / "data" / "confronto" / "vini_tannico.csv"
DATA = date.today().isoformat()   # giorno in cui si fa il confronto (aggiornamento settimanale)
CAMPI = ["id", "nome", "cantina", "annata_peck", "litri_peck", "prezzo_peck", "url_tannico", "annata_tannico",
         "litri_tannico", "prezzo_tannico", "prezzo_peck_al_litro", "prezzo_tannico_al_litro", "differenza_pct",
         "confrontabile", "disponibile_tannico", "data", "nota"]


def prezzo_da_scheda(pr, pausa=3.0):
    """Prezzo dalla scheda prodotto (JSON-LD / meta), scaricandola se serve."""
    f = T.PRODOTTI / (pr.p["handle"] + ".html")
    if not f.exists():
        T.PRODOTTI.mkdir(parents=True, exist_ok=True)
        f.write_bytes(T.prendi(pr.url, pausa))
    t = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'"price"\s*:\s*"?([0-9]+(?:[.,][0-9]+)?)', t):
        return float(m.group(1).replace(",", "."))
    m = re.search(r'product:price:amount"\s+content="([0-9.,]+)"', t)
    return float(m.group(1).replace(",", ".")) if m else None


def main():
    prodotti = [T.Prodotto(p) for p in T.carica_catalogo()]
    prodotti = [pr for pr in prodotti
                if pr.p["product_type"] not in ("Spirits", "Accessori", "Soft Drink", "No-Low Alcol") and not pr.box]
    per_url = {pr.url: pr for pr in prodotti}
    idx = T.costruisci_indice(prodotti)
    generici = T.frequenze_generiche(prodotti)
    with open(T.VINI, encoding="utf-8-sig", newline="") as f:
        vini = list(csv.DictReader(f))
    with open(T.USCITA, encoding="utf-8-sig", newline="") as f:
        abb = {r["id"]: r for r in csv.DictReader(f)}

    uscita, cache = [], {}
    for r in vini:
        a = abb.get(r["id"])
        if not a or a["corrispondenza"] == "nessuna" or a["url_tannico"] not in per_url:
            continue
        base_pr = per_url[a["url_tannico"]]
        if r["id"] not in cache:  # prodotti Tannico dello stesso vino (uguale, cantina identica)
            tc_alt = T.tok_cantina(r["cantina"])
            cand = {}
            for alt in tc_alt:
                for w in alt:
                    for pr in idx.get(w, []):
                        cand[pr.p["id"]] = pr
            stessi = []
            for pr in cand.values():
                c = T.confronta(r, tc_alt, pr, generici)
                if c and c[0] == "uguale" and c[2]:
                    stessi.append(pr)
            cache[r["id"]] = stessi
        stessi = cache[r["id"]]
        identico = base_pr in stessi
        litri = float(r["litri"]) if r["litri"] else None
        prezzo = float(r["prezzo_euro"]) if r["prezzo_euro"] else 0.0
        pr = base_pr
        if identico and litri:
            ml = int(round(litri * 1000))
            ok = [p for p in stessi if p.formato == ml]
            if ok:
                def dist(p):
                    return abs(int(p.anno) - int(r["annata"])) if p.anno and r["annata"] else (0 if p.anno == r["annata"] else 99)
                ok.sort(key=lambda p: (dist(p), p.p["available"] is not True))
                pr = ok[0]
        note = [a["nota"]] if a["nota"] and pr is base_pr else []
        p_t = float(pr.p["price"]) if pr.p.get("price") not in (None, "") else None
        if not p_t:
            p_t = prezzo_da_scheda(pr)
            note.append("prezzo Tannico preso dalla scheda prodotto")
        l_t = pr.formato / 1000
        motivi = []
        if not identico:
            motivi.append("non e' certo che sia lo stesso vino (abbinamento " + a["corrispondenza"] + ")")
        if r["variante"] == "calice":
            motivi.append("calice")
        elif not litri:
            motivi.append("formato Peck non indicato")
        elif abs(litri - l_t) > 1e-9:
            motivi.append(f"formato diverso (Peck {litri:g} L, Tannico {l_t:g} L)")
        if prezzo <= 0:
            motivi.append("prezzo Peck mancante")
        if not p_t:
            motivi.append("prezzo Tannico mancante")
        ap, at = r["annata"], pr.anno
        if bool(ap) != bool(at):
            motivi.append("annata presente solo da una parte")
        elif ap and abs(int(ap) - int(at)) > 2:
            motivi.append(f"annata lontana (Peck {ap}, Tannico {at})")
        pl = prezzo / litri if litri and prezzo > 0 else None
        tl = p_t / l_t if p_t else None
        diff = round((pl / tl - 1) * 100, 1) if pl and tl else None
        if ap and at and ap != at and not motivi:
            note.append(f"annata diversa di {abs(int(ap) - int(at))} anno/i")
        if motivi:
            note.append("; ".join(motivi))
        uscita.append({
            "id": r["id"], "nome": r["nome"], "cantina": r["cantina"], "annata_peck": ap,
            "litri_peck": r["litri"], "prezzo_peck": f"{prezzo:g}" if prezzo else "", "url_tannico": pr.url,
            "annata_tannico": at, "litri_tannico": f"{l_t:g}", "prezzo_tannico": f"{p_t:g}" if p_t else "",
            "prezzo_peck_al_litro": f"{pl:.2f}" if pl else "", "prezzo_tannico_al_litro": f"{tl:.2f}" if tl else "",
            "differenza_pct": diff if diff is not None else "",
            "confrontabile": "no" if motivi else "si",
            "disponibile_tannico": {True: "si", False: "no"}.get(pr.p.get("available"), ""),
            "data": DATA, "nota": "; ".join(n for n in note if n)})
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, CAMPI)
        w.writeheader()
        w.writerows(uscita)
    si = [u for u in uscita if u["confrontabile"] == "si"]
    print(len(uscita), "righe,", len(si), "confrontabili")
    if si:
        d = [float(u["differenza_pct"]) for u in si]
        print("differenza mediana %:", round(statistics.median(d), 1))


if __name__ == "__main__":
    main()
