"""Costruisce i dati del sito (docs/dati.json e docs/vini.json) dai file CSV in data/.

Si lancia dalla cartella peck-tracker, con Python 3.12:

    python -I src/sito.py

Si puo' rilanciare quando si vuole (per esempio dopo aver aggiornato data/aziende.csv):
riscrive i due file json da zero. Non scarica nulla. Nei json finiscono solo
indirizzi web (URL) delle foto, mai le foto: le foto restano sui server di Peck e di Winerim.

Legge:  data/prodotti.csv, elementi.csv, indirizzi.csv, altre_origini.csv, aziende.csv,
        vini.csv, cantine.csv, vini_nelle_box.csv, data/raw/prodotto_*.html (per le foto),
        data/raw/winerim/vini_p*.json (per le foto delle bottiglie).
Scrive: docs/dati.json (dispensa, box, produttori) e docs/vini.json (enoteca).
"""

import csv
import difflib
import glob
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

RADICE = Path(__file__).resolve().parent.parent
DATI = RADICE / "data"
RAW = DATI / "raw"
DOCS = RADICE / "docs"

REPO = "https://github.com/AndreottiVIII/peck-tracker"
FOTO_PECK_HOST = "https://shop.peck.it/"
FOTO_WINERIM_PREFISSO = "https://app.winerim.com/images/wines/"
LINK_WINERIM_PREFISSO = "https://web.winerim.com/enotecapeck/wines/"
DATA_FOTOGRAFIA = "2026-10-24"

# ---------------------------------------------------------------------------
# Categorie del cibo: parole chiave cercate nel nome del prodotto (in minuscolo).
# La prima categoria che ha una parola chiave nel nome vince, quindi l'ordine conta.
# Una parola che inizia con ^ vale solo se il nome INIZIA con quella parola.
# Se nessuna categoria va bene, il prodotto e' "altro".
# Questa lista viene copiata anche in docs/dati.json e mostrata nella pagina "Come funziona".
# ---------------------------------------------------------------------------
CATEGORIE = [
    ("olio e aceto", ["^olio", "^aceto", "condimento"]),
    ("dolci e lievitati", [
        "panettone", "pandoro", "veneziana", "torron", "baci di dama", "krumiri", "biscott",
        "amaretti", "panforte", "zabaione", "gelatine", "caramelle", "marrons gla",
        "^crema al pistacchio", "^crema alla mandorla", "^crema alla nocciola",
    ]),
    ("frutta secca", ["^noci", "^nocciole", "^mandorle", "^anacardi", "^pistacchi",
                      "frutta disidratata"]),
    ("cioccolato", ["cioccolat", "praline", "gianduiotti", "tartufini", "marroncini", "rondelle"]),
    ("distillati", ["^gin ", "grappa", "^amaro", "nonino"]),
    ("pesce", ["salmone", "tonno", "acciughe", "granchio", "bottarga"]),
    ("salumi", ["prosciutto", "jamón", "paleta", "salame", "coppa", "bresaola", "mortadella",
                "cotechino", "zampone"]),
    ("formaggi", ["^parmigiano", "^pecorino", "castelmagno", "montasio", "bagoss", "tometta",
                  "monnalisa"]),
    ("pasta e riso", ["spaghetti", "penne", "linguine", "bucatini", "fusilloni", "paccheri",
                      "rigatoni", "tagliatelle", "tagliolini", "^riso"]),
    ("tè e caffè", ["^caff", "^tè", "^te nero"]),
    ("vini e spumanti", ["franciacorta", "champagne", "prosecco", "brunello", "barolo",
                         "chianti rufina", "castello pomino", "lucente", "guidalberto",
                         "metodo classico", "spumante", "docg", "lunelli", "giulio ferrari",
                         "cinquevigne"]),
    ("conserve e sottoli", [
        "confettur", "marmellat", "mostarda", "miele", "olive", "carciof", "capper", "cucunci",
        "cipollin", "giardiniera", "caponata", "passata", "pomodor", "pesto", "salsa", "salse",
        "ragù", "broccoli", "funghi", "radicchio", "peperoncini", "acquasale", "marroni",
        "amarena", "fico tartufato", "filetti di arancia", "^crema", "genovese",
    ]),
]
CATEGORIA_ALTRO = "altro"
ORDINE_CATEGORIE = [c for c, _ in CATEGORIE] + [CATEGORIA_ALTRO]

# Stati di "quanto siamo sicuri" (dal piu' sicuro al meno sicuro).
CERTA, PROBABILE, PECK, NON_TROVATA, NESSUNA = "certa", "probabile", "peck", "non trovata", "nessuna"
ORDINE_STATI = [CERTA, PROBABILE, PECK, NON_TROVATA, NESSUNA]

# Province -> regioni.
_REGIONI = {
    "Piemonte": "AL AT BI CN NO TO VB VC",
    "Valle d'Aosta": "AO",
    "Lombardia": "BG BS CO CR LC LO MB MI MN PV SO VA",
    "Trentino-Alto Adige": "BZ TN",
    "Veneto": "BL PD RO TV VE VR VI",
    "Friuli-Venezia Giulia": "GO PN TS UD",
    "Liguria": "GE IM SP SV",
    "Emilia-Romagna": "BO FE FC MO PR PC RA RE RN",
    "Toscana": "AR FI GR LI LU MS PI PT PO SI",
    "Umbria": "PG TR",
    "Marche": "AN AP FM MC PU",
    "Lazio": "FR LT RI RM VT",
    "Abruzzo": "AQ CH PE TE",
    "Molise": "CB IS",
    "Campania": "AV BN CE NA SA",
    "Puglia": "BA BT BR FG LE TA",
    "Basilicata": "MT PZ",
    "Calabria": "CZ CS KR RC VV",
    "Sicilia": "AG CL CT EN ME PA RG SR TP",
    "Sardegna": "CA NU OR SS SU",
}
PROV_REGIONE = {s: r for r, sigle in _REGIONI.items() for s in sigle.split()}
# Province scritte per esteso nei dati di Peck, e comuni senza provincia nei dati.
PROV_NOMI = {"firenze": "FI"}
COMUNE_PROV = {"torino": "TO", "milano": "MI", "sondrio": "SO", "catania": "CT", "sassari": "SS"}
# Chi non ha provincia italiana: il "luogo" e' il paese.
COMUNE_PAESE = {"hamburg": "Germania", "altheim": "Germania"}  # chiavi gia' passate da nz()

# Sigle con "abbinamento a mano" (chiave scritta da Peck -> chiave in aziende.csv).
# Servono solo se l'abbinamento automatico sbaglia; per ora e' vuoto.
ALIAS_INDIRIZZI = {}


# ---------------------------------------------------------------------------
# Piccoli attrezzi
# ---------------------------------------------------------------------------

def leggi_csv(nome):
    with open(DATI / f"{nome}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def senza_accenti(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def nz(s):
    """Forma 'confrontabile': minuscolo, senza accenti, solo lettere e numeri."""
    return re.sub(r"[^a-z0-9]", "", senza_accenti(s or "").lower())


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", senza_accenti(s or "").lower()).strip("-")
    return s or "x"


PAROLINE = {"di", "da", "e", "al", "alla", "allo", "ai", "agli", "alle", "il", "la", "le",
            "lo", "del", "della", "dei", "delle", "degli", "in", "con", "per", "su", "a", "dal",
            "sul", "nel", "d", "all", "dell", "senza"}
SIGLE = {"dop", "igp", "docg", "doc", "evo", "igt", "ggg", "ue", "ce", "it"}
UNITA = {"kg", "gr", "g", "ml", "cl", "l"}


def maiuscola_iniziale(w):
    for i, c in enumerate(w):
        if c.isalpha():
            return w[:i] + c.upper() + w[i + 1:]
    return w


def bello(nome):
    """Nome 'in bella': se e' tutto maiuscolo lo mette con le iniziali maiuscole."""
    s = re.sub(r"\s*\(WEB E CONFEZIONI\)", "", nome or "", flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    lettere = [c for c in s if c.isalpha()]
    if not lettere or sum(c.isupper() for c in lettere) / len(lettere) < 0.6:
        return s[:1].upper() + s[1:]
    out = []
    for i, parola in enumerate(s.split(" ")):
        low = parola.lower()
        nudo = re.sub(r"[^\w]", "", low)
        if nudo in SIGLE:
            out.append(parola.upper())
        elif nudo in UNITA or re.fullmatch(r"\d+(?:[.,]\d+)?(?:kg|gr|g|ml|cl|l)", nudo):
            out.append(low)
        elif nudo == "peck":
            out.append("Peck")
        elif "'" in low or "’" in low:
            pezzi = re.split(r"(['’])", low)
            res = []
            for j, p in enumerate(pezzi):
                if p in ("'", "’") or not p:
                    res.append(p)
                elif j == 0 and len(p) <= 4 and i > 0:
                    res.append(p)  # d'altri -> d'
                else:
                    res.append(p[:1].upper() + p[1:])
            out.append("".join(res))
        elif i > 0 and nudo in PAROLINE and low == nudo:
            out.append(low)
        else:
            out.append(maiuscola_iniziale(low))
    return " ".join(out)


def euro_testo(v):
    """'252.00' -> '252,00 €' come lo mostra Peck."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def regione_di(provincia, paese):
    if paese and paese != "Italia":
        return paese
    return PROV_REGIONE.get((provincia or "").upper(), "")


# ---------------------------------------------------------------------------
# Foto dei prodotti Peck (solo l'indirizzo web, scritto nella pagina salvata)
# ---------------------------------------------------------------------------

def foto_pagina(slug_pagina):
    f = RAW / f"prodotto_{slug_pagina}.html"
    if not f.exists():
        return ""
    soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
    url = ""
    m = soup.find("meta", attrs={"property": "og:image"})
    if m and m.get("content"):
        url = m["content"].strip()
    if not url:
        img = soup.select_one("img.img-thumbnail")
        if img and img.get("src"):
            url = img["src"].strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if url.startswith("/"):
        url = FOTO_PECK_HOST.rstrip("/") + url
    if not url.startswith(FOTO_PECK_HOST):
        return ""  # per sicurezza: solo foto servite dal negozio di Peck
    return url


# ---------------------------------------------------------------------------
# Categorie
# ---------------------------------------------------------------------------

def categoria_di(nome):
    n = nome.lower()
    for cat, parole in CATEGORIE:
        for p in parole:
            if p.startswith("^"):
                if n.startswith(p[1:]):
                    return cat
            elif p in n:
                return cat
    return CATEGORIA_ALTRO


# ---------------------------------------------------------------------------
# Aziende: chiavi e abbinamento
# ---------------------------------------------------------------------------

def chiave_indirizzo(r):
    """Scrive l'indirizzo come in aziende.csv: 'via X 9, Comune (PR)'."""
    pezzi = [x for x in (r["indirizzo"], r["comune"]) if x]
    k = ", ".join(pezzi)
    if r["provincia"]:
        k += f" ({r['provincia']})"
    return k


def senza_provincia(k):
    return re.sub(r"\s*\([^)]*\)\s*$", "", k)


FORME = re.compile(
    r"\b(s\.?\s?r\.?\s?l\.?|s\.?\s?p\.?\s?a\.?|s\.?\s?a\.?\s?s\.?|s\.?\s?n\.?\s?c\.?|s\.?\s?a\.?|"
    r"srl|spa|unipersonale|a socio unico|societa'? agricola|societa'? cooperativa|di .* e c\.?)\b")


def nome_azienda_chiave(ragione, marchio):
    """Forma confrontabile del nome di un'azienda, per unire righe diverse della stessa azienda."""
    s = senza_accenti(ragione or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = FORME.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class Aziende:
    """Le righe di aziende.csv, con l'abbinamento per indirizzo, bollo CE e produttore nominato."""

    def __init__(self, righe):
        self.righe = righe
        self.per_indirizzo = {}
        self.per_indirizzo_np = {}
        self.per_bollo = {}
        self.per_produttore = {}
        self.per_via = defaultdict(list)
        for a in righe:
            k = a["chiave"]
            if a["tipo_chiave"] == "indirizzo":
                self.per_indirizzo[nz(k)] = a
                self.per_indirizzo_np.setdefault(nz(senza_provincia(k)), a)
                self.per_via[nz(k.split(",")[0])].append(a)
            elif a["tipo_chiave"] == "bollo_ce":
                self.per_bollo[nz(k)] = a
            elif a["tipo_chiave"] == "produttore":
                self.per_produttore[nz(k)] = a
        self.approssimati = []  # abbinamenti non esatti, da stampare e controllare

    def cerca_indirizzo(self, r):
        k = chiave_indirizzo(r)
        if k in ALIAS_INDIRIZZI:
            k = ALIAS_INDIRIZZI[k]
        n = nz(k)
        if n in self.per_indirizzo:
            return self.per_indirizzo[n], "esatto"
        nsp = nz(senza_provincia(k))
        if nsp in self.per_indirizzo_np:
            return self.per_indirizzo_np[nsp], "senza provincia"
        # stessa via e stesso numero civico, comune scritto in un altro modo (Sorbara / Sorbara di Bomporto)
        if r["indirizzo"]:
            vie = self.per_via.get(nz(r["indirizzo"]), [])
            primo = nz((r["comune"] or "").split(" ")[0])
            if len(vie) == 1 and primo and primo in nz(vie[0]["chiave"]):
                self.approssimati.append((k, vie[0]["chiave"]))
                return vie[0], "stessa via"
        # ultimo tentativo: somiglianza (refusi di Peck, 'n 9' al posto di '9', ecc.)
        migliori = difflib.get_close_matches(nsp, list(self.per_indirizzo_np), n=2, cutoff=0.86)
        if migliori:
            a = self.per_indirizzo_np[migliori[0]]
            self.approssimati.append((k, a["chiave"]))
            return a, "approssimato"
        return None, ""

    def cerca(self, r):
        """Ritorna (riga di aziende.csv o None, come l'ha trovata)."""
        if r["indirizzo"] or r["comune"]:
            a, come = self.cerca_indirizzo(r)
            if a:
                return a, "indirizzo (" + come + ")"
        if r["bollo_ce"]:
            a = self.per_bollo.get(nz(r["bollo_ce"]))
            if a:
                return a, "bollo CE"
        if r["produttore_nominato"]:
            a = self.per_produttore.get(nz(r["produttore_nominato"]))
            if a:
                return a, "produttore nominato"
        return None, ""


# ---------------------------------------------------------------------------
# Costruzione dei dati del cibo
# ---------------------------------------------------------------------------

def costruisci_cibo():
    prodotti = leggi_csv("prodotti")
    elementi = leggi_csv("elementi")
    aziende = Aziende(leggi_csv("aziende"))

    # --- box (le 46 pagine dello shop)
    box = {}
    for p in prodotti:
        sl = p["url"].rstrip("/").rsplit("/", 1)[-1]
        box[p["url"]] = {
            "id": sl, "nome": bello(p["nome"]), "nome_originale": p["nome"], "url": p["url"],
            "tipo": p["tipo"], "prezzo": float(p["prezzo"]) if p["prezzo"] else None,
            "prezzo_testo": euro_testo(p["prezzo"]), "n_elementi_dichiarati": int(p["numero_elementi"]),
            "foto": foto_pagina(sl), "elementi": [],
        }

    # --- elementi distinti (stesso nome in piu' box = un solo elemento)
    elem = {}      # nome originale -> dict
    ordine = []
    for r in elementi:
        nome = r["nome_elemento"].strip()
        e = elem.get(nome)
        if e is None:
            e = elem[nome] = {"nome_originale": nome, "righe": [], "box": []}
            ordine.append(nome)
        e["righe"].append(r)
        if r["url_pagina"] not in e["box"]:
            e["box"].append(r["url_pagina"])
        b = box.get(r["url_pagina"])
        if b is not None and nome not in b["elementi"]:
            b["elementi"].append(nome)

    # --- id degli elementi
    usati = set()
    for nome in ordine:
        e = elem[nome]
        e["nome"] = bello(nome)
        base = slug(e["nome"])
        i, sid = 1, base
        while sid in usati:
            i += 1
            sid = f"{base}-{i}"
        usati.add(sid)
        e["id"] = sid
        e["categoria"] = categoria_di(nome)

    # --- foto: l'elemento di una pagina 'singolo' ha la foto della pagina;
    #     gli altri usano la foto della box piu' piccola in cui compaiono.
    foto_propria = {}
    for url, b in box.items():
        if b["tipo"] == "singolo" and len(b["elementi"]) == 1 and b["foto"]:
            foto_propria.setdefault(b["elementi"][0], (b["foto"], b["nome"]))
    for nome in ordine:
        e = elem[nome]
        if nome in foto_propria:
            e["foto"], e["foto_tipo"], e["foto_da"] = foto_propria[nome][0], "prodotto", foto_propria[nome][1]
            continue
        cand = [box[u] for u in e["box"] if u in box and box[u]["foto"]]
        if cand:
            piccola = min(cand, key=lambda b: (len(b["elementi"]), b["nome"]))
            e["foto"], e["foto_tipo"], e["foto_da"] = piccola["foto"], "box", piccola["nome"]
        else:
            e["foto"], e["foto_tipo"], e["foto_da"] = "", "", ""

    # --- province mancanti (comune -> provincia dagli altri dati)
    comune_prov = {}
    for r in elementi:
        if r["comune"] and r["provincia"] and r["provincia"].upper() in PROV_REGIONE:
            comune_prov.setdefault(nz(r["comune"]), r["provincia"].upper())

    def sigla(r):
        p = (r["provincia"] or "").strip()
        if p.upper() in PROV_REGIONE:
            return p.upper()
        if p.lower() in PROV_NOMI:
            return PROV_NOMI[p.lower()]
        c = nz(r["comune"])
        return comune_prov.get(c) or COMUNE_PROV.get(c, "")

    # --- aziende (uniche): unisce righe diverse con la stessa ragione sociale
    aziende_out = {}      # id -> dict
    per_nome = {}         # nome confrontabile -> id
    riga_a_azienda = {}   # id riga aziende.csv (chiave) -> id azienda

    def id_azienda(a):
        k = (a["tipo_chiave"], nz(a["chiave"]))
        if k in riga_a_azienda:
            return riga_a_azienda[k]
        rag = (a["ragione_sociale"] or "").strip()
        nome_k = nome_azienda_chiave(rag, a["marchio"])
        if rag and nome_k and nome_k in per_nome:
            aid = per_nome[nome_k]
        else:
            base = slug(rag or ("sconosciuta-" + a["chiave"]))
            aid, i = base, 1
            while aid in aziende_out:
                i += 1
                aid = f"{base}-{i}"
            aziende_out[aid] = {
                "id": aid, "nome": rag or "Azienda non trovata", "marchio": "", "sito": "",
                "shop_online": "", "link_shop": "", "fonti": [], "certezza": a["certezza"],
                "chiavi": [], "note": [], "prodotti": [], "luoghi": Counter(), "paese": "",
                "trovata": bool(rag),
            }
            if rag and nome_k:
                per_nome[nome_k] = aid
        z = aziende_out[aid]
        if a["marchio"] and not z["marchio"]:
            z["marchio"] = a["marchio"]
        if a["sito"] and not z["sito"]:
            z["sito"] = a["sito"]
        if a["link_shop"] and not z["link_shop"]:
            z["link_shop"] = a["link_shop"]
        # 'si' vince su 'non verificato' che vince su 'no'
        peso = {"si": 3, "non verificato": 2, "no": 1, "": 0}
        if peso.get(a["shop_online"], 0) > peso.get(z["shop_online"], 0):
            z["shop_online"] = a["shop_online"]
        if a["fonte"] and a["fonte"] not in z["fonti"]:
            z["fonti"].append(a["fonte"])
        if ORDINE_STATI.index(a["certezza"] if a["certezza"] in ORDINE_STATI else NON_TROVATA) < \
                ORDINE_STATI.index(z["certezza"] if z["certezza"] in ORDINE_STATI else NON_TROVATA):
            z["certezza"] = a["certezza"]
        z["chiavi"].append({"tipo": a["tipo_chiave"], "chiave": a["chiave"],
                            "certezza": a["certezza"], "fonte": a["fonte"]})
        if a["nota"]:
            z["note"].append(a["nota"])
        riga_a_azienda[k] = aid
        return aid

    # azienda 'Peck stessa' (indirizzi di Peck dichiarati come luogo di produzione/confezionamento)
    aziende_out["peck"] = {
        "id": "peck", "nome": "Peck S.p.A. (via Spadari 9, Milano)", "marchio": "Peck", "sito": "",
        "shop_online": "", "link_shop": "", "fonti": [], "certezza": PECK, "chiavi": [], "note": [
            "Sono i prodotti per cui Peck scrive di averli prodotti o confezionati nella sua sede "
            "di via Spadari 9, a Milano."],
        "prodotti": [], "luoghi": Counter({("Milano", "MI", "Italia"): 1}), "paese": "Italia",
        "trovata": True,
    }

    # --- origini di ogni elemento
    n_righe_con_origine = 0
    n_righe_abbinate = 0
    come_abbinate = Counter()
    for nome in ordine:
        e = elem[nome]
        origini, viste = [], set()
        for r in e["righe"]:
            frase = r["frase_origine"].strip()
            ha_luogo = bool(r["indirizzo"] or r["comune"] or r["bollo_ce"] or r["produttore_nominato"])
            if r["sede_peck"] == "si":
                stato, aid, come = PECK, "peck", "sede Peck"
            elif ha_luogo:
                n_righe_con_origine += 1
                a, come = aziende.cerca(r)
                if a:
                    aid = id_azienda(a)
                    stato = a["certezza"] if a["certezza"] in (CERTA, PROBABILE, NON_TROVATA) else NON_TROVATA
                    n_righe_abbinate += 1
                    come_abbinate[come] += 1
                else:
                    # indirizzo senza riga in aziende.csv: azienda 'non cercata'
                    aid = id_azienda({
                        "tipo_chiave": "indirizzo", "chiave": chiave_indirizzo(r) or r["produttore_nominato"]
                        or r["bollo_ce"], "ragione_sociale": "", "marchio": "", "sito": "",
                        "shop_online": "", "link_shop": "", "fonte": "", "certezza": NON_TROVATA,
                        "nota": "Questo indirizzo non e' ancora stato cercato in data/aziende.csv."})
                    stato = NON_TROVATA
            else:
                aid, stato = "", NESSUNA
            if r["sede_peck"] != "si" and not ha_luogo and not frase:
                pass
            chiave_o = (frase, r["indirizzo"], r["comune"], r["bollo_ce"], r["produttore_nominato"])
            if chiave_o in viste:
                continue
            viste.add(chiave_o)
            sg = sigla(r)
            paese = r["paese"] or COMUNE_PAESE.get(nz(r["comune"]), "") or ("Italia" if sg else "")
            origini.append({
                "frase": frase, "ruolo": r["ruolo"], "indirizzo": r["indirizzo"], "cap": r["cap"],
                "comune": r["comune"], "provincia": sg or r["provincia"], "paese": paese,
                "bollo": r["bollo_ce"], "nominato": r["produttore_nominato"],
                "azienda": aid, "stato": stato, "nota": r["nota"],
            })
            if aid and r["comune"] and aid in aziende_out:
                aziende_out[aid]["luoghi"][(r["comune"], sg, paese)] += 1
            elif aid and aid in aziende_out and paese:
                aziende_out[aid]["luoghi"][("", "", paese)] += 1
        # se un elemento ha una frase vera, non serve mostrare anche la riga 'nessuna indicazione'
        if any(o["stato"] != NESSUNA for o in origini):
            origini = [o for o in origini if o["stato"] != NESSUNA or o["frase"]]
        e["origini"] = origini
        e["stato"] = min((o["stato"] for o in origini), key=ORDINE_STATI.index, default=NESSUNA)

    # righe di aziende.csv che nessun prodotto ha usato ma che sono della stessa azienda
    # (per esempio il bollo CE di un'azienda gia' trovata dal suo indirizzo): si aggiungono alle sue chiavi
    for a in aziende.righe:
        if (a["tipo_chiave"], nz(a["chiave"])) not in riga_a_azienda:
            nk = nome_azienda_chiave(a["ragione_sociale"], a["marchio"])
            if a["ragione_sociale"] and nk in per_nome:
                id_azienda(a)

    # --- azienda: luogo principale e prodotti
    for z in aziende_out.values():
        # un luogo con comune vince su uno senza
        con_comune = [(c, n) for c, n in z["luoghi"].items() if c[0]]
        pool = con_comune or list(z["luoghi"].items())
        if pool:
            (comune, prov, paese), _ = max(pool, key=lambda x: x[1])
            z["comune"], z["provincia"], z["paese"] = comune, prov, paese
        else:
            z["comune"], z["provincia"], z["paese"] = "", "", ""
        z["regione"] = regione_di(z["provincia"], z["paese"])
        del z["luoghi"]
        # nome da mostrare: senza le note tra parentesi (la ragione sociale intera resta in 'ragione')
        z["ragione"] = z["nome"]
        breve = re.sub(r"\s*\([^)]*\)", "", z["nome"]).strip(" ,-")
        if z["trovata"] and breve:
            z["nome"] = breve
    for nome in ordine:
        e = elem[nome]
        for o in e["origini"]:
            if o["azienda"] and e["id"] not in aziende_out[o["azienda"]]["prodotti"]:
                aziende_out[o["azienda"]]["prodotti"].append(e["id"])
        # luogo mancante in un'origine (es. 'Regione Prati e Pescine'): prende quello dell'azienda
        for o in e["origini"]:
            z = aziende_out.get(o["azienda"])
            if z and not o["comune"] and z["comune"]:
                o["comune_azienda"] = z["comune"]
                if not o["provincia"]:
                    o["provincia"] = z["provincia"]
                if not o["paese"]:
                    o["paese"] = z["paese"]
        for o in e["origini"]:
            o["regione"] = regione_di(o["provincia"], o["paese"])
        e["regioni"] = sorted({o["regione"] for o in e["origini"] if o["regione"]})

    # --- uscita
    id_box = {u: b["id"] for u, b in box.items()}
    dispensa = []
    for nome in ordine:
        e = elem[nome]
        dispensa.append({
            "id": e["id"], "nome": e["nome"], "nome_originale": e["nome_originale"],
            "categoria": e["categoria"], "stato": e["stato"], "regioni": e["regioni"],
            "foto": e["foto"], "foto_tipo": e["foto_tipo"], "foto_da": e["foto_da"],
            "box": [id_box[u] for u in e["box"] if u in id_box], "origini": e["origini"],
        })
    id_el = {n: elem[n]["id"] for n in ordine}
    box_out = []
    for u, b in box.items():
        box_out.append({
            "id": b["id"], "nome": b["nome"], "url": b["url"], "tipo": b["tipo"],
            "prezzo": b["prezzo"], "prezzo_testo": b["prezzo_testo"],
            "n_elementi": len(b["elementi"]), "n_elementi_dichiarati": b["n_elementi_dichiarati"],
            "foto": b["foto"], "elementi": [id_el[n] for n in b["elementi"]],
        })
    produttori = []
    for z in aziende_out.values():
        if not z["prodotti"]:
            continue  # righe di aziende.csv senza nessun prodotto sul sito
        z["chiavi"] = [dict(t) for t in {tuple(sorted(c.items())) for c in z["chiavi"]}]
        z["chiavi"].sort(key=lambda c: (c["tipo"], c["chiave"]))
        z["note"] = list(dict.fromkeys(z["note"]))
        produttori.append(z)
    produttori.sort(key=lambda z: (ORDINE_STATI.index(z["certezza"]) if z["certezza"] in ORDINE_STATI
                                   else 9, nz(z["nome"])))

    stat = {
        "elementi": len(dispensa), "box": len(box_out), "produttori": len(produttori),
        "righe_con_luogo": n_righe_con_origine, "righe_abbinate": n_righe_abbinate,
        "come_abbinate": dict(come_abbinate),
        "stati_elementi": dict(Counter(d["stato"] for d in dispensa)),
        "categorie": dict(Counter(d["categoria"] for d in dispensa)),
        "approssimati": aziende.approssimati,
        "foto_box": sum(1 for b in box_out if b["foto"]),
        "foto_elementi": Counter(d["foto_tipo"] or "nessuna" for d in dispensa),
        "box_conteggio_diverso": [(b["nome"], b["n_elementi"], b["n_elementi_dichiarati"])
                                  for b in box_out if b["n_elementi"] != b["n_elementi_dichiarati"]],
        "aziende_non_usate": [a["chiave"] for a in aziende.righe
                              if (a["tipo_chiave"], nz(a["chiave"])) not in riga_a_azienda],
    }
    return dispensa, box_out, produttori, stat


# ---------------------------------------------------------------------------
# Enoteca
# ---------------------------------------------------------------------------

def costruisci_vini(box_per_nome):
    righe = leggi_csv("vini")
    cantine_csv = leggi_csv("cantine")
    nelle_box = leggi_csv("vini_nelle_box")

    foto, slugs = {}, {}
    for f in sorted(glob.glob(str(RAW / "winerim" / "vini_p*.json"))):
        with open(f, encoding="utf-8") as fh:
            j = json.load(fh)
        for w in j.get("results", []):
            foto[str(w["id"])] = (w.get("photo") or "").strip()
            slugs[str(w["id"])] = w.get("slugname") or ""

    def foto_corta(u):
        if u.startswith(FOTO_WINERIM_PREFISSO):
            return u[len(FOTO_WINERIM_PREFISSO):]
        return u if u.startswith("https://") else ""

    cantine_nomi = sorted({r["cantina"] for r in righe}, key=lambda s: nz(s) + s)
    idx_cantina = {n: i for i, n in enumerate(cantine_nomi)}
    paesi = sorted({r["paese"] for r in righe})
    regioni = sorted({(r["paese"], r["regione"]) for r in righe if r["regione"]})
    tipi = ["rosso", "bianco", "spumante", "rosato", "dolce", "liquoroso/fortificato"]
    tipi += sorted({r["tipo"] for r in righe} - set(tipi))

    vini = {}
    for r in righe:
        w = vini.get(r["id"])
        if w is None:
            w = vini[r["id"]] = {
                "id": int(r["id"]), "n": r["nome"], "a": r["annata"], "t": tipi.index(r["tipo"]),
                "p": paesi.index(r["paese"]), "r": r["regione"], "c": idx_cantina[r["cantina"]],
                "u": [x.strip() for x in r["uve"].split(";") if x.strip()],
                "s": slugs.get(r["id"]) or r["link"].rsplit("/", 1)[-1],
                "ph": foto_corta(foto.get(r["id"], "")), "f": [],
            }
            link_atteso = f"{LINK_WINERIM_PREFISSO}{r['id']}/{w['s']}"
            if r["link"] != link_atteso:
                w["l"] = r["link"]
        try:
            prezzo = float(r["prezzo_euro"]) if r["prezzo_euro"] != "" else None
        except ValueError:
            prezzo = None
        if prezzo is not None and prezzo <= 0:
            prezzo = None
        w["f"].append([r["variante"] or r["formato"] or "", r["formato"], prezzo,
                       1 if r["in_stock"] == "si" else 0, r["nota"]])
    for w in vini.values():
        # prezzo principale: bottiglia da 750 ml, se c'e' e ha prezzo; se no il primo prezzo
        bott = [f for f in w["f"] if f[1] == "750ml" and f[2] is not None]
        con = [f for f in w["f"] if f[2] is not None]
        w["pr"] = (bott or con or [[None, None, None]])[0][2]
    lista = sorted(vini.values(), key=lambda w: w["id"])

    cant = []
    for c in cantine_csv:
        cant.append({
            "nome": c["cantina"], "paese": c["paese"], "regioni": c["regioni"],
            "n": int(c["n_etichette"] or 0),
            "tipi": {"rosso": int(c["n_rossi"] or 0), "bianco": int(c["n_bianchi"] or 0),
                     "spumante": int(c["n_spumanti"] or 0), "dolce": int(c["n_dolci"] or 0),
                     "rosato": int(c["n_rosati"] or 0), "liquoroso/fortificato": int(c["n_liquorosi"] or 0)},
            "pmin": float(c["prezzo_min"]) if c["prezzo_min"] else None,
            "pmax": float(c["prezzo_max"]) if c["prezzo_max"] else None,
            "nota": c["nota"], "box": [],
        })
    cant_per_nome = {c["nome"]: c for c in cant}
    for r in nelle_box:
        nome = r["cantina_in_carta"]
        if nome in cant_per_nome:
            for bn in re.split(r"\s*(?:\||;)\s*", r["box"]):
                bid = box_per_nome.get(nz(bn))
                if bid and bid not in cant_per_nome[nome]["box"]:
                    cant_per_nome[nome]["box"].append(bid)
    # la cantina di un vino e' un indice nella lista ordinata: allinea le due liste
    ordine_cant = {c["nome"]: c for c in cant}
    cantine_ordinate = [ordine_cant[n] for n in cantine_nomi if n in ordine_cant]
    mancanti = [n for n in cantine_nomi if n not in ordine_cant]
    for n in mancanti:  # cantina presente nei vini ma non in cantine.csv (non dovrebbe succedere)
        cantine_ordinate.insert(cantine_nomi.index(n), {
            "nome": n, "paese": "", "regioni": "", "n": 0, "tipi": {}, "pmin": None, "pmax": None,
            "nota": "", "box": []})
    usati = set()
    for c in cantine_ordinate:  # id leggibile e unico per l'indirizzo #/cantina/<id>
        base, i = slug(c["nome"]), 1
        cid = base
        while cid in usati:
            i += 1
            cid = f"{base}-{i}"
        usati.add(cid)
        c["id"] = cid
    prezzi = [w["pr"] for w in lista if w["pr"] is not None]
    meta = {
        "n_vini": len(lista), "n_cantine": len(cantine_ordinate), "paesi": paesi, "tipi": tipi,
        "regioni": [[p, r] for p, r in regioni],
        "prezzo_min": min(prezzi), "prezzo_max": max(prezzi), "senza_prezzo": len(lista) - len(prezzi),
        "prefisso_foto": FOTO_WINERIM_PREFISSO, "prefisso_link": LINK_WINERIM_PREFISSO,
        "data": DATA_FOTOGRAFIA,
    }
    out = {"meta": meta, "cantine": cantine_ordinate, "vini": lista}
    return out, {"mancanti": mancanti, "senza_foto": sum(1 for w in lista if not w["ph"]),
                 "link_diversi": sum(1 for w in lista if "l" in w)}


# ---------------------------------------------------------------------------

def scrivi(nome, dati):
    DOCS.mkdir(exist_ok=True)
    p = DOCS / nome
    testo = json.dumps(dati, ensure_ascii=False, separators=(",", ":"))
    p.write_text(testo, encoding="utf-8")
    return len(testo.encode("utf-8"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dispensa, box, produttori, st = costruisci_cibo()
    box_per_nome = {nz(b["nome"]): b["id"] for b in box}
    vini, stv = costruisci_vini(box_per_nome)

    meta = {
        "data": DATA_FOTOGRAFIA, "generato": date.today().isoformat(), "repo": REPO,
        "csv": [f"{REPO}/blob/main/data/{n}.csv" for n in
                ("prodotti", "elementi", "indirizzi", "altre_origini", "aziende", "vini",
                 "cantine", "vini_nelle_box")],
        "categorie": ORDINE_CATEGORIE,
        "categorie_parole": {c: p for c, p in CATEGORIE},
        "stati": ORDINE_STATI,
        "n_elementi": len(dispensa), "n_box": len(box), "n_produttori": len(produttori),
        "n_vini": vini["meta"]["n_vini"], "n_cantine": vini["meta"]["n_cantine"],
    }
    n1 = scrivi("dati.json", {"meta": meta, "dispensa": dispensa, "box": box, "produttori": produttori})
    n2 = scrivi("vini.json", vini)

    print(f"dati.json: {n1/1024:.0f} KB   vini.json: {n2/1024:.0f} KB")
    print(f"elementi (dispensa): {st['elementi']}   box/pagine: {st['box']}   produttori: {st['produttori']}"
          f"   vini: {vini['meta']['n_vini']}   cantine: {vini['meta']['n_cantine']}")
    print(f"righe di origine con un luogo/codice: {st['righe_con_luogo']}, abbinate a un'azienda: "
          f"{st['righe_abbinate']}  ({st['come_abbinate']})")
    print("stato degli elementi:", st["stati_elementi"])
    print("categorie:", st["categorie"])
    print("foto elementi:", dict(st["foto_elementi"]), " foto box:", st["foto_box"], "/", st["box"])
    if st["approssimati"]:
        print("abbinamenti approssimati (da controllare):")
        for a, b in sorted(set(st["approssimati"])):
            print("   ", a, "->", b)
    if st["box_conteggio_diverso"]:
        print("box con numero di elementi diverso da prodotti.csv:", st["box_conteggio_diverso"])
    if st["aziende_non_usate"]:
        print("righe di aziende.csv non usate da nessun elemento:", st["aziende_non_usate"])
    print("vini senza foto:", stv["senza_foto"], " link diversi dal solito:", stv["link_diversi"],
          " cantine mancanti in cantine.csv:", stv["mancanti"], " vini senza prezzo:",
          vini["meta"]["senza_prezzo"])


if __name__ == "__main__":
    main()
