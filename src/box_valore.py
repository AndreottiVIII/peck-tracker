"""Il «valore spacchettato» di ogni pagina dello shop: quanto costerebbero i singoli prodotti presi uno a uno.

    python -I src/box_valore.py

Legge:  data/prodotti.csv, data/elementi.csv            (le 46 pagine dello shop e i loro prodotti)
        data/delivery_dispensa.csv                      (prezzi del delivery di Peck per 60 prodotti)
        data/confronto/risultati_*.csv                  (prezzi dei produttori: stesso prodotto / molto simile)
        data/vini.csv                                   (prezzi dell'enoteca di Peck)
Scrive: data/confronto/box_valore.csv                   (una riga per pagina)
        data/confronto/box_valore_righe.csv             (una riga per prodotto di ogni pagina, con prezzo e fonte)

Per ogni prodotto si prende il MIGLIOR prezzo disponibile, in quest'ordine:
  1. delivery di Peck (data/delivery_dispensa.csv); se il delivery lo vende a peso (prezzo al kg) si moltiplica
     per il peso scritto nel nome del prodotto Peck; se il formato e' diverso si riporta in proporzione.
  2. scheda singola dello shop Peck: i 10 prodotti venduti anche da soli (panettoni, pandoro, veneziana...)
     hanno un loro prezzo; per la pagina stessa del prodotto non si usa (sarebbe un giro in tondo).
  3. produttore (risultati_*.csv, solo «stesso prodotto» e «molto simile», con un prezzo del produttore),
     riportato in proporzione allo stesso formato se il formato del produttore e' diverso.
  4. enoteca di Peck (data/vini.csv) per i vini: stessa etichetta, stessa annata, bottiglia da 0,75 L.
Se non c'e' nessun prezzo il prodotto resta «non prezzato»: la copertura dice quanti prodotti su quanti.

Un prodotto vale per 1 pezzo del formato scritto nel suo nome (Peck non dice se una box ne contiene di piu').
Il prezzo dell'enoteca e quello della scheda singola sono prezzi di Peck: vanno nella somma «peck».
"""

import csv
import glob
import re
import unicodedata
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
DATI = RADICE / "data"
CONF = DATI / "confronto"

# --- vini dell'enoteca di Peck: (pezzo del nome Peck, id Winerim, nota)
VINI_ENOTECA = [
    ("cuveeprestigeedizionepeckcadelbosco", "151081", ""),
    ("palazzolanaextreme2014berlucchi", "370658", ""),
    ("teatroallascalabrut2022coffretbellavista", "351572", "bottiglia 0,75 L senza coffret"),
    ("pominochardonnayriservabenefizio2024", "250450", "in carta come «Castello Pomino Benefizio Riserva Pomino Bianco 2024»"),
    ("lucente2024frescobaldi", "372185", ""),
    ("140peckmetodoclassicopasdose2019", "151093", "in carta come «Peck Metodo Classico 140° Pinot Nero Pas Dosé 2019»"),
    ("domruinartbrut2013", "181915", "in carta come «Dom Ruinart Chalk Wrap 2013» (confezione diversa)"),
    ("guidalberto2024", "265581", ""),
    ("barolocinquevigne2022damilano", "264877", "in carta come «Damilano Barolo Le Cinquevigne 2022»"),
    ("lunelliriserva2016ferrari", "165773", "in carta come «Ferrari Trento DOC Riserva Lunelli 2016»"),
    ("giulioferraritrentobrutriserva2015", "155226", "in carta come «Ferrari Trento DOC Giulio Ferrari Riserva del Fondatore 2015»"),
]
# vini e distillati della box che in carta NON ci sono in questa forma (annata, edizione o cuvée diversa): non si usano
VINI_NON_IN_CARTA = [
    ("moscato2025peck", "il Canelli Moscato 2025 Peck non è in carta"),
    ("almaassemblage3", "in carta c'è l'Alma Assemblage 1 e 2, non la 3"),
    ("berlucchi61nature", "il Berlucchi '61 Nature non è in carta"),
    ("poggioallemura2021", "in carta c'è il Poggio all'Oro Riserva 2019, non il Brunello Poggio alle Mura 2021"),
    ("grandecuvee174", "in carta ci sono le edizioni 168-173 della Grande Cuvée (275 € la 173, 285 € la 172 in coffret), non la 174: non sommata"),
    ("vecchieviti2022", "in carta c'è il Nipozzano Riserva 2022 (19 €), non il Vecchie Viti: non sommato"),
    ("domperignonbrut2018", "in carta il Dom Pérignon Brut è 2017 (275 €, 285 € in coffret), non 2018: non sommato"),
    ("proseccovaldobbiadene2025", "in carta il Prosecco Peck è 2022/2023 (20 €, non disponibili), non 2025: non sommato"),
    ("ginpeck", "i distillati non sono nella carta vini dell'enoteca"),
    ("nonino", "i distillati non sono nella carta vini dell'enoteca"),
]


# riferimenti che esistono ma NON si sommano (altro taglio, altro formato, altra stagionatura): servono a spiegare
NON_USATI = [
    ("parmigianoreggianodopvaccabianca", "il delivery ha tre stagionature (30, 60 e 100 mesi: 70, 99 e 180 € al kg) e la scheda Peck non dice quale: non sommato"),
    ("olivebelladicerignola", "nel delivery le Bella di Cerignola sono sfuse (36 € al kg), non in vaso da 290 g: non sommato"),
    ("coppapecktrancio", "nel delivery c'è solo la coppa affettata (52 € al kg), non il trancio: non sommato"),
    ("carciofinimignon", "nel delivery i carciofini mignon sono da 120 g e il prezzo (139 €) non torna con il formato: non sommato"),
    ("salmoneaffumicatoallevato200", "nel delivery c'è il salmone Orcadi affettato (250 € al kg), non è lo stesso prodotto: non sommato"),
    ("zafferanodisardegnabio", "nel delivery c'è lo zafferano in stimmi da 1 g (35 €), altro formato e non bio: non sommato"),
    ("lorenzo5", "nel delivery c'è solo il Lorenzo 1 (25 €), che è un altro olio: non sommato"),
    ("tranciodibresaola", "nel delivery c'è la bresaola punta d'anca affettata (68 € al kg), altro taglio: non sommato"),
    ("cipollineinaceto", "nel delivery ci sono le cipolle all'aceto sfuse (28 € al kg), non le cipoline in vaso: non sommato"),
    ("tomettadicapra", "nel delivery c'è la tometta di capra a crosta lavata (55 € al kg), non a crosta naturale: non sommato"),
]


def motivo_vino(nome):
    n = nz(nome)
    for k, m in VINI_NON_IN_CARTA + NON_USATI:
        if k in n:
            return m
    return None


def nz(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def leggi(percorso):
    with open(percorso, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(x):
    m = re.search(r"-?\d+(?:[.,]\d+)?", x or "")
    return float(m.group().replace(",", ".")) if m else None


def formato(testo):
    """Il primo formato scritto in un testo -> (quantita, 'g' | 'ml') oppure None.
    '340 g' -> (340,'g'); 'G. 70' -> (70,'g'); '0.7 KG' -> (700,'g'); '25 cl' -> (250,'ml'); '0,75 L' -> (750,'ml')."""
    s = unicodedata.normalize("NFKD", testo or "").encode("ascii", "ignore").decode().lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|gr|g|ml|cl|lt|l)\b", s)
    if m:
        v, u = float(m.group(1)), m.group(2)
    else:
        m = re.search(r"\bkg\.?\s*(\d+(?:\.\d+)?)", s)
        if m:
            return float(m.group(1)) * 1000, "g"
        m = re.search(r"\b(?:g|gr)\.?\s*(\d+(?:\.\d+)?)\b", s)
        if not m:
            return None
        return float(m.group(1)), "g"
    if u in ("g", "gr"):
        return v, "g"
    if u == "kg":
        return v * 1000, "g"
    if u == "ml":
        return v, "ml"
    if u == "cl":
        return v * 10, "ml"
    return v * 1000, "ml"   # l, lt


def euro(x):
    return f"{x:.2f}"


def main():
    prodotti = leggi(DATI / "prodotti.csv")
    elementi = leggi(DATI / "elementi.csv")
    delivery = leggi(DATI / "delivery_dispensa.csv")
    vini = leggi(DATI / "vini.csv")

    # --- pagine e prodotti (distinti per pagina)
    per_pagina = {}
    nomi_el = []
    for r in elementi:
        n = r["nome_elemento"].strip()
        lst = per_pagina.setdefault(r["url_pagina"], [])
        if n not in lst:
            lst.append(n)
        if n not in nomi_el:
            nomi_el.append(n)

    # --- 1. delivery
    dd = {nz(r["nome_dispensa"]): r for r in delivery}

    def prezzo_delivery(nome):
        r = dd.get(nz(nome))
        if not r:
            return None
        p = float(r["prezzo"])
        fe = formato(nome)
        base = f"delivery cod. {r['cod_art']} «{r['nome_delivery']}»"
        if r["unita"] == "KG":
            if not fe or fe[1] != "g":
                return None
            kg = fe[0] / 1000
            return dict(prezzo=round(p * kg, 2), fonte="delivery", qualita="a peso",
                        dettaglio=f"{base}: {p:g} € al kg × {kg:g} kg (peso scritto da Peck nel nome del prodotto)")
        fd = formato(r["formato"])
        if r["corrispondenza"].startswith("esatta") or (fe and fd and fe == fd):
            return dict(prezzo=p, fonte="delivery", qualita="diretto", dettaglio=f"{base}: {p:g} € a confezione ({r['formato']})")
        if fe and fd and fe[1] == fd[1]:
            return dict(prezzo=round(p * fe[0] / fd[0], 2), fonte="delivery", qualita="proporzionale",
                        dettaglio=f"{base}: {p:g} € per {r['formato']}, riportato a {fe[0]:g} {fe[1]} in proporzione")
        return dict(prezzo=p, fonte="delivery", qualita="formato presunto",
                    dettaglio=f"{base}: {p:g} € per {r['formato']} (la scheda Peck non scrive il formato: si assume lo stesso)")

    # --- 2. prezzo della scheda singola dello shop
    singoli = {}
    for p in prodotti:
        if p["tipo"] == "singolo" and len(per_pagina.get(p["url"], [])) == 1:
            singoli[per_pagina[p["url"]][0]] = (float(p["prezzo"]), p["url"], p["nome"])

    # --- 4. enoteca
    per_id = {}
    for v in vini:
        if v["litri"] == "0.75" and v["variante"] != "calice":
            per_id.setdefault(v["id"], v)

    def prezzo_enoteca(nome):
        n = nz(nome)
        for pezzo, wid, nota in VINI_ENOTECA:
            if pezzo in n:
                v = per_id[wid]
                return dict(prezzo=float(v["prezzo_euro"]), fonte="enoteca Peck", qualita="diretto",
                            dettaglio=(f"enoteca Peck (Winerim) «{v['nome']}» {v['annata']}, bottiglia 0,75 L, "
                                       f"{float(v['prezzo_euro']):g} €" + (f"; {nota}" if nota else "")))
        return None

    # --- 3. produttori (risultati_*.csv)
    livello = {"stesso prodotto": 2, "molto simile": 1}
    cand = {}     # nome elemento -> lista (livello, prezzo adattato, qualita, dettaglio)
    stato_rit = {}  # nome elemento -> miglior esito (per spiegare perche' manca)
    per_nz = {nz(n): n for n in nomi_el}
    for f in sorted(glob.glob(str(CONF / "risultati_*.csv"))):
        sigla = Path(f).stem.replace("risultati_", "r")
        for r in leggi(f):
            nome = per_nz.get(nz(r["nome_peck"]))
            if not nome:
                continue
            sim = (r["somiglianza"] or "").strip().lower()
            stato_rit.setdefault(nome, set()).add(sim)
            pp = num(r["prezzo_produttore"])
            if sim not in livello or pp is None:
                continue
            fe = formato(nome) or formato(r["formato_peck"])
            fp = formato(r["formato_produttore"])
            etic = f"{r['azienda']} «{r['nome_produttore']}» ({sigla}, {sim})"
            if fp is None and r["formato_produttore"].strip() == "":
                prezzo, q, det = pp, "formato presunto", f"{etic}: {pp:g} €, formato del produttore non scritto (si assume lo stesso)"
            elif fe is None:
                prezzo, q, det = pp, "formato presunto", f"{etic}: {pp:g} € per {r['formato_produttore']} (Peck non scrive il formato: si assume lo stesso)"
            elif fp is None or fe[1] != fp[1]:
                continue
            else:
                rapporto = fe[0] / fp[0]
                if abs(rapporto - 1) <= 0.03:
                    prezzo, q, det = pp, "diretto", f"{etic}: {pp:g} € ({r['formato_produttore']})"
                else:
                    prezzo = round(pp * rapporto, 2)
                    q = "proporzionale"
                    det = f"{etic}: {pp:g} € per {fp[0]:g} {fp[1]}, riportato a {fe[0]:g} {fe[1]} in proporzione"
            cand.setdefault(nome, []).append((livello[sim], prezzo, q, det))

    def prezzo_produttore(nome):
        c = cand.get(nome)
        if not c:
            return None
        top = max(x[0] for x in c)
        migliori = [x for x in c if x[0] == top]
        prezzi = [x[1] for x in migliori]
        prezzo = round(sum(prezzi) / len(prezzi), 2)
        qs = {x[2] for x in migliori}
        q = "proporzionale" if "proporzionale" in qs else ("formato presunto" if "formato presunto" in qs else "diretto")
        det = " | ".join(x[3] for x in migliori)
        if len(migliori) > 1 and len(set(prezzi)) > 1:
            det = f"media di {len(migliori)} produttori collegati: " + det
        return dict(prezzo=prezzo, fonte="produttore", qualita=q, dettaglio=det)

    # --- prezzo di ogni prodotto, pagina per pagina
    righe = []
    box = []
    for p in prodotti:
        url = p["url"]
        nomi = per_pagina.get(url, [])
        tot = {"peck": 0.0, "prod": 0.0}
        n_pre = n_peck = n_prod = n_stim = 0
        mancano = []
        for n in nomi:
            sc = prezzo_delivery(n)
            if sc is None and n in singoli and singoli[n][1] != url:
                pr, u, nm = singoli[n]
                sc = dict(prezzo=pr, fonte="scheda singola Peck", qualita="diretto",
                          dettaglio=f"scheda «{nm}» dello shop Peck, venduto anche da solo: {pr:g} €")
            if sc is None:
                sc = prezzo_produttore(n)
            if sc is None:
                sc = prezzo_enoteca(n)
            r = {"url_box": url, "nome_box": p["nome"], "prodotto": n, "prezzo": "", "fonte": "", "qualita": "",
                 "dettaglio": "", "motivo_senza_prezzo": ""}
            if sc is None:
                es = stato_rit.get(n, set())
                if "non verificato" in es:
                    mot = "il sito del produttore vieta l'accesso agli agenti AI: da cercare a mano"
                elif "non trovato" in es:
                    mot = "il produttore non pubblica prezzi o non vende questo prodotto"
                elif "simile" in es:
                    mot = "dal produttore c'è solo un prodotto «simile»: non usato"
                elif "peck" in nz(n) and not motivo_vino(n):
                    mot = "prodotto a marchio Peck venduto solo nelle box: nessun prezzo pubblico"
                elif not motivo_vino(n):
                    mot = "nessun abbinamento con un prezzo (delivery, produttore o enoteca)"
                else:
                    mot = ""
                if motivo_vino(n):
                    mot = (mot + "; " if mot else "") + motivo_vino(n)
                r["motivo_senza_prezzo"] = mot
                mancano.append(n)
            else:
                r.update(prezzo=euro(sc["prezzo"]), fonte=sc["fonte"], qualita=sc["qualita"], dettaglio=sc["dettaglio"])
                n_pre += 1
                if sc["fonte"] == "produttore":
                    tot["prod"] += sc["prezzo"]
                    n_prod += 1
                else:
                    tot["peck"] += sc["prezzo"]
                    n_peck += 1
                if sc["qualita"] != "diretto":
                    n_stim += 1
            righe.append(r)

        prezzo_box = float(p["prezzo"])
        n_el = len(nomi)
        cop = 100.0 * n_pre / n_el if n_el else 0.0
        somma = tot["peck"] + tot["prod"]
        diff = prezzo_box - somma
        if cop >= 80:
            giud = "buona"
        elif cop >= 50:
            giud = "media"
        else:
            giud = "bassa"
        note = []
        if p["tipo"] == "singolo":
            note.append("Pagina di un prodotto singolo, non di una box: il suo prezzo è quello del prodotto stesso.")
        if n_pre == 0:
            note.append("Nessun prodotto ha un prezzo: niente da sommare.")
        elif cop >= 100:
            note.append("Tutti i prodotti hanno un prezzo: la differenza è il valore di confezione e servizio, "
                        "più gli errori delle stime.")
        elif cop >= 80:
            note.append(f"Copertura buona: sommati {n_pre} prodotti su {n_el}. La differenza comprende anche il valore "
                        f"dei prodotti senza prezzo, quindi è un massimo per confezione e servizio.")
        elif cop >= 50:
            note.append(f"Copertura parziale: sommati {n_pre} prodotti su {n_el}. La somma è solo una parte del contenuto "
                        f"e la differenza con il prezzo della box NON è un ricarico: comprende i prodotti senza prezzo.")
        else:
            note.append(f"Copertura bassa: sommati solo {n_pre} prodotti su {n_el}. La somma non è confrontabile con il "
                        f"prezzo della box.")
        if n_stim:
            note.append(f"{n_stim} dei prezzi sommati {'è una stima' if n_stim == 1 else 'sono stime'} "
                        f"(a peso, in proporzione o con formato presunto).")
        if mancano:
            elenco = "; ".join(m[:48] for m in mancano[:6]) + (f"; e altri {len(mancano) - 6}" if len(mancano) > 6 else "")
            note.append("Senza prezzo: " + elenco + ".")
        note.append("Nella somma non ci sono confezione, nastri e servizio della box.")
        box.append({
            "url": url, "nome": p["nome"], "tipo": p["tipo"], "prezzo_box": euro(prezzo_box),
            "n_elementi": n_el, "n_prezzati": n_pre,
            "somma_prezzi_peck": euro(tot["peck"]), "somma_prezzi_produttore": euro(tot["prod"]),
            "copertura_pct": f"{cop:.0f}", "differenza": euro(diff),
            "nota": " ".join(note),
            "copertura_giudizio": giud, "somma_totale": euro(somma),
            "differenza_pct": (f"{diff / somma * 100:+.1f}" if somma and cop >= 50 else ""),
            "n_prezzi_peck": n_peck, "n_prezzi_produttore": n_prod, "n_stime": n_stim,
        })

    col_box = ["url", "nome", "prezzo_box", "n_elementi", "n_prezzati", "somma_prezzi_peck", "somma_prezzi_produttore",
               "copertura_pct", "differenza", "nota", "tipo", "copertura_giudizio", "somma_totale", "differenza_pct",
               "n_prezzi_peck", "n_prezzi_produttore", "n_stime"]
    with open(CONF / "box_valore.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=col_box)
        w.writeheader()
        w.writerows(box)
    col_righe = ["url_box", "nome_box", "prodotto", "prezzo", "fonte", "qualita", "dettaglio", "motivo_senza_prezzo"]
    with open(CONF / "box_valore_righe.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=col_righe)
        w.writeheader()
        w.writerows(righe)

    # --- riepilogo a video
    print(f"{len(box)} pagine, {len(righe)} righe prodotto, {sum(1 for r in righe if r['prezzo'])} con prezzo")
    for b in sorted(box, key=lambda b: -int(b["copertura_pct"])):
        print(f"{b['copertura_pct']:>4}% {b['n_prezzati']:>2}/{b['n_elementi']:<2} box {b['prezzo_box']:>8} "
              f"somma {b['somma_totale']:>8} (peck {b['somma_prezzi_peck']}, prod {b['somma_prezzi_produttore']}) "
              f"diff {b['differenza']:>8} {b['differenza_pct']:>7}%  {b['nome'][:36]}")


if __name__ == "__main__":
    main()
