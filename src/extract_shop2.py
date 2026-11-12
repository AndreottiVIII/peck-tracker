"""Legge una fotografia dello shop NUOVO di Peck (data/raw/shop2/<data>/) e AGGIORNA le tabelle in data/ senza cancellare niente.

Uso:  python -I src/extract_shop2.py [--data AAAA-MM-GG] [--cartella data/raw/shop2/AAAA-MM-GG]

Prima si lancia src/fetch_shop2.py (scarica l'API e le pagine). Questo programma:

  data/prodotti.csv        una riga per prodotto/box, colonne in piu' rispetto al vecchio shop: id_prodotto (indirizzo
                           stabile delle pagine del sito), fonte_shop (shop.peck.it / peck.it), prima_vista,
                           ultima_vista, in_vendita (si/no), url (quello di oggi) e url_vecchio, id_woo, categoria_slug,
                           foto_url, foto_vecchia_url, foto_locale (file dell'archivio personale, vedi src/foto_shop.py).
  data/elementi.csv        come prima, piu' prima_vista / ultima_vista / in_vendita. Una riga = una frase di origine di un
                           elemento di una pagina. Se la frase di un elemento cambia, la riga vecchia resta (in_vendita=no)
                           e se ne aggiunge una nuova: cosi' si vede che il fornitore e' cambiato.
  data/indirizzi.csv       gli stessi indirizzi di prima, ricalcolati su TUTTE le righe (comprese quelle non piu' in vendita)
  data/altre_origini.csv   idem per bolli CE e produttori nominati
  data/storico_shop.csv    una riga per prodotto per data di fotografia (prezzo, in_vendita...)

REGOLA DEL PROPRIETARIO: non si toglie MAI niente. Un prodotto del vecchio shop che non e' piu' nel nuovo resta, con
in_vendita = no e ultima_vista = l'ultima data in cui l'abbiamo visto (24 ottobre 2026 per i prodotti di shop.peck.it).
Se l'API non risponde o restituisce troppo pochi prodotti, non cambia niente (non si segna nessun prodotto come sparito).

Il vecchio shop e' passato su peck.it/shop il 12/11/2026: i prodotti si abbinano per nome (senza maiuscole, accenti,
spazi); se il nome non basta, per nome dell'unico elemento e prezzo. Si salvano solo frasi brevi sull'origine (come prima).
"""
import argparse
import csv
import html
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as E  # noqa: E402
import scheda_shop2 as S  # noqa: E402
from fetch_shop2 import RAW2, ultima_cartella  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_VECCHIO = DATA / "raw"
DATA_VECCHIO = "2026-10-24"          # il giorno in cui si e' scaricato lo shop vecchio (shop.peck.it)
SHOP_VECCHIO = "shop.peck.it"
SHOP_NUOVO = "peck.it"
MIN_PRODOTTI = 20                    # sotto questo numero l'API si considera guasta: non si cambia niente
BASE_NUOVO = "https://peck.it/"

CAMPI_PRODOTTI = ["url", "nome", "tipo", "prezzo", "numero_elementi", "categoria",
                  "id_prodotto", "fonte_shop", "prima_vista", "ultima_vista", "in_vendita", "url_vecchio",
                  "id_woo", "categoria_slug", "foto_url", "foto_vecchia_url", "foto_locale"]
CAMPI_ELEMENTI = ["url_pagina", "nome_pagina", "nome_elemento", "ruolo", "frase_origine", "indirizzo", "cap",
                  "comune", "provincia", "paese", "produttore_nominato", "bollo_ce", "sede_peck", "nota",
                  "prima_vista", "ultima_vista", "in_vendita"]
CAMPI_STORICO = ["data", "id_prodotto", "id_woo", "nome", "categoria_slug", "prezzo", "in_vendita", "url",
                 "fonte_shop", "n_elementi", "foto_url"]


# ---------------------------------------------------------------- csv

def leggi(nome):
    f = DATA / nome
    if not f.exists():
        return []
    with open(f, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def scrivi(nome, righe, campi):
    with open(DATA / nome, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campi, extrasaction="ignore")
        w.writeheader()
        for r in righe:
            w.writerow({k: r.get(k, "") for k in campi})


def leggi_indice(f):
    with open(f, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def slug(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


nz = S.nz


# ---------------------------------------------------------------- migrazione del vecchio shop

def og_image(slug_pagina):
    f = RAW_VECCHIO / f"prodotto_{slug_pagina}.html"
    if not f.exists():
        return ""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
    m = soup.find("meta", attrs={"property": "og:image"})
    url = (m.get("content") or "").strip() if m else ""
    return ("https://" + url[7:]) if url.startswith("http://") else url


def migra(prodotti, elementi):
    """Se le tabelle sono ancora quelle del vecchio shop, aggiunge le colonne nuove (nessuna riga cambia)."""
    if prodotti and "in_vendita" in prodotti[0]:
        return prodotti, elementi, False
    for p in prodotti:
        sl = p["url"].rstrip("/").rsplit("/", 1)[-1]
        locale = ROOT / "archivio" / "foto_box" / f"{sl}.jpg"
        p.update({"id_prodotto": sl, "fonte_shop": SHOP_VECCHIO, "prima_vista": DATA_VECCHIO,
                  "ultima_vista": DATA_VECCHIO, "in_vendita": "si", "url_vecchio": p["url"], "id_woo": "",
                  "categoria_slug": "", "foto_url": og_image(sl), "foto_vecchia_url": og_image(sl),
                  "foto_locale": f"archivio/foto_box/{sl}.jpg" if locale.exists() else ""})
    for e in elementi:
        e.update({"prima_vista": DATA_VECCHIO, "ultima_vista": DATA_VECCHIO, "in_vendita": "si"})
    return prodotti, elementi, True


# ---------------------------------------------------------------- lettura della fotografia

def carica_fotografia(cartella):
    """[{id, nome, slug, url, prezzo, cat_slug, cat_nome, foto_url, righe_desc, scheda, ha_pagina}] dall'API + pagine."""
    api = []
    for f in sorted(cartella.glob("api_p*.json"), key=lambda x: int(re.search(r"(\d+)", x.stem).group(1))):
        api += json.loads(f.read_text(encoding="utf-8"))
    out = []
    for p in api:
        cat = next(((c["slug"], html.unescape(c["name"])) for c in p.get("categories", [])
                    if c["slug"] != "product_for_sale"), ("", ""))
        pag = cartella / f"p{p['id']}.html"
        foto = next((i["src"] for i in p.get("images", []) if i.get("src")), "")
        centesimi = int(p["prices"]["price"]) if p.get("prices", {}).get("price") not in (None, "") else None
        minor = int(p["prices"].get("currency_minor_unit", 2))
        out.append({
            "id": str(p["id"]), "nome": re.sub(r"\s+", " ", S.pulisci_testo(p["name"])).strip(),
            "slug": p["slug"], "url": p["permalink"], "cat_slug": cat[0], "cat_nome": cat[1],
            "prezzo": f"{centesimi / 10 ** minor:.2f}" if centesimi is not None else "",
            "foto_url": ("https://" + foto[7:]) if foto.startswith("http://") else foto,
            "righe_desc": S.righe_descrizione(p.get("description", "")),
            "scheda": S.testo_scheda(pag.read_text(encoding="utf-8")) if pag.exists() else None,
            "ha_pagina": pag.exists(),
        })
    return out


def elementi_di(prod, vocab):
    """Gli elementi di un prodotto della fotografia: [(nome, [righe di origine analizzate], da)]."""
    el = S.elementi_pagina(prod["scheda"] or "", prod["righe_desc"], vocab, vini=(prod["cat_slug"] == "gift-box-wines"))
    out = []
    for e in el:
        rr = E.righe_origine({"nome": e["nome"], "righe": e["righe"]})
        out.append((e["nome"], rr, e["da"]))
    return out


def stessa_origine(a, b):
    """Due righe di elementi.csv dello stesso elemento dicono la stessa origine?"""
    luogo_a, luogo_b = bool(a["indirizzo"] or a["comune"]), bool(b["indirizzo"] or b["comune"])
    if luogo_a and luogo_b:
        return E.stesso_luogo(a, b)
    if a["bollo_ce"] and b["bollo_ce"]:
        return E.nucleo_bollo(a["bollo_ce"]) == E.nucleo_bollo(b["bollo_ce"])
    if luogo_a or luogo_b or a["bollo_ce"] or b["bollo_ce"]:
        return False
    if a["produttore_nominato"] or b["produttore_nominato"]:
        return nz(a["produttore_nominato"]) == nz(b["produttore_nominato"])
    return E.norm(a["frase_origine"]) == E.norm(b["frase_origine"])


# ---------------------------------------------------------------- abbinamento vecchio <-> nuovo

def abbina_prodotti(prodotti, fotografia, vocab):
    """{id_prodotto esistente: prodotto della fotografia}. Prima per id_woo, poi per nome, poi per elemento unico + prezzo."""
    per_id = {p["id"]: p for p in fotografia}
    usati, ris = set(), {}
    for r in prodotti:                                    # gia' abbinati in un giro precedente
        if r.get("id_woo") and r["id_woo"] in per_id:
            ris[r["id_prodotto"]] = per_id[r["id_woo"]]
            usati.add(r["id_woo"])
    per_nome = {}
    for p in fotografia:
        per_nome.setdefault(nz(p["nome"]), []).append(p)
    for r in prodotti:
        if r["id_prodotto"] in ris:
            continue
        cand = [p for p in per_nome.get(nz(r["nome"]), []) if p["id"] not in usati]
        if len(cand) == 1:
            ris[r["id_prodotto"]] = cand[0]
            usati.add(cand[0]["id"])
    for r in prodotti:                                    # es. «PANETTONE TRADIZIONALE 1 KG» -> «Panettone Tradizionale»
        if r["id_prodotto"] in ris or r["id_woo"]:
            continue
        for p in fotografia:
            if p["id"] in usati or not p["scheda"]:
                continue
            nomi = [e["nome"] for e in S.elementi_pagina(p["scheda"], [], vocab)]
            if len(nomi) == 1 and nz(nomi[0]) == nz(r["nome"]) and p["prezzo"] == r["prezzo"]:
                ris[r["id_prodotto"]] = p
                usati.add(p["id"])
                break
    return ris, usati


# ---------------------------------------------------------------- aggiornamento

def aggiorna(cartella, data_foto):
    prodotti = leggi("prodotti.csv")
    elementi = leggi("elementi.csv")
    prodotti, elementi, migrato = migra(prodotti, elementi)
    fotografia = carica_fotografia(cartella)
    if len(fotografia) < MIN_PRODOTTI:
        sys.exit(f"STOP: la fotografia ha solo {len(fotografia)} prodotti (meno di {MIN_PRODOTTI}): non si cambia niente.")
    print(f"fotografia {data_foto}: {len(fotografia)} prodotti dall'API; "
          f"{sum(1 for p in fotografia if p['ha_pagina'])} pagine", flush=True)

    # nomi di elemento gia' noti (per non duplicare lo stesso prodotto scritto in modi diversi)
    canonico = {}
    for e in elementi:
        canonico.setdefault(nz(e["nome_elemento"]), e["nome_elemento"])
    vocab = set(canonico.values())

    abb, usati = abbina_prodotti(prodotti, fotografia, vocab)
    per_id_prodotto = {r["id_prodotto"]: r for r in prodotti}
    ids = set(per_id_prodotto)
    n_abbinati, n_nuovi = len(abb), 0
    riga_di = {}                                           # id_woo -> riga di prodotti

    for idp, p in abb.items():
        riga_di[p["id"]] = per_id_prodotto[idp]
    for p in sorted(fotografia, key=lambda x: int(x["id"])):
        if p["id"] in usati:
            continue
        base = slug(p["nome"])
        idp, i = base, 1
        while idp in ids:
            i += 1
            idp = f"{base}-{i}"
        ids.add(idp)
        r = {"url": p["url"], "nome": p["nome"], "tipo": "", "prezzo": p["prezzo"], "numero_elementi": "",
             "categoria": p["cat_nome"], "id_prodotto": idp, "fonte_shop": SHOP_NUOVO, "prima_vista": data_foto,
             "ultima_vista": "", "in_vendita": "si", "url_vecchio": "", "id_woo": p["id"],
             "categoria_slug": p["cat_slug"], "foto_url": p["foto_url"], "foto_vecchia_url": "", "foto_locale": ""}
        prodotti.append(r)
        per_id_prodotto[idp] = r
        riga_di[p["id"]] = r
        n_nuovi += 1

    righe_per_prodotto = {}
    for e in elementi:
        righe_per_prodotto.setdefault(e["url_pagina"], []).append(e)

    visti_id_woo = set()
    n_righe_nuove = n_righe_tolte = 0
    cambi = []
    for p in fotografia:
        r = riga_di[p["id"]]
        visti_id_woo.add(p["id"])
        url_prima = r["url"]
        # pagina letta davvero? se no si aggiornano solo i dati dell'API e le righe di elementi restano come sono
        letto = p["ha_pagina"] and bool(p["scheda"])
        r.update({"url": p["url"], "nome": p["nome"], "prezzo": p["prezzo"] or r["prezzo"],
                  "categoria": p["cat_nome"] or r["categoria"], "categoria_slug": p["cat_slug"],
                  "id_woo": p["id"], "fonte_shop": SHOP_NUOVO, "ultima_vista": data_foto, "in_vendita": "si"})
        if p["foto_url"]:
            if r["foto_url"] and r["foto_url"] != p["foto_url"] and not r["foto_vecchia_url"] \
                    and r["fonte_shop"] == SHOP_VECCHIO:
                r["foto_vecchia_url"] = r["foto_url"]
            r["foto_url"] = p["foto_url"]
        # le righe di elementi di questa pagina passano all'url di oggi
        mie = righe_per_prodotto.pop(url_prima, []) + (righe_per_prodotto.pop(p["url"], []) if p["url"] != url_prima else [])
        for e in mie:
            e["url_pagina"], e["nome_pagina"] = p["url"], p["nome"]
        righe_per_prodotto[p["url"]] = mie
        if not letto:
            continue
        nuovi = elementi_di(p, vocab)
        nuove_righe = []
        for nome, rr, da in nuovi:
            nome = canonico.setdefault(nz(nome), nome)
            vocab.add(nome)
            base = {"url_pagina": p["url"], "nome_pagina": p["nome"], "nome_elemento": nome}
            if not rr:
                nota = ("nessuna frase di origine nel testo" if da == "scheda" else
                        "nessuna frase di origine nel testo (elemento letto dalla Descrizione: la scheda non ha il suo nome)")
                nuove_righe.append(({**base, "ruolo": "", "frase_origine": "", "indirizzo": "", "cap": "", "comune": "",
                                     "provincia": "", "paese": "", "produttore_nominato": "", "bollo_ce": "",
                                     "sede_peck": "", "nota": nota}, ""))
                continue
            for q in rr:
                nuove_righe.append(({**base, "ruolo": q["ruolo"], "frase_origine": q["frase"], "indirizzo": q["indirizzo"],
                                     "cap": q["cap"], "comune": q["comune"], "provincia": q["provincia"],
                                     "paese": q["paese"], "produttore_nominato": q["produttore_nominato"],
                                     "bollo_ce": q["bollo_ce"], "sede_peck": "si" if E.sede_peck(q) else "",
                                     "nota": q["nota"]}, q["frase"]))
        # una riga nuova e' la stessa di una esistente se l'elemento e' lo stesso e l'origine e' la stessa
        # (stesso luogo, stesso bollo, stesso produttore nominato, o la stessa frase): le differenze di
        # punteggiatura o di «Prodotto in» / «Prodotto e confezionato in» non contano
        da_aggiungere = []
        usate = set()
        for riga, frase in nuove_righe:
            trovata = None
            for j, e in enumerate(mie):
                if j in usate or nz(e["nome_elemento"]) != nz(riga["nome_elemento"]):
                    continue
                if stessa_origine(e, riga):
                    trovata = j
                    break
            if trovata is None:
                da_aggiungere.append(riga)
            else:
                usate.add(trovata)
                mie[trovata]["ultima_vista"], mie[trovata]["in_vendita"] = data_foto, "si"
        for j, e in enumerate(mie):
            if j not in usate:
                if e["in_vendita"] == "si":
                    n_righe_tolte += 1
                    if e["frase_origine"]:
                        cambi.append(f"tolta da «{p['nome']}»: {e['nome_elemento']} | {e['frase_origine']}")
                e["in_vendita"] = "no"
        for riga in da_aggiungere:
            riga.update({"prima_vista": data_foto, "ultima_vista": data_foto, "in_vendita": "si"})
            mie.append(riga)
            elementi.append(riga)
            n_righe_nuove += 1
            if r["prima_vista"] != data_foto and riga["frase_origine"]:
                cambi.append(f"nuova in «{p['nome']}»: {riga['nome_elemento']} | {riga['frase_origine']}")
        elem_correnti = {nz(e["nome_elemento"]) for e in mie if e["in_vendita"] == "si"}
        r["numero_elementi"] = str(len(elem_correnti))
        r["tipo"] = "box" if (p["cat_slug"] == "gift-box-wines" or len(elem_correnti) > 1) else "singolo"

    # prodotti non piu' nella fotografia: restano, segnati come non piu' in vendita
    sparsi = 0
    for r in prodotti:
        if r.get("id_woo") in visti_id_woo:
            continue
        if r["in_vendita"] == "si":
            sparsi += 1
            cambi.append(f"non piu' in vendita online: {r['nome']} (visto l'ultima volta il {r['ultima_vista']})")
        r["in_vendita"] = "no"
        for e in righe_per_prodotto.get(r["url"], []) + righe_per_prodotto.get(r["url_vecchio"], []):
            e["in_vendita"] = "no"
        if not r["tipo"]:
            r["tipo"] = "box"
    for r in prodotti:
        if not r["numero_elementi"]:
            r["numero_elementi"] = "0"

    # righe di elementi: ordine = quello di prodotti.csv (le righe nuove in coda a ogni prodotto)
    ordine_url = {}
    for r in prodotti:
        for u in (r["url"], r["url_vecchio"]):
            if u:
                ordine_url.setdefault(u, len(ordine_url))
    elementi.sort(key=lambda e: ordine_url.get(e["url_pagina"], 10 ** 6))   # sort stabile

    # --- storico: una riga per prodotto per data di fotografia
    storico = leggi("storico_shop.csv")
    if not storico:
        for r in prodotti:                                  # la fotografia del vecchio shop, 24/10/2026
            if r["fonte_shop"] == SHOP_VECCHIO or r["prima_vista"] == DATA_VECCHIO:
                storico.append({"data": DATA_VECCHIO, "id_prodotto": r["id_prodotto"], "id_woo": "", "nome": r["nome"],
                                "categoria_slug": "", "prezzo": r["prezzo"], "in_vendita": "si",
                                "url": r["url_vecchio"] or r["url"], "fonte_shop": SHOP_VECCHIO,
                                "n_elementi": r["numero_elementi"], "foto_url": r["foto_vecchia_url"] or ""})
    storico = [s for s in storico if s["data"] != data_foto]
    for p in fotografia:
        r = riga_di[p["id"]]
        storico.append({"data": data_foto, "id_prodotto": r["id_prodotto"], "id_woo": p["id"], "nome": p["nome"],
                        "categoria_slug": p["cat_slug"], "prezzo": p["prezzo"], "in_vendita": "si", "url": p["url"],
                        "fonte_shop": SHOP_NUOVO, "n_elementi": r["numero_elementi"], "foto_url": p["foto_url"]})
    storico.sort(key=lambda s: (s["data"], s["id_prodotto"]))

    # --- foto_locale: le foto gia' archiviate in locale da src/foto_shop.py (solo il percorso, mai l'immagine)
    archiviate = {}
    for ind in sorted((ROOT / "archivio" / "foto_shop").glob("*/indice.csv")):
        for q in leggi_indice(ind):
            if q["stato"] in ("scaricata", "gia archiviata") and q["file"]:
                archiviate[q["foto_url"]] = (q["tipo"] if q["stato"] == "gia archiviata" else
                                             f"archivio/foto_shop/{ind.parent.name}/{q['file']}")
    for r in prodotti:
        if r["foto_url"] in archiviate:
            r["foto_locale"] = archiviate[r["foto_url"]]

    # --- scrittura (prima di tutto, controllo: nessuna riga e' sparita)
    vecchi_prodotti = len(leggi("prodotti.csv"))
    vecchi_elementi = len(leggi("elementi.csv"))
    assert len(prodotti) >= vecchi_prodotti and len(elementi) >= vecchi_elementi, "righe sparite: non scrivo"
    scrivi("prodotti.csv", prodotti, CAMPI_PRODOTTI)
    scrivi("elementi.csv", elementi, CAMPI_ELEMENTI)
    scrivi("indirizzi.csv", E.costruisci_indirizzi(elementi), E.CAMPI_INDIRIZZI)
    scrivi("altre_origini.csv", E.costruisci_altre(elementi), E.CAMPI_ALTRE)
    scrivi("storico_shop.csv", storico, CAMPI_STORICO)

    print(f"prodotti: {len(prodotti)} righe (abbinati al vecchio shop {n_abbinati}, nuovi {n_nuovi}, "
          f"non piu' in vendita {sum(1 for r in prodotti if r['in_vendita'] == 'no')}; appena spariti {sparsi})")
    print(f"elementi.csv: {len(elementi)} righe (nuove {n_righe_nuove}, non piu' presenti {n_righe_tolte})"
          + ("  [migrato dal vecchio formato]" if migrato else ""))
    for c in cambi:
        print("  ", c)
    return prodotti, elementi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="")
    ap.add_argument("--cartella", default="")
    a = ap.parse_args()
    cartella = Path(a.cartella) if a.cartella else (RAW2 / a.data if a.data else ultima_cartella())
    if not cartella or not cartella.exists():
        sys.exit("nessuna fotografia in data/raw/shop2: lanciare prima src/fetch_shop2.py")
    aggiorna(cartella, a.data or cartella.name)


if __name__ == "__main__":
    main()
