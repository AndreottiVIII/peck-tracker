"""Confronto prezzi: carta dei vini di Peck contro le enoteche online (Callmewine, Millesima, Xtrawine,
Zachys, Berry Bros & Rudd), per litro.

    python -I src/confronto_vini_enoteche.py

NESSUNO scaricamento: legge solo le schede gia' presenti in data/raw/voti/<enoteca>/pagine/ (sola lettura) e
l'elenco degli abbinamenti dei voti (data/raw/voti/<enoteca>/candidati.csv, con gli stessi controlli di
voti_enoteche.py: nome, cantina, formato in litri, annata entro 2 anni). Si puo' rilanciare quando arrivano
altre schede (es. Berry Bros & Rudd). Scrive data/confronto/vini_enoteche_prezzi.csv.

Dove sta il prezzo:
  Callmewine, Xtrawine, Zachys, Berry Bros: JSON-LD `Offer` (prezzo, valuta, disponibilita'); Callmewine:
      disponibile se la pagina NON ha il bottone "Avvisami quando arriva" (il JSON-LD dice sempre PreOrder).
  Millesima: `__NEXT_DATA__`, elenco `items` (una voce per confezione: bottiglia singola, cassa da 6...,
      con `nbunit`, prezzo `offerPrice`, tipo di vendita primeur/pre-arrival).

Regole (confrontabile = si solo se tutte vere):
  - stesso vino e stesso formato in litri di Peck (controllato da voti_enoteche.verifica_pagina);
  - annata uguale o entro 2 anni (NV solo con NV);
  - bottiglia singola (se c'e' solo la cassa si divide per le bottiglie, ma e' `no`);
  - non en primeur / futures / pre-arrival (Millesima: venduti prima della consegna);
  - prezzo al consumatore con IVA in EUR, o in GBP convertito con cambio fisso:
        1 GBP = TASSO_GBP EUR
    Callmewine e Xtrawine (siti italiani) e Millesima.fr (consegna in Francia): prezzo al privato con IVA, come
    impone la legge; la pagina non lo scrive ma non c'e' un prezzo "senza IVA" accanto.
    Zachys (USD): prezzo americano senza imposta di vendita ne' dazi/IVA italiana -> convertito con
        1 USD = TASSO_USD EUR
    per curiosita' ma SEMPRE `no`. Berry Bros: `si` solo se la pagina dice "inc VAT" / "incl. VAT".
  - scarto per litro <= -60% o >= +200%: sospetto errore (cassa, prodotto diverso), `no` da controllare a mano;
  - Peck: prezzo della carta (con IVA), stessa regola dei confronti con Tannico.
"""
import csv
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voti_enoteche as VE  # noqa: E402
import voti_aperti as VA  # noqa: E402

RADICE = VE.RADICE
RAW = VE.RAW
USCITA = RADICE / "data" / "confronto" / "vini_enoteche_prezzi.csv"
TASSO_GBP = 1.15   # cambio fisso indicativo, ottobre 2026: 1 GBP = 1,15 EUR
TASSO_USD = 0.86   # cambio fisso indicativo, ottobre 2026: 1 USD = 0,86 EUR
TASSI = {"EUR": 1.0, "GBP": TASSO_GBP, "USD": TASSO_USD}
MAX_ANNI = 2
CAMPI = ["id", "nome", "cantina", "annata_peck", "litri_peck", "prezzo_peck", "retailer", "url", "annata_fonte",
         "litri_fonte", "prezzo_fonte", "valuta", "prezzo_fonte_eur_bottiglia", "prezzo_al_litro",
         "prezzo_peck_al_litro", "differenza_pct", "confrontabile", "disponibile", "data_pagina", "nota"]


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def unita_da_testo(txt):
    """Numero di bottiglie di una confezione dal testo (cassa da 6, 6 x 75cl, 6-pack...). 1 se non dice nulla."""
    t = txt or ""
    m = (re.search(r"(?i)\b(?:case|caisse|carton|cassa)\s+(?:of|de|da)\s+(\d+)", t)
         or re.search(r"(?i)\b(\d+)\s*[x×]\s*\d", t) or re.search(r"(?i)\b(\d+)[- ]?(?:pack|bottle case)\b", t))
    n = int(m.group(1)) if m else 1
    return n if n > 1 else 1


def offerte_json_ld(t):
    """Offerte (prezzo/valuta/disponibile) dal JSON-LD Product; piu' voci se la scheda ha piu' confezioni."""
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', t, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            cand = []
            if isinstance(x, dict):
                cand.append(x)
                if isinstance(x.get("@graph"), list):
                    cand += [y for y in x["@graph"] if isinstance(y, dict)]
            for p in cand:
                if p.get("@type") not in ("Product", "ProductGroup"):
                    continue
                o = p.get("offers")
                for of in (o if isinstance(o, list) else [o]):
                    if not isinstance(of, dict):
                        continue
                    pr = num(of.get("price") if of.get("price") is not None else of.get("lowPrice"))
                    if pr is None:
                        continue
                    av = str(of.get("availability", "")).split("/")[-1]
                    out.append({"prezzo": pr, "valuta": of.get("priceCurrency", ""),
                                "nome": str(p.get("name", "")),
                                "disponibile": {"InStock": "si", "OutOfStock": "no", "SoldOut": "no",
                                                "Discontinued": "no"}.get(av, "")})
    return out


def litri_da_millesima(desc):
    m = re.search(r"\(([0-9][0-9\-.,]*)\s*(cl|l)\)", desc or "", re.I)
    if m:
        v = float(m.group(1).replace("-", ".").replace(",", "."))
        return v / 100 if m.group(2).lower() == "cl" else v
    return 0.75 if re.search(r"(?i)bouteille", desc or "") and not re.search(r"(?i)demi", desc or "") else None


def offerte_millesima(t, oggi):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    if not m:
        return []
    try:
        c = json.loads(m.group(1))["props"]["pageProps"]["initialReduxState"]["product"]["content"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for it in c.get("items") or []:
        a = it.get("attributes") or {}

        def av(k):
            x = a.get(k)
            return x.get("value") if isinstance(x, dict) else None
        desc = it.get("shortdesc", "")
        pr = num(it.get("offerPrice") if it.get("offerPrice") is not None else it.get("listPrice"))
        if pr is None:
            continue
        stato = (a.get("in_stock") or {}).get("valueId", "")        # L livrable, P primeur, PA pre-arrival
        unita = int(num(av("nbunit")) or unita_da_testo(desc))
        giorni = None
        if it.get("availability"):
            try:
                giorni = (datetime.strptime(it["availability"], "%Y-%m-%d").date() - oggi).days
            except ValueError:
                pass
        out.append({"prezzo": pr, "valuta": it.get("stockOrigin") or "EUR", "nome": desc, "unita": unita,
                    "litri": litri_da_millesima(desc),
                    "futuro": bool(it.get("isPrevSale")) or stato in ("P", "PA") or (giorni is not None and giorni > 60),
                    "regalo": bool(re.search(r"(?i)coffret|etui|étui|\bvis\b", desc)),
                    "disponibile": "si" if stato == "L" and (it.get("stock") or 0) > 0 else "no"})
    return out


def scegli(offerte, litri_peck):
    """(offerta, nota): bottiglia singola del formato Peck; se non c'e', la confezione da piu' bottiglie."""
    def ok_litri(o):
        return o.get("litri") is None or abs(o["litri"] - litri_peck) < 1e-6
    sing = [o for o in offerte if o["unita"] == 1 and ok_litri(o)]
    if sing:
        sing.sort(key=lambda o: (o.get("regalo", False), o["disponibile"] != "si", o["prezzo"]))
        return sing[0], ""
    multi = [o for o in offerte if o["unita"] > 1 and ok_litri(o)]
    if multi:
        multi.sort(key=lambda o: (o["disponibile"] != "si", o["prezzo"] / o["unita"]))
        return multi[0], f"solo cassa da {multi[0]['unita']} bottiglie: prezzo diviso per bottiglia"
    return None, "nessuna confezione nel formato di Peck"


def distanza_annata(ap, af):
    ap, af = ap or "NV", af or "NV"
    if ap == "NV" or af == "NV":
        return 0 if ap == af else 99
    return abs(int(ap) - int(af))


def main():
    vini, _ = VA.leggi_vini()
    V = {v["id"]: v for v in vini}
    oggi = datetime.now().date()
    righe, stat = [], Counter()
    for nome in VE.ENOTECHE:
        cart = RAW / nome / "pagine"
        if not (RAW / nome / "candidati.csv").exists() or not cart.exists():
            continue
        etichetta = VE.NOMI_FONTE[nome]
        cache, visti = {}, set()
        for rg in VE.leggi_candidati(nome):
            f = cart / VE.nome_file(rg["url"])
            if not f.exists():
                stat[nome, "pagina non scaricata"] += 1
                continue
            if rg["url"] not in cache:
                t = f.read_text(encoding="utf-8", errors="replace")
                try:
                    sch = VE.ESTRATTORI[nome](t)
                except Exception as e:  # una scheda strana non ferma le altre
                    print("errore", nome, rg["url"], repr(e), file=sys.stderr)
                    sch = VE.Scheda()
                cache[rg["url"]] = (t, sch, datetime.fromtimestamp(f.stat().st_mtime).date().isoformat())
            t, sch, data_pagina = cache[rg["url"]]
            if (rg["id"], rg["url"]) in visti:
                continue
            visti.add((rg["id"], rg["url"]))
            v = V[rg["id"]]
            ok = VE.verifica_pagina(v, VE.T.tok_cantina(v["cantina"]), rg, sch)
            if not ok:
                stat[nome, "scartata dal controllo"] += 1
                continue
            corr, annata_f, litri_f = ok
            ap = v["annata"] or "NV"
            litri_p = num(v["litri"]) or 0.75
            prezzo_p = num(v["prezzo_euro"]) or 0.0
            if nome == "millesima":
                offerte = offerte_millesima(t, oggi)
            else:
                offerte = offerte_json_ld(t)
                for o in offerte:
                    o["unita"] = unita_da_testo(o["nome"])
                    o["litri"] = None
                    o["futuro"] = False
                    if nome == "callmewine":
                        o["disponibile"] = "no" if "Avvisami quando arriva" in t else "si"
            note, motivi = [], []
            o, n = scegli(offerte, litri_p)
            if not o:
                stat[nome, "senza prezzo"] += 1
                continue
            if n:
                (motivi if o["unita"] > 1 else note).append(n)
            valuta = o["valuta"] or "EUR"
            if valuta not in TASSI:
                motivi.append("valuta " + valuta + " sconosciuta")
            tasso = TASSI.get(valuta, 0)
            eur_btl = o["prezzo"] * tasso / o["unita"]
            if valuta != "EUR":
                note.append(f"convertito da {valuta} con cambio fisso 1 {valuta} = {tasso} EUR")
            if o.get("futuro"):
                motivi.append("en primeur / futures: consegna futura")
            if nome == "callmewine" and re.search(r"-(confezione|astuccio)-", rg["url"]):
                o["regalo"] = True      # su Callmewine "confezione" = versione con astuccio regalo
            if o.get("regalo"):
                motivi.append("con astuccio o cofanetto")
            if nome == "zachys":
                motivi.append("prezzo americano in USD senza IVA ne' imposte: non confrontabile")
            elif nome == "bbr":
                if not re.search(r"(?i)inc(?:l\.?|\.|luding)?\s*VAT", t):
                    motivi.append("la pagina non dice che il prezzo ha l'IVA")
                else:
                    note.append("prezzo UK con IVA 20%")
            elif nome == "millesima":
                note.append("prezzo B2C Millesima.fr (IVA inclusa per consegna in Francia, non scritta nella pagina)")
            else:
                note.append("prezzo al privato con IVA (sito italiano)")
            d = distanza_annata(ap, annata_f)
            if d > MAX_ANNI:
                motivi.append(f"annata lontana (Peck {ap}, fonte {annata_f})")
            elif d:
                note.append(f"annata diversa di {d} anno/i")
            if prezzo_p <= 0:
                motivi.append("prezzo Peck mancante")
            pl_peck = prezzo_p / litri_p if prezzo_p > 0 else None
            pl_fonte = eur_btl / litri_p if tasso else None
            diff = round((pl_peck / pl_fonte - 1) * 100, 1) if pl_peck and pl_fonte else None
            if diff is not None and (diff <= -60 or diff >= 200):
                motivi.append("scarto anomalo (prezzo fonte forse di una cassa o di un altro prodotto): da controllare a mano")
            if o["disponibile"] == "no":
                note.append("non disponibile (prezzo di listino)")
            righe.append({
                "id": rg["id"], "nome": v["nome"], "cantina": v["cantina"], "annata_peck": v["annata"],
                "litri_peck": f"{litri_p:g}", "prezzo_peck": f"{prezzo_p:g}" if prezzo_p else "",
                "retailer": etichetta, "url": rg["url"], "annata_fonte": annata_f, "litri_fonte": f"{litri_f:g}",
                "prezzo_fonte": f"{o['prezzo']:g}", "valuta": valuta,
                "prezzo_fonte_eur_bottiglia": f"{eur_btl:.2f}" if tasso else "",
                "prezzo_al_litro": f"{pl_fonte:.2f}" if pl_fonte else "",
                "prezzo_peck_al_litro": f"{pl_peck:.2f}" if pl_peck else "",
                "differenza_pct": diff if diff is not None else "",
                "confrontabile": "no" if motivi or diff is None else "si",
                "disponibile": o["disponibile"], "data_pagina": data_pagina,
                "nota": "; ".join(note + motivi)})
            stat[nome, "righe"] += 1
    righe.sort(key=lambda r: (int(r["id"]), r["retailer"], r["url"]))
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, CAMPI)
        w.writeheader()
        w.writerows(righe)
    for k, n in sorted(stat.items()):
        print(k[0], k[1], n)
    print(len(righe), "righe in", USCITA.name)
    for r_ in sorted({x["retailer"] for x in righe}):
        si = [float(x["differenza_pct"]) for x in righe if x["retailer"] == r_ and x["confrontabile"] == "si"]
        print(r_, "confrontabili:", len(si), "mediana %:", round(statistics.median(si), 1) if si else "-",
              "Peck piu' economico:", sum(1 for d in si if d < 0))
    tutte = [float(x["differenza_pct"]) for x in righe if x["confrontabile"] == "si"]
    if tutte:
        print("totale confrontabili", len(tutte), "mediana %:", round(statistics.median(tutte), 1))


if __name__ == "__main__":
    main()
