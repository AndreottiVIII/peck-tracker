"""Costruisce il sito statico (le pagine in docs/) dai file CSV in data/.

Si lancia dalla cartella peck-tracker, con Python 3.12:

    python -I src/sito.py

Si puo' rilanciare quando si vuole (per esempio dopo aver aggiornato data/aziende.csv): cancella
le pagine generate e le riscrive da zero. Non scarica nulla. Nelle pagine finiscono solo indirizzi
web (URL) delle foto, mai le foto: le foto restano sui server di Peck e di Winerim.

Ogni pagina ha un indirizzo vero (una cartella con dentro index.html), con link relativi, cosi'
funziona sia su https://andreottiviii.github.io/peck-tracker/ sia alla radice di un server locale:

    docs/index.html                       home (e' la Dispensa)
    docs/dispensa/                        elenco dei prodotti, con filtri
    docs/prodotto/<id>/                   un prodotto alimentare
    docs/box/            docs/box/<id>/   le pagine dello shop di Peck, "spacchettate"
    docs/produttori/     docs/produttore/<id>/
    docs/enoteca/        docs/cantina/<id>/   docs/vino/<id>-<nome>/
    docs/come-funziona/
    docs/404.html, docs/sitemap.xml, docs/robots.txt, docs/vini.json (dati per i filtri dell'enoteca)

I file scritti a mano e che questo programma NON tocca: docs/style.css, docs/app.js e i disegni
docs/disegni/*.svg (nostri; quale disegno va a quale prodotto lo decide DISEGNI_PAROLE). Il file
docs/personale.js (il logo di Peck, solo per il computer del proprietario) e' nel .gitignore e non
viene mai pubblicato.

Legge:  data/prodotti.csv, elementi.csv, indirizzi.csv, altre_origini.csv, aziende.csv,
        vini.csv (compresi gli attributi di degustazione), cantine.csv, vini_nelle_box.csv,
        link_controllati.csv (se c'e': i bottoni dei link rotti non si mostrano),
        delivery_dispensa.csv (se c'e': prezzo e foto del servizio delivery per i prodotti abbinati;
        lo scrive src/delivery_dispensa.py),
        data/raw/prodotto_*.html (per le foto) e data/raw/winerim/vini_p*.json (per le foto delle bottiglie).
"""

import csv
import difflib
import glob
import html
import json
import math
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

RADICE = Path(__file__).resolve().parent.parent
DATI = RADICE / "data"
RAW = DATI / "raw"
DOCS = RADICE / "docs"

REPO = "https://github.com/AndreottiVIII/peck-tracker"
URL_SITO = "https://andreottiviii.github.io/peck-tracker/"
PREFISSO_SITO = "/peck-tracker/"   # solo per la pagina 404, che GitHub serve da qualsiasi percorso
FOTO_PECK_HOST = "https://shop.peck.it/"
FOTO_WINERIM_PREFISSO = "https://app.winerim.com/images/wines/"
LINK_WINERIM_PREFISSO = "https://web.winerim.com/enotecapeck/wines/"
DATA_FOTOGRAFIA = "2026-10-24"
DATA_DELIVERY = "2026-10-25"          # il giorno in cui abbiamo guardato il catalogo del servizio delivery
FONTE_DELIVERY = "dal servizio delivery di Peck, 25 ottobre 2026"
DATA_FOTOGRAFIA_LUNGA = "24 ottobre 2026"   # = DATA_FOTOGRAFIA, per la linea del tempo del fornitore
AVVISO = "Progetto indipendente di appassionati, non affiliato a Peck. Nessun prodotto in vendita."

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

# ---------------------------------------------------------------------------
# Disegni della Dispensa: docs/disegni/<nome>.svg, disegnati a mano per questo sito (sono nostri).
# Quasi nessun prodotto ha una foto tutta sua (Peck mostra la foto della box), e la foto della
# box non fa capire che cosa sia il prodotto: al suo posto c'e' un disegno. Si sceglie cosi':
#   1. DISEGNI_PAROLE: la prima riga che ha una parola nel nome vince (stesse regole di
#      CATEGORIE: nome in minuscolo, una parola che inizia con ^ vale solo all'inizio del nome);
#   2. se nessuna parola va bene, il disegno della categoria (DISEGNO_CATEGORIA).
# I prodotti con una foto propria di Peck (le pagine "singolo": panettoni, pandoro, veneziana,
# salmone, frutta disidratata) tengono la foto. Le pagine delle Box regalo usano sempre le foto.
# L'ordine conta: "biscotti al caramello" sono biscotti, "gelatine panettone al rum" sono
# caramelle, "taralli al pomodoro" sono taralli (biscotti), "torrone ricoperto di cioccolato"
# e' torrone, "salametto al cioccolato" e' cioccolato, "amarena tartufata" e' un dolce al
# cioccolato (non tartufo), "noci e miele" e' frutta secca (per questo "^miele").
# ---------------------------------------------------------------------------
DISEGNI_PAROLE = [
    ("biscotti", ["biscott", "krumiri", "baci di dama", "amaretti", "taralli"]),
    ("caramelle", ["caramell", "gelatine", "marrons gla"]),
    ("panettone", ["panettone", "pandoro", "veneziana"]),
    ("torrone", ["torron", "panforte"]),
    ("crema", ["zabaione", "^crema", "burro"]),
    ("praline", ["praline", "gianduiotti", "tartufini", "marroncini", "rondelle", "moneta", "tartufat"]),
    ("tavoletta", ["tavolett", "salametto al cioccolato"]),
    ("prosciutto", ["prosciutto", "jamón", "paleta"]),
    ("pomodoro", ["pomodor", "passata", "ragù"]),
    ("marmellata", ["confettur", "marmellat", "^miele", "mostarda"]),
    ("sottolio", ["peperon"]),
    ("legumi", ["^riso", "lenticchie", "legumi"]),
]
DISEGNO_CATEGORIA = {
    "dolci e lievitati": "biscotti", "cioccolato": "tavoletta", "pasta e riso": "pasta",
    "salumi": "salame", "formaggi": "formaggio", "conserve e sottoli": "sottolio",
    "olio e aceto": "olio-aceto", "pesce": "pesce", "tè e caffè": "te-caffe",
    "vini e spumanti": "vino", "distillati": "distillato", "frutta secca": "frutta-secca",
    CATEGORIA_ALTRO: "legumi",
}
# Che cosa mostra ogni disegno (testo alternativo per chi non vede l'immagine).
DISEGNI_NOMI = {
    "panettone": "un panettone", "biscotti": "biscotti", "torrone": "un torrone",
    "caramelle": "caramelle incartate", "crema": "un vasetto di crema con il cucchiaino",
    "tavoletta": "una tavoletta di cioccolato", "praline": "una scatola di cioccolatini",
    "pasta": "pasta secca", "legumi": "un sacco di legumi", "salame": "un salame",
    "prosciutto": "un prosciutto", "formaggio": "una forma di formaggio",
    "sottolio": "un vaso di verdure sott’olio", "pomodoro": "un pomodoro",
    "marmellata": "un vasetto di marmellata", "olio-aceto": "una bottiglia d’olio e una d’aceto",
    "pesce": "un pesce", "te-caffe": "una tazza di tè o caffè", "vino": "una bottiglia di vino",
    "distillato": "una bottiglia di distillato", "frutta-secca": "frutta secca",
}

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

def ha_parola(n, parole):
    """True se il nome (gia' in minuscolo) contiene una delle parole (^ = all'inizio)."""
    return any(n.startswith(p[1:]) if p.startswith("^") else p in n for p in parole)


def categoria_di(nome):
    n = nome.lower()
    for cat, parole in CATEGORIE:
        if ha_parola(n, parole):
            return cat
    return CATEGORIA_ALTRO


def disegno_di(nome, categoria):
    """Il disegno di docs/disegni/ per un prodotto (vedi DISEGNI_PAROLE)."""
    n = nome.lower()
    for disegno, parole in DISEGNI_PAROLE:
        if ha_parola(n, parole):
            return disegno
    return DISEGNO_CATEGORIA.get(categoria, DISEGNO_CATEGORIA[CATEGORIA_ALTRO])


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

def carica_delivery():
    """data/delivery_dispensa.csv -> {chiave Dispensa: riga}. Se il file non c'e', nessun abbinamento."""
    if not (DATI / "delivery_dispensa.csv").exists():
        return {}
    return {r["chiave_dispensa"]: r for r in leggi_csv("delivery_dispensa")}


def prezzo_delivery(dv):
    """('6 € (180 g)', '44 € al kg'): il prezzo come lo mostriamo, dal campo unita (KG = al kg, PZ = a confezione)."""
    p = euro_it(float(dv["prezzo"]))
    return f"{p} al kg" if dv["unita"] == "KG" else f"{p} ({dv['formato']})"


def foto_chiave(url):
    """Per riconoscere la stessa foto scritta in due modi (%27 e '), confrontando solo il nome del file."""
    return unquote(url or "").strip().rsplit("/", 1)[-1].lower()


def carica_ritagli():
    """data/ritagli.csv -> {chiave Dispensa: dict}. Il rettangolo (x, y, w, h) e' in frazioni della foto della box."""
    f = DATI / "ritagli.csv"
    if not f.exists():
        return {}
    out = {}
    for r in leggi_csv("ritagli"):
        try:
            x, y, w, h = (float(r[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, ValueError):
            continue
        url = (r.get("url_foto_box") or "").strip()
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1) or not url.startswith(FOTO_PECK_HOST):
            continue
        out[r["chiave"].strip()] = {"url": url, "x": x, "y": y, "w": min(w, 1 - x), "h": min(h, 1 - y),
                                    "certezza": (r.get("certezza") or "alta").strip(), "nota": (r.get("nota") or "").strip()}
    return out


def luogo_da_chiave(a):
    """(comune, provincia, paese) dalla chiave di una riga di aziende.csv: «Via X 5, Bisceglie (BT)» o «ES 12.00487/H CE»."""
    k = a["chiave"]
    if a["tipo_chiave"] == "bollo_ce":
        return "", "", {"ES": "Spagna"}.get(k.strip()[:2].upper(), "")
    ultimo = k.split(",")[-1].strip()
    m = re.fullmatch(r"(.+?)(?:\s*\((\w{2})\))?", ultimo)
    comune, prov = (m.group(1), (m.group(2) or "").upper()) if m else (ultimo, "")
    if not prov:
        prov = COMUNE_PROV.get(nz(comune), "")
    return comune, prov, "Italia" if prov else ""


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
    # --- disegno: per tutti quelli senza una foto propria (vedi DISEGNI_PAROLE)
    for nome in ordine:
        e = elem[nome]
        e["disegno"] = "" if e["foto_tipo"] == "prodotto" else disegno_di(nome, e["categoria"])
    # --- servizio delivery di Peck: prezzo e, se c'e', la foto del prodotto (collegata, mai copiata)
    delivery = carica_delivery()
    for nome in ordine:
        e = elem[nome]
        dv = delivery.get(e["id"])
        e["delivery"] = dv
        if dv and dv["foto_url"]:
            e["foto"], e["foto_tipo"], e["foto_da"] = dv["foto_url"], "delivery", "servizio delivery di Peck"
            e["disegno"] = ""

    # --- ritagli dalle foto delle box (data/ritagli.csv): per i prodotti senza foto propria e senza foto del delivery
    ritagli = carica_ritagli()
    box_per_foto = defaultdict(list)
    for u, b in box.items():
        if b["foto"]:
            box_per_foto[foto_chiave(b["foto"])].append(b)
    ritagli_senza_box = []
    for nome in ordine:
        e = elem[nome]
        e["ritaglio"] = None
        rt = ritagli.get(e["id"])
        if not rt or e["foto_tipo"] in ("prodotto", "delivery"):
            continue
        cand = box_per_foto.get(foto_chiave(rt["url"]), [])
        dentro = [b for b in cand if b["url"] in e["box"]]
        b = (dentro or cand or [None])[0]
        if b is None:
            ritagli_senza_box.append(e["id"])
            continue
        e["ritaglio"] = dict(rt, box_id=b["id"], box_nome=b["nome"])
    ritagli_non_usati = sorted(set(ritagli) - {elem[n]["id"] for n in ordine if elem[n]["ritaglio"]})

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
                "trovata": bool(rag), "prodotti_testo": [], "fuori": False, "osservazioni": [],
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
        for t in (a.get("prodotti_peck") or "").split(";"):
            t = t.strip()
            if t and t not in z["prodotti_testo"]:
                z["prodotti_testo"].append(t)
        riga_a_azienda[k] = aid
        return aid

    # azienda 'Peck stessa' (indirizzi di Peck dichiarati come luogo di produzione/confezionamento)
    aziende_out["peck"] = {
        "id": "peck", "nome": "Peck S.p.A. (via Spadari 9, Milano)", "marchio": "Peck", "sito": "",
        "shop_online": "", "link_shop": "", "fonti": [], "certezza": PECK, "chiavi": [], "note": [
            "Sono i prodotti per cui Peck scrive di averli prodotti o confezionati nella sua sede "
            "di via Spadari 9, a Milano."],
        "prodotti": [], "luoghi": Counter({("Milano", "MI", "Italia"): 1}), "paese": "Italia",
        "trovata": True, "prodotti_testo": [], "fuori": False, "osservazioni": [],
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

    # aziende di aziende.csv che nessun prodotto dello shop 2026 usa ma che hanno un nome e una ricerca fatta
    # (visti nel 2025, nel delivery o in un secondo giro): hanno la loro pagina, segnata «fuori dallo shop del 2026»
    for a in aziende.righe:
        if ((a["tipo_chiave"], nz(a["chiave"])) not in riga_a_azienda and (a["ragione_sociale"] or "").strip()
                and a["certezza"] in (CERTA, PROBABILE)):
            aid = id_azienda(a)
            aziende_out[aid]["fuori"] = True
            aziende_out[aid]["luoghi"][luogo_da_chiave(a)] += 1

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
            "disegno": e["disegno"], "delivery": e["delivery"], "ritaglio": e["ritaglio"],
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
        if not z["prodotti"] and not z["fuori"]:
            continue  # righe di aziende.csv senza nessun prodotto sul sito
        z["fuori"] = not z["prodotti"]
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
        "disegni": Counter(d["disegno"] or "(foto propria)" for d in dispensa),
        "box_conteggio_diverso": [(b["nome"], b["n_elementi"], b["n_elementi_dichiarati"])
                                  for b in box_out if b["n_elementi"] != b["n_elementi_dichiarati"]],
        "ritagli": sum(1 for d in dispensa if d["ritaglio"]), "ritagli_senza_box": ritagli_senza_box,
        "ritagli_non_usati": ritagli_non_usati, "_aziende": aziende, "_riga_a_azienda": riga_a_azienda,
        "aziende_non_usate": [a["chiave"] for a in aziende.righe
                              if (a["tipo_chiave"], nz(a["chiave"])) not in riga_a_azienda],
    }
    return dispensa, box_out, produttori, stat



# ---------------------------------------------------------------------------
# Link controllati (data/link_controllati.csv, scritto da src/controlla_link.py)
# ---------------------------------------------------------------------------

class Link:
    """Dice se un link si puo' mostrare. Un link marcato 'rotto' o 'dominio_parcheggiato' non
    diventa mai un bottone. Se il file non c'e' si mostrano tutti."""

    def __init__(self):
        self.esiti = {}
        self.data = ""
        self.conteggi = Counter()
        f = DATI / "link_controllati.csv"
        if f.exists():
            self.data = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
            for r in leggi_csv("link_controllati"):
                self.esiti[r["url"]] = r["esito"]
                self.conteggi[(r["campo"], r["esito"])] += 1

    def buono(self, url):
        return bool(url) and self.esiti.get(url, "ok") not in ("rotto", "dominio_parcheggiato")


LINK = Link()


# ---------------------------------------------------------------------------
# Enoteca
# ---------------------------------------------------------------------------

ATTRIBUTI_VINO = [  # (colonna in vini.csv, nome mostrato)
    ("intensita", "Intensità"), ("freschezza", "Freschezza"), ("dolcezza", "Dolcezza"),
    ("tannicita", "Tannicità"), ("fruttato", "Fruttato"), ("affinamento", "Affinamento"),
]


def termini_vino(cantina, nome):
    """Le parole con cui cercare il vino su Vivino e Wine-Searcher: cantina + nome, senza
    ripetere la cantina se il nome la contiene gia'."""
    if nz(cantina) and nz(cantina) in nz(nome):
        return nome.strip()
    return f"{cantina} {nome}".strip()


def url_vivino(termini):
    return "https://www.vivino.com/search/wines?q=" + quote(termini, safe="!'()*")


def url_wine_searcher(termini, annata):
    parole = re.findall(r"[a-z0-9]+", senza_accenti(termini).lower())
    u = "https://www.wine-searcher.com/find/" + "+".join(parole)
    if re.fullmatch(r"(19|20)\d\d", annata or ""):
        u += "/" + annata
    return u


def url_tannico_ricerca(termini):
    return "https://www.tannico.it/search?q=" + "+".join(quote(p, safe="") for p in termini.split())


def carica_tannico():
    """id vino -> (url, nota_annata, formato_tannico) per i vini con scheda su Tannico.
    nota_annata e' "" se l'annata e' quella giusta. formato_tannico e' "" se il formato e' lo stesso di Peck
    (esatta o annata diversa); se invece Tannico ha SOLO un altro formato (corrispondenza "da controllare" con
    la sola nota «formato diverso») il vino e' collegato lo stesso, ma con il formato scritto, per esempio
    "0,75 L". Gli altri vini non compaiono: per loro il bottone apre la ricerca. Il file e' prodotto da
    src/tannico.py."""
    try:
        righe = leggi_csv("tannico")
    except FileNotFoundError:
        return {}

    def anno_di(t):
        m = re.search(r"(?:19|20)\d\d", t["titolo_tannico"] or "")
        if not m:  # il titolo a volte non ha l'anno, l'indirizzo si' (...-2022)
            m = re.search(r"(?<=-)(?:19|20)\d\d(?=-|$)", t["url_tannico"].rstrip("/"))
        return m.group(0) if m else ""

    out = {}
    for t in righe:
        if t["corrispondenza"] == "esatta" and t["url_tannico"]:
            out[t["id"]] = (t["url_tannico"], "", "")
        elif t["corrispondenza"] == "annata diversa" and t["url_tannico"]:
            out[t["id"]] = (t["url_tannico"], anno_di(t) or "un’altra annata", "")
        elif t["corrispondenza"] == "da controllare" and t["url_tannico"]:
            m = re.fullmatch(r"formato diverso \(Peck [\d/]+ ml, Tannico (\d+) ml\)", t["nota"] or "")
            if m:
                anno = anno_di(t)
                out[t["id"]] = (t["url_tannico"], anno if anno and t["annata"] and anno != t["annata"] else "",
                                litri_it(int(m.group(1)) / 1000) + " L")
    return out


# Critici in ordine di "peso" per scegliere il voto da mettere sul bollino (solo scala 100).
# Se nessuno e' presente si usa il giudizio di Tannico stesso.
CRITICI_ORDINE = ["Robert Parker", "James Suckling", "Wine Spectator", "Decanter", "Antonio Galloni", "Vinous",
                  "Wine Enthusiast", "Falstaff", "Gambero Rosso", "Veronelli", "Luca Maroni", "Doctor Wine", "Bibenda"]
CRITICI_BREVI = {"Robert Parker": "Parker", "James Suckling": "Suckling", "Antonio Galloni": "Galloni"}


def leggi_critici(testo):
    """'Robert Parker 94/100; Bibenda 5 grappoli' -> [(nome, valore, scala_o_unita)]."""
    out = []
    for voce in (testo or "").split(";"):
        m = re.fullmatch(r"\s*(.+?) (\d+(?:\.\d+)?)(?:/(\d+)| ([^\W\d_]+))?\s*", voce)
        if m:
            out.append((m.group(1), m.group(2), m.group(3) or m.group(4) or ""))
    return out


def carica_voti():
    """id vino -> voti presi dalla scheda Tannico (data/tannico_voti.csv, prodotto da `tannico.py voti`)."""
    try:
        righe = leggi_csv("tannico_voti")
    except FileNotFoundError:
        return {}
    out = {}
    for r in righe:
        critici = leggi_critici(r["voti_critici"])
        pt = int(r["punteggio_tannico"]) if r["punteggio_tannico"].isdigit() else None
        if pt is None and not critici:
            continue
        voce = {"anno": r["annata_tannico"], "diversa": r["corrispondenza"] == "annata diversa",
                "tannico": pt, "critici": critici, "url": r["url_tannico"], "data": r["data_raccolta"]}
        # voto del bollino: il critico piu' autorevole su scala 100, altrimenti il giudizio di Tannico
        scelto = None
        for nome in CRITICI_ORDINE:
            for c in critici:
                if c[0] == nome and c[2] == "100":
                    scelto = (CRITICI_BREVI.get(nome, nome), int(float(c[1])))
                    break
            if scelto:
                break
        if not scelto:
            for c in critici:  # un critico non in elenco, ma su scala 100
                if c[2] == "100":
                    scelto = (CRITICI_BREVI.get(c[0], c[0]), int(float(c[1])))
                    break
        voce["critico_bollino"] = scelto                  # (nome breve, voto /100) o None
        voce["bollino"] = scelto or (("Tannico", pt) if pt is not None else None)
        out[r["id"]] = voce
    return out


# ---------------------------------------------------------------------------
# Voti da fonti aperte (data/voti_aperti.csv: Wine Enthusiast e X-Wines) e dalle enoteche
# (data/voti_enoteche.csv, se c'e': punteggi di critici riportati da un negozio, con link)
# ---------------------------------------------------------------------------

MAX_SCARTO_ANNATA = 2          # stessa regola dei voti Tannico: oltre 2 anni il voto non si usa
XW_MIN_VOTI = 10
WE_LICENZA = "CC BY-NC-SA 4.0"
XW_DOI = "https://doi.org/10.3390/bdcc7010020"


def scarto_annata(ap, aa, corr):
    """Anni di distanza fra l'annata Peck (ap) e quella del voto (aa); None se il voto non si puo' usare.
    Si usano solo le righe `esatta` e `annata diversa` entro MAX_SCARTO_ANNATA anni."""
    ap, aa = (ap or "").strip(), (aa or "").strip()
    if corr == "esatta":
        return abs(int(ap) - int(aa)) if ap.isdigit() and aa.isdigit() else 0
    if corr == "annata diversa" and ap.isdigit() and aa.isdigit():
        d = abs(int(ap) - int(aa))
        return d if 0 < d <= MAX_SCARTO_ANNATA else None
    return None


def numero(x):
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def carica_voti_aperti():
    """id vino -> {"we": [...], "xw": [...], "en": [...]}, ancora da filtrare per annata (dipende dal vino Peck).
    Non legge MAI voti_aperti_da_controllare.csv."""
    out = defaultdict(lambda: {"we": [], "xw": [], "en": []})
    try:
        righe = leggi_csv("voti_aperti")
    except FileNotFoundError:
        righe = []
    for r in righe:
        voto = numero(r["voto"])
        if voto is None or r["corrispondenza"] not in ("esatta", "annata diversa"):
            continue
        base = {"anno": r["annata_fonte"].strip(), "corr": r["corrispondenza"], "voto": voto}
        if r["fonte"] == "Wine Enthusiast" and r["scala"] == "100":
            critico = r["critico/rivista"].strip()
            base["critico"] = "" if critico in ("", "Wine Enthusiast") else critico
            if base not in out[r["id"]]["we"]:
                out[r["id"]]["we"].append(base)
        elif r["fonte"] == "X-Wines" and r["scala"] == "5":
            m = re.search(r"n=(\d+)", r["critico/rivista"])
            base["n"] = int(m.group(1)) if m else 0
            if base["n"] >= XW_MIN_VOTI:
                out[r["id"]]["xw"].append(base)
    try:
        righe = leggi_csv("voti_enoteche")
    except FileNotFoundError:
        righe = []
    for r in righe:
        voto = numero(r.get("voto"))
        if voto is None or r.get("corrispondenza") not in ("esatta", "annata diversa"):
            continue
        out[r["id"]]["en"].append({"anno": (r.get("annata_fonte") or "").strip(), "corr": r["corrispondenza"],
                                   "voto": voto, "scala": (r.get("scala") or "100").strip(),
                                   "fonte": (r.get("fonte") or "").strip(), "url": (r.get("url") or "").strip(),
                                   "critico": (r.get("critico") or "").strip()})
    return out


def filtra_aperti(grezzi, annata_peck):
    """Tiene solo i voti con annata uguale o a non piu' di 2 anni; aggiunge `scarto` e `diversa`."""
    out = {"we": [], "xw": [], "en": []}
    for k in out:
        for e in grezzi[k]:
            sc = scarto_annata(annata_peck, e["anno"], e["corr"])
            if sc is None:
                continue
            e = dict(e, scarto=sc, diversa=e["anno"].isdigit() and e["anno"] != (annata_peck or "").strip())   # «NV» non e' un'annata diversa
            out[k].append(e)
    out["we"].sort(key=lambda e: (e["scarto"], -e["voto"]))
    out["xw"].sort(key=lambda e: (e["scarto"], -e["n"]))
    out["en"].sort(key=lambda e: (e["scarto"], -e["voto"]))
    return out


def nome_breve(critico):
    return CRITICI_BREVI.get(critico, critico)


def scegli_bollino(t, ap):
    """Il bollino della scheda. Priorita': critico /100 (Tannico, poi enoteche, poi Wine Enthusiast),
    poi il giudizio di Tannico, poi la media degli utenti X-Wines (almeno 10 voti).
    t = voti Tannico se l'annata e' vicina (altrimenti None), ap = voti aperti gia' filtrati.
    Restituisce dict {testo, tipo (c/t/u), n (per ordinare), anno (se diversa), fonte (per il titolo)} o None."""
    if t and t.get("critico_bollino"):
        nome, val = t["critico_bollino"]
        diversa = t["diversa"] and t["_diversa_da_peck"]
        return {"testo": f"{nome} {val}", "tipo": "c", "n": val, "anno": (t["anno"] or "altra annata") if diversa else "",
                "fonte": "Voto riportato da Tannico"}
    en100 = [e for e in ap["en"] if e["scala"] == "100"]
    if en100:
        def peso(e):
            for i, nome in enumerate(CRITICI_ORDINE):
                if e["critico"] == nome:
                    return i
            return len(CRITICI_ORDINE)
        e = sorted(en100, key=lambda e: (peso(e), e["scarto"], -e["voto"]))[0]
        etichetta = nome_breve(e["critico"]) or e["fonte"]
        return {"testo": f"{etichetta} {int(e['voto'])}", "tipo": "c", "n": int(e["voto"]),
                "anno": e["anno"] if e["diversa"] else "",
                "fonte": f"Voto riportato da {e['fonte']}" if e["fonte"] else "Voto di un’enoteca"}
    if ap["we"]:
        e = ap["we"][0]
        return {"testo": f"WE {int(e['voto'])}", "tipo": "c", "n": int(e["voto"]), "anno": e["anno"] if e["diversa"] else "",
                "fonte": "Voto di Wine Enthusiast" + (f" ({e['critico']})" if e["critico"] else "")}
    if t and t["tannico"] is not None:
        diversa = t["diversa"] and t["_diversa_da_peck"]
        return {"testo": f"Tannico {t['tannico']}", "tipo": "t", "n": t["tannico"],
                "anno": (t["anno"] or "altra annata") if diversa else "", "fonte": "Giudizio di Tannico, non di un critico"}
    if ap["xw"]:
        e = ap["xw"][0]
        return {"testo": f"Utenti {stelle_it(e['voto'])}★", "tipo": "u", "n": round(e["voto"] * 20, 1),
                "anno": e["anno"] if e["diversa"] else "",
                "fonte": f"Media dei voti degli utenti di X-Wines, {e['n']} voti, non di critici"}
    return None


def stelle_it(x, cifre=1):
    return f"{x:.{cifre}f}".replace(".", ",")


def litri_it(x):
    """0.75 -> '0,75', 1.5 -> '1,5', 3.0 -> '3' (stesso formato di litriIt in app.js)."""
    return f"{x:g}".replace(".", ",")


FORMATI_CORTI = {"Mezza bottiglia (37,5 cl)": "Mezza", "Bottiglia da 50 cl": "Piccola", "Bottiglia da 1 litro": "Litro",
                 "Rehoboam (5 L)": "Rehoboam", "Set / cassa": "Set"}


def nome_corto(nome):
    """Il nome del formato come lo scriviamo sul chip: «Magnum», «Mezza», «Bottiglia»..."""
    return FORMATI_CORTI.get(nome, nome)


def chip_formato_dopo(f):
    c = chip_formato(f) if f else ""
    return " " + c if c else ""


def chip_formato(f):
    """Il formato di una riga prezzo: «Magnum · 1,5 L». Evidenziato (chip giallo) dal magnum in su; vuoto se non si sa."""
    litri, nome = f[5], f[6]
    if not nome:
        return ""
    testo = f"{nome} · {litri_it(litri)} L" if litri is not None else nome
    classe = "fmt" + (" grande" if litri is not None and litri >= 1.5 and nome != "Set" else
                      " set" if nome == "Set" else " piccolo" if litri is not None and litri < 0.75 else
                      " solito" if litri == 0.75 else "")
    titolo = f' title="{H(f[4])}"' if f[4] else ""
    return f'<span class="{classe}"{titolo}>{H(testo)}</span>'


def costruisci_vini(box_per_nome):
    righe = leggi_csv("vini")
    tannico = carica_tannico()
    voti = carica_voti()
    voti_aperti = carica_voti_aperti()
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

    def intero(x):
        try:
            return int(float(x))
        except (TypeError, ValueError):
            return None

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
            sl = slug(r["nome"])
            if len(sl) > 50:                                              # taglia a fine parola
                sl = sl[:50].rsplit("-", 1)[0] if "-" in sl[:50] else sl[:50]
            w["d"] = f"{r['id']}-{sl}"                                    # cartella della pagina
            w["tt"] = termini_vino(r["cantina"], r["nome"])               # parole per Vivino / Wine-Searcher
            if r["id"] in tannico:                                        # scheda Tannico (altrimenti: ricerca)
                w["tn"], w["ta"], w["tf"] = tannico[r["id"]]             # url, annata diversa, formato diverso
                for k in ("ta", "tf"):
                    if not w[k]:
                        del w[k]
            v = voti.get(r["id"])
            t_ok = None                                                   # voti Tannico con annata vicina (per il bollino)
            if v and v["bollino"]:                                        # voti dalla scheda Tannico
                ap, at = r["annata"].strip(), (v["anno"] or "").strip()
                if ap.isdigit() and at.isdigit():
                    scarto = abs(int(ap) - int(at))
                    vicina = scarto <= 2 if v["diversa"] else True
                else:
                    scarto, vicina = None, (not ap and not at)            # senza annata: solo se manca da entrambe
                v["lontana"] = v["diversa"] and scarto is not None and scarto > 2
                v["_diversa_da_peck"] = v["diversa"] and at != ap
                if vicina:                                                # bollino solo se l'annata e' (quasi) la stessa
                    t_ok = v
            aperti = filtra_aperti(voti_aperti[r["id"]], r["annata"]) if r["id"] in voti_aperti else                 {"we": [], "xw": [], "en": []}
            bol = scegli_bollino(t_ok, aperti)
            if bol:
                w["vb"], w["vk"], w["vn"] = bol["testo"], bol["tipo"], bol["n"]   # testo, tipo (c/t/u), numero per ordinare
                w["vf"] = bol["fonte"]                                    # per il titolo del bollino
                if bol["anno"]:
                    w["vy"] = bol["anno"]                                 # annata del voto, se non e' quella di Peck
            if v or aperti["we"] or aperti["xw"] or aperti["en"]:
                w["voti"] = {"t": v, "we": aperti["we"], "xw": aperti["xw"], "en": aperti["en"]}   # completo: solo per la pagina
            # profilo di degustazione (0-5): [(nome, valore)] solo per quelli indicati
            prof = [(nome, intero(r.get(col))) for col, nome in ATTRIBUTI_VINO]
            prof = [(n, v) for n, v in prof if v is not None]
            w["at"] = prof
            extra = {}
            for col in ("gradazione", "temperatura_servizio", "bere_da", "bere_fino_a", "picco_da", "picco_a"):
                if r.get(col):
                    extra[col] = r[col]
            if r.get("abbinamenti"):
                extra["abbinamenti"] = [x.strip() for x in r["abbinamenti"].split(";") if x.strip()]
            w["ex"] = extra
        try:
            prezzo = float(r["prezzo_euro"]) if r["prezzo_euro"] != "" else None
        except ValueError:
            prezzo = None
        if prezzo is not None and prezzo <= 0:
            prezzo = None
        litri = float(r["litri"]) if r.get("litri") else None
        nota = "; ".join(x for x in r["nota"].split("; ") if x and not x.startswith("formato da:"))
        w["f"].append([r["variante"] or r["formato"] or "", r["formato"], prezzo,
                       1 if r["in_stock"] == "si" else 0, nota, litri, nome_corto(r.get("formato_nome", ""))])
    for w in vini.values():
        # prezzo principale: bottiglia da 0,75 L, se c'e' e ha prezzo; se no il primo prezzo.
        # I formati sono in ordine di grandezza (i calici in coda): una riga per formato.
        w["f"].sort(key=lambda f: (f[5] is None, f[5] or 0))
        bott = [f for f in w["f"] if f[5] == 0.75 and f[2] is not None]
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
    for c in cantine_ordinate:  # id leggibile e unico: e' la cartella docs/cantina/<id>/
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
    for w in lista:
        w["cantina"] = cantine_ordinate[w["c"]]
        w["paese"] = paesi[w["p"]]
        w["tipo"] = tipi[w["t"]]
    for c in cantine_ordinate:
        c["vini"] = []
    for w in lista:
        w["cantina"]["vini"].append(w)
    out = {"meta": meta, "cantine": cantine_ordinate, "vini": lista}
    return out, {"mancanti": mancanti, "senza_foto": sum(1 for w in lista if not w["ph"]),
                 "link_diversi": sum(1 for w in lista if "l" in w),
                 "con_profilo": sum(1 for w in lista if w["at"]),
                 "con_dettagli": sum(1 for w in lista if w["ex"])}


def json_vini(vini):
    """La versione compatta che il browser scarica per i filtri dell'enoteca (docs/vini.json)."""
    chiavi = ("id", "n", "a", "t", "p", "r", "c", "u", "s", "ph", "f", "pr", "d", "tt", "l", "tn", "ta", "tf", "vb", "vn", "vk", "vf", "vy")
    return {
        "meta": vini["meta"],
        "cantine": [{"id": c["id"], "nome": c["nome"], "n": c["n"]} for c in vini["cantine"]],
        "vini": [{k: w[k] for k in chiavi if k in w} for w in vini["vini"]],
    }


# ---------------------------------------------------------------------------
# Pezzi di HTML in comune
# ---------------------------------------------------------------------------

STATI_TESTO = {"certa": "certa", "probabile": "probabile", "non trovata": "non trovata",
               "peck": "Peck stessa", "nessuna": "nessuna indicazione"}
TIPI_CHIAVE = {"indirizzo": "Indirizzo", "bollo_ce": "Bollo CE", "produttore": "Produttore nominato"}
MENU = [("dispensa", "Dispensa", "dispensa/"), ("box", "Box regalo", "box/"),
        ("produttori", "Produttori", "produttori/"), ("enoteca", "Enoteca", "enoteca/"),
        ("occasioni", "Occasioni", "occasioni/"), ("prezzi", "Prezzi confrontati", "prezzi/"), ("come-funziona", "Come funziona", "come-funziona/")]
GIALLO_PECK = "#FFCD45"    # --giallo-peck nel CSS di peck.it
MARRONE_PECK = "#5E4824"   # --marrone-peck nel CSS di peck.it

FONT = ("https://fonts.googleapis.com/css2?family=Raleway:wght@400;500;600;700;800;900"
        "&family=Playfair+Display:ital,wght@1,400;1,500&display=swap")
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect "
           "width='32' height='32' fill='%23ffcd45'/%3E%3Ccircle cx='15' cy='15' r='7' fill='none' "
           "stroke='%235e4824' stroke-width='3'/%3E%3Cpath d='M20 20l6 6' stroke='%235e4824' "
           "stroke-width='3' stroke-linecap='round'/%3E%3C/svg%3E")

# Vecchi indirizzi del sito (con #/): rimandano alle pagine nuove
REDIRECT_VECCHI = (
    "(function(){var h=location.hash;if(h.indexOf('#/')!==0)return;var p=h.slice(2).split('?'),"
    "a=p[0].split('/').filter(Boolean),q=p[1]?'?'+p[1]:'',m={dispensa:'dispensa/',box:'box/',"
    "produttori:'produttori/',enoteca:'enoteca/','come-funziona':'come-funziona/'},t='';"
    "if(a[1]&&{prodotto:1,box:1,produttore:1,cantina:1}[a[0]])t=a[0]+'/'+a[1]+'/';"
    "else if(m[a[0]])t=m[a[0]]+q;if(t)location.replace(t)})();"
)
CARICA_PERSONALE = (
    "(function(){var h=location.hostname;if(h==='localhost'||h==='127.0.0.1'){"
    "var s=document.createElement('script');s.src='%sSCRIPT';document.head.appendChild(s)}})();"
)


def H(s):
    return html.escape("" if s is None else str(s), quote=True)


def cap(s):
    return s[:1].upper() + s[1:] if s else s


def num(n):
    return f"{n:,}".replace(",", ".")


def euro_it(x):
    """80 -> '80 €',  12.5 -> '12,50 €',  1250 -> '1.250 €' (stesso formato di app.js)."""
    if x is None:
        return ""
    if float(x).is_integer():
        t = f"{int(x):,}".replace(",", ".")
    else:
        t = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return t + " €"


def data_lunga(iso):
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
            "settembre", "ottobre", "novembre", "dicembre"]
    d = date.fromisoformat(iso)
    return f"{d.day} {mesi[d.month - 1]} {d.year}"


def luogo(comune, prov):
    return f"{comune} ({prov})" if comune and prov else (comune or "")


def sr_nuova_scheda():
    return '<span class="sr"> (si apre in una nuova scheda)</span>'


def ext(url, testo, classe=""):
    """Link verso un altro sito. Se il link e' marcato rotto in link_controllati.csv non si mostra."""
    if not url or not url.startswith(("http://", "https://")) or not LINK.buono(url):
        return ""
    c = f' class="{classe}"' if classe else ""
    return (f'<a{c} href="{H(url)}" target="_blank" rel="noopener noreferrer">{H(testo)}'
            f'{sr_nuova_scheda()}</a>')


def badge(stato):
    k = stato.replace(" ", "-")
    return (f'<span class="badge b-{k}" title="Quanto siamo sicuri di chi fa il prodotto">'
            f'{H(STATI_TESTO.get(stato, stato))}</span>')


SEGNAPOSTO = {
    "cibo": '<div class="segnaposto cibo" role="img" aria-label="Foto non disponibile"></div>',
    "vino": '<div class="segnaposto vino" role="img" aria-label="Foto non disponibile"></div>',
}


def foto_html(url, alt, tipo="cibo", etichetta=""):
    classe = "foto bottiglia" if tipo == "vino" else "foto"
    if not url:
        return f'<div class="{classe}">{SEGNAPOSTO[tipo]}</div>'
    img = (f'<img src="{H(url)}" alt="{H(alt)}" loading="lazy" decoding="async" '
           f'referrerpolicy="no-referrer" data-ph="{tipo}">')
    et = f'<span class="etic-foto">{H(etichetta)}</span>' if etichetta else ""
    return f'<div class="{classe}">{img}{et}</div>'


def stile_ritaglio(rt):
    """Il ritaglio con il solo CSS: la foto della box ingrandita (100/w, 100/h) e spostata sul rettangolo (x, y, w, h)."""
    w, h, x, y = rt["w"], rt["h"], rt["x"], rt["y"]
    px = x / (1 - w) * 100 if w < 1 else 0
    py = y / (1 - h) * 100 if h < 1 else 0
    return (f"background-size:{100 / w:.2f}% {100 / h:.2f}%;background-position:{px:.2f}% {py:.2f}%;"
            f"background-repeat:no-repeat")


def didascalia_ritaglio(rt, r, link=True):
    """«Dettaglio dalla foto della box «Nome»» (con il link alla pagina della box); per esclusione se la certezza e' media."""
    nome = H(rt["box_nome"])
    box = f'<a href="{r}box/{rt["box_id"]}/">{nome}</a>' if link else nome
    t = f"Dettaglio dalla foto della box «{box}»"
    if rt["certezza"] == "media":
        t += " (riconosciuto per esclusione)"
    return t


def immagine_cibo(it, r, eager=False):
    """Un ritaglio della foto della box (collegata, mai copiata) se c'e'; se no il disegno nostro (docs/disegni/)
    se il prodotto non ha una foto propria; se no la foto di Peck. Il disegno resta sotto al ritaglio: si vede
    se la foto non si carica (lo decide app.js). eager = il ritaglio e' scritto subito nella pagina
    (pagina del prodotto); altrimenti app.js lo carica solo quando e' vicino allo schermo (le foto delle box pesano 1 MB)."""
    d = it.get("disegno")
    rt = it.get("ritaglio")
    if rt and d:
        alt = f"Dettaglio dalla foto della box «{rt['box_nome']}»: {it['nome']}"
        bg = f"background-image:url({rt['url']!r});" if eager else ""
        bg = bg.replace("'", '"')
        classe = "foto disegno ritaglio-box" + (" incerta" if rt["certezza"] == "media" else "")
        corto = "Dettaglio dalla box" + (" · per esclusione" if rt["certezza"] == "media" else "")
        return (f'<div class="{classe}"><img class="sotto" src="{r}disegni/{d}.svg" width="200" height="200" alt="" '
                f'loading="lazy" decoding="async">'
                f'<div class="ritaglio" role="img" aria-label="{H(alt)}" data-src="{H(rt["url"])}" '
                f'style="{H(bg + stile_ritaglio(rt))}"></div>'
                f'<span class="etic-foto" title="{H(re.sub(r"<[^>]+>", "", didascalia_ritaglio(rt, r, False)))}">{H(corto)}</span></div>')
    if not d:
        dove = "dal servizio delivery di Peck" if it.get("foto_tipo") == "delivery" else "dal sito Peck"
        return foto_html(it["foto"], "Foto di " + it["nome"] + " " + dove)
    return (f'<div class="foto disegno"><img src="{r}disegni/{d}.svg" width="200" height="200" '
            f'alt="Disegno: {H(DISEGNI_NOMI.get(d, d))}" loading="lazy" decoding="async"></div>')


def pulsante(url, testo, classe="bottone secondario piccolo"):
    return ext(url, testo, classe)


# ---------------------------------------------------------------------------
# Pagina intera
# ---------------------------------------------------------------------------

PAGINE = []   # (percorso della cartella, ultima modifica) per la sitemap
CONTA = Counter()


def scrivi_pagina(rel, contenuto, tipo):
    """rel = 'prodotto/panettone' -> docs/prodotto/panettone/index.html ; '' -> docs/index.html"""
    p = DOCS / rel / "index.html" if rel else DOCS / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenuto, encoding="utf-8")
    PAGINE.append(rel)
    CONTA[tipo] += 1


def layout(*, titolo, descr, corpo, rel, sezione, home=False, assoluto=False):
    prof = rel.count("/") + 1 if rel else 0
    r = PREFISSO_SITO if assoluto else ("../" * prof if prof else "./")
    titolo_pagina = ("Peck Tracker – chi fa davvero quello che vende Peck" if home
                     else f"{titolo} – Peck Tracker")
    canon = URL_SITO + (rel + "/" if rel else "")
    menu = "".join(
        f'<a href="{r}{href}"' + (' aria-current="page"' if k == sezione else "") + f">{H(t)}</a>"
        for k, t, href in MENU)
    redirect = f"<script>{REDIRECT_VECCHI}</script>\n" if home else ""
    carica = CARICA_PERSONALE.replace("%s", r).replace("SCRIPT", "personale.js")
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{H(titolo_pagina)}</title>
<meta name="description" content="{H(descr)}">
<meta name="theme-color" content="{GIALLO_PECK}">
<meta name="referrer" content="no-referrer">
<link rel="canonical" href="{H(canon)}">
<link rel="icon" href="{FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONT}">
<link rel="stylesheet" href="{r}style.css">
</head>
<body data-radice="{r}">
<a class="salta" href="#principale">Vai al contenuto</a>

<p class="avviso" role="note">{H(AVVISO)}</p>

<header class="testata" id="testata">
  <div class="contenitore">
    <div class="marchio" id="marchio">
      <div class="marchio-testo">
        <p class="logo"><a href="{r}">Peck Tracker</a></p>
        <p class="sotto-logo">Chi fa davvero quello che vende Peck, e dove</p>
      </div>
    </div>
    <div class="barra">
      <a class="mini-logo" href="{r}" aria-hidden="true" tabindex="-1">Peck Tracker</a>
      <nav aria-label="Sezioni del sito" class="menu">{menu}</nav>
    </div>
  </div>
</header>

<main id="principale" tabindex="-1" class="contenitore">
{corpo}
</main>

<footer class="piede">
  <div class="contenitore">
    <p class="avviso-fondo">{H(AVVISO)}</p>
    <p>Le foto non sono nostre e non sono copiate qui: si caricano direttamente dai server di Peck (shop.peck.it e delivery.peck.it) e di Winerim, che ne restano proprietari. I nomi dei prodotti e dei vini sono quelli scritti da Peck.</p>
    <p><a href="{r}come-funziona/">Come funziona</a> · <a href="{REPO}" target="_blank" rel="noopener noreferrer">Dati e codice su GitHub{sr_nuova_scheda()}</a> · Fotografia dei dati: {data_lunga(DATA_FOTOGRAFIA)}</p>
  </div>
</footer>
<script>{carica}</script>
{redirect}<script src="{r}app.js" defer></script>
</body>
</html>
"""


def briciole(r, *voci):
    """voci: (testo, href o None). L'ultima e' la pagina corrente."""
    pezzi = []
    for i, (t, href) in enumerate(voci):
        if href is not None:
            pezzi.append(f'<a href="{r}{href}">{H(t)}</a>')
        else:
            pezzi.append(f'<span aria-current="page">{H(t)}</span>')
    return f'<nav class="briciole" aria-label="Dove sei">{" <span aria-hidden=\"true\">›</span> ".join(pezzi)}</nav>'


# ---------------------------------------------------------------------------
# Filtri e liste (il filtraggio lo fa app.js, lo stato sta nell'indirizzo: ?q=...&cat=...)
# ---------------------------------------------------------------------------

def ctl_cerca(etichetta, segnaposto):
    return (f'<div class="campo cerca"><label for="f-q">{H(etichetta)}</label>'
            f'<input type="search" id="f-q" name="q" data-modo="cerca" placeholder="{H(segnaposto)}" '
            f'autocomplete="off"></div>')


def ctl_select(nome, etichetta, opzioni, attr="", modo="eq", vuoto="Tutti", dip=""):
    """opzioni: [(valore, testo)] oppure [(valore, testo, valore_regione)]."""
    ops = ""
    for o in opzioni:
        v, t = o[0], o[1]
        x = f' data-reg="{H(o[2])}"' if len(o) > 2 and o[2] else ""
        ops += f'<option value="{H(v)}"{x}>{H(t)}</option>'
    a = f' data-attr="{attr}"' if attr else ""
    d = f' data-dip="{dip}"' if dip else ""
    return (f'<div class="campo"><label for="f-{nome}">{H(etichetta)}</label>'
            f'<select id="f-{nome}" name="{nome}" data-modo="{modo}"{a}{d}>'
            f'<option value="">{H(vuoto)}</option>{ops}</select></div>')


def ctl_spunta(nome, etichetta, attr, classe=""):
    return (f'<div class="campo spunta{(" " + classe) if classe else ""}"><input type="checkbox" id="f-{nome}" name="{nome}" value="1" '
            f'data-modo="flag" data-attr="{attr}"><label for="f-{nome}">{H(etichetta)}</label></div>')


def form_filtri(aria, cerca, campi):
    return f"""<form class="filtri" role="search" aria-label="{H(aria)}" onsubmit="return false">
{cerca}
<button type="button" class="apri-filtri" aria-expanded="false" aria-controls="altri-filtri">Filtri</button>
<div class="altri-filtri" id="altri-filtri">
<div class="riga">{campi}</div>
<button type="button" class="azzera">Azzera i filtri</button>
</div>
</form>"""


def barra_lista(conteggio):
    return f"""<div class="barra-lista">
<p class="conteggio" id="conteggio" role="status" aria-live="polite">{H(conteggio)}</p>
<div class="vista-scelta" role="group" aria-label="Come vuoi vedere l’elenco">
<a href="?" data-vista="schede" aria-current="true">Schede</a>
<a href="?vista=elenco" data-vista="elenco">Elenco</a>
</div>
</div>"""


def lista_html(intestazioni, voci, singolare, plurale, extra_attr="", foto=True):
    ints = "".join(f"<span>{H(t)}</span>" for t in intestazioni)
    vuota = "<span></span>" if foto else ""
    classe_int = "intestazione-elenco" + ("" if foto else " senza-foto")
    return f"""<div class="lista" id="lista" data-lista data-singolare="{singolare}" data-plurale="{plurale}"{extra_attr}>
<div class="{classe_int}" aria-hidden="true">{vuota}{ints}</div>
<ul class="griglia">
{voci}
</ul>
<p class="vuoto" hidden>Nessun risultato. Prova a togliere qualche filtro.</p>
</div>"""


def conta_testo(n, sing, plur):
    return f"{num(n)} {sing if n == 1 else plur}"


# ---------------------------------------------------------------------------
# Dispensa
# ---------------------------------------------------------------------------

def chi_fa(it, az):
    """(testo 'chi', 'dove', stato) per le schede."""
    o = it.get("best")
    if not o:
        return "Nessuna indicazione di dove è fatto", "", "nessuna"
    z = az.get(o["azienda"])
    sede = luogo(o["comune"] or o.get("comune_azienda") or (z and z["comune"]) or "",
                 o["provincia"] or (z and z["provincia"]) or "")
    altre = f" e altre {len(it['aziende']) - 1}" if len(it["aziende"]) > 1 else ""
    if o["stato"] == "peck":
        return "Peck stessa, in via Spadari 9", "Milano (MI)", "peck"
    if o["stato"] == "nessuna":
        return "Nessuna indicazione di dove è fatto", "", "nessuna"
    if z and z["trovata"]:
        return f"Fatto da <strong>{H(z['nome'])}</strong>{H(altre)}", sede, o["stato"]
    dove = sede or (("codice " + o["bollo"]) if o["bollo"] else (o["nominato"] or "luogo non chiaro"))
    return f"<strong>Azienda non trovata</strong>{H(altre)}", dove, o["stato"]


def prepara_cibo(dispensa, box, produttori):
    az = {z["id"]: z for z in produttori}
    # il "peck" non ha prodotti se nessuno ha sede_peck: in quel caso non c'e' in lista
    items = {d["id"]: d for d in dispensa}
    boxes = {b["id"]: b for b in box}
    ordine = ["certa", "probabile", "peck", "non trovata", "nessuna"]
    for it in dispensa:
        it["best"] = sorted(it["origini"], key=lambda o: ordine.index(o["stato"]))[0] if it["origini"] else None
        it["aziende"] = list(dict.fromkeys(o["azienda"] for o in it["origini"] if o["azienda"]))
        pezzi = [it["nome"], it["nome_originale"], it["categoria"], *it["regioni"]]
        for o in it["origini"]:
            z = az.get(o["azienda"])
            pezzi += [o["comune"], o["provincia"], o["bollo"], o["nominato"], o["frase"]]
            if z:
                pezzi += [z["nome"], z["marchio"], z["comune"]]
        it["k"] = senza_accenti(" ".join(p for p in pezzi if p)).lower()
    for z in produttori:
        z["shop"] = z["shop_online"] == "si" or LINK.buono(z["link_shop"])
        z["k"] = senza_accenti(" ".join(p for p in [z["nome"], z["ragione"], z["marchio"], z["comune"],
                                                   z["provincia"], z["regione"],
                                                   *[c["chiave"] for c in z["chiavi"]]] if p)).lower()
    for it in dispensa:
        it["shop"] = any(az[a]["shop"] for a in it["aziende"] if a in az)
    for b in box:
        b["k"] = senza_accenti(" ".join([b["nome"]] + [items[i]["nome"] + " " + items[i]["categoria"]
                                                       for i in b["elementi"]])).lower()
    return az, items, boxes


def prezzo_scheda(it):
    """La riga 'Prezzo Peck: 6 € (180 g)' sotto il nome, solo per i prodotti trovati nel delivery."""
    dv = it.get("delivery")
    if not dv:
        return ""
    return (f'<span class="prezzo-peck" title="Prezzo {H(FONTE_DELIVERY)}">'
            f'Prezzo Peck: {H(prezzo_delivery(dv))}</span>')


def blocco_prezzo(it):
    """Il prezzo nella pagina del prodotto, con la fonte e (se il formato e' un altro) la spiegazione."""
    dv = it.get("delivery")
    if not dv:
        return ""
    avviso = ""
    if dv["corrispondenza"] != "esatta":
        avviso = (f'<p class="meta">Attenzione: il formato è diverso da quello dello shop. '
                  f'{H(cap(dv["nota"]))}.</p>' if dv["nota"] else
                  '<p class="meta">Attenzione: il formato è diverso da quello dello shop.</p>')
    foto = (f" Anche la foto è del servizio delivery di Peck." if it.get("foto_tipo") == "delivery" else "")
    return (f'<div class="prezzo-pagina"><p class="prezzo-peck-grande">Prezzo Peck: '
            f'<strong>{H(prezzo_delivery(dv))}</strong></p>'
            f'<p class="meta">{H(cap(FONTE_DELIVERY))}.{foto} I prezzi cambiano; qui nessuno vende niente.</p>'
            f'{avviso}</div>')


def voce_prodotto(it, az, r):
    chi, dove, stato = chi_fa(it, az)
    regioni = "|" + "|".join(it["regioni"]) + "|"
    province = "|" + "|".join(sorted({o["provincia"] for o in it["origini"] if o["provincia"]})) + "|"
    dove_html = f'<span class="col-c">{H(dove)}</span>' if dove else '<span class="col-c"></span>'
    return (f'<li class="it" data-k="{H(it["k"])}" data-c="{H(it["categoria"])}" data-g="{H(regioni)}" '
            f'data-p="{H(province)}" data-s="{H(it["stato"])}" data-n="{1 if it["shop"] else 0}" data-cp="{1 if it.get("chip") else 0}">'
            f'<a class="scheda" href="{r}prodotto/{it["id"]}/">'
            f'{immagine_cibo(it, r)}'
            f'<div class="corpo"><div class="col-a"><span class="cat">{H(cap(it["categoria"]))}</span>'
            f'<p class="nome">{H(it["nome"])}</p>{prezzo_scheda(it)}{chip_confronto(it)}</div>'
            f'<p class="meta"><span class="col-b">{chi}</span>{dove_html}</p>'
            f'<div class="col-d">{badge(stato)}</div></div></a></li>')


def pagina_dispensa(dispensa, az, r_rel, home=False):
    r = "./" if home else "../"
    voci = "\n".join(voce_prodotto(it, az, r) for it in dispensa)
    regioni = sorted({g for it in dispensa for g in it["regioni"]}, key=lambda s: s.lower())
    prov = sorted({(o["provincia"], o["regione"]) for it in dispensa for o in it["origini"]
                   if o["provincia"] and o["regione"]})
    cats = [c for c in ORDINE_CATEGORIE if any(it["categoria"] == c for it in dispensa)]
    campi = (
        ctl_select("cat", "Categoria", [(c, cap(c)) for c in cats], "c") +
        ctl_select("reg", "Regione o paese", [(g, g) for g in regioni], "g", "multi") +
        ctl_select("prov", "Provincia", [(p, p, g) for p, g in prov], "p", "multi", "Tutte", dip="reg") +
        ctl_select("cert", "Quanto siamo sicuri", [(s, cap(STATI_TESTO[s])) for s in
                                                    ("certa", "probabile", "peck", "non trovata", "nessuna")], "s") +
        ctl_spunta("shop", "Il produttore ha uno shop online", "n") +
        ctl_spunta("cp", "Con confronto prezzi", "cp"))
    corpo = f"""<section>
<h1 class="titolo-pagina">Dispensa</h1>
<p class="intro">Ogni prodotto alimentare che Peck vende online, una volta sola anche se sta in più box. Per ognuno: chi lo fa e dove, e quanto siamo sicuri. Dove abbiamo trovato lo stesso prodotto sul sito del produttore c’è anche il confronto dei prezzi.</p>
{form_filtri("Filtri: dispensa", ctl_cerca("Cerca un prodotto, un’azienda o un paese", "per esempio: panettone, Pordenone, tartufo"), campi)}
{barra_lista(conta_testo(len(dispensa), "prodotto", "prodotti"))}
{lista_html(["Prodotto", "Chi lo fa", "Dove", "Quanto siamo sicuri"], voci, "prodotto", "prodotti")}
</section>"""
    return corpo


def azienda_riquadro_link(z):
    sito = pulsante(z["sito"], "Sito ufficiale")
    shop = pulsante(z["link_shop"], "Compra dal produttore", "bottone piccolo")
    return "".join(x for x in (sito, shop) if x)


def testo_shop(z):
    if LINK.buono(z["link_shop"]):
        return "Ha uno shop online (vedi il bottone)."
    if z["shop_online"] == "si":
        return "Ha uno shop online."
    if z["shop_online"] == "no":
        return "Sul suo sito non abbiamo trovato un negozio online (non è una prova che non esista)."
    return "Non abbiamo verificato se ha un negozio online."


def fonte_buona(fonti):
    return next((f for f in fonti if LINK.buono(f)), "")


def scheda_box_corta(b, r):
    return (f'<a class="scheda" href="{r}box/{b["id"]}/">'
            f'{foto_html(b["foto"], "Foto di " + b["nome"] + " dal sito Peck")}'
            f'<div class="corpo"><span class="cat">{"Box regalo" if b["tipo"] == "box" else "Prodotto singolo"}</span>'
            f'<p class="nome">{H(b["nome"])}</p>'
            f'<p class="meta"><span class="prezzo">{H(b["prezzo_testo"])}</span><br>'
            f'{b["n_elementi"]} {"prodotto" if b["n_elementi"] == 1 else "prodotti"}</p></div></a>')


def pagina_prodotto(it, az, boxes, r):
    blocchi = []
    for o in it["origini"]:
        z = az.get(o["azienda"])
        dl = ""

        def riga(k, v):
            nonlocal dl
            if v:
                dl += f"<dt>{H(k)}</dt><dd>{H(v)}</dd>"
        indirizzo = ", ".join(x for x in (o["indirizzo"], o["cap"], luogo(o["comune"], o["provincia"])) if x)
        if not indirizzo and o.get("comune_azienda"):
            indirizzo = (f"{o['comune_azienda']}" + (f" ({o['provincia']})" if o["provincia"] else "")
                         + " (luogo preso dall’azienda)")
        riga("Indirizzo", indirizzo)
        riga("Regione o paese", o["regione"] or o["paese"])
        riga("Bollo sanitario / codice", o["bollo"])
        riga("Produttore nominato da Peck", o["nominato"])
        etichetta = ("Come lo scrive Peck" + (f" ({o['ruolo']})" if o["ruolo"] else "")) if o["frase"] else "Origine"
        frase = (f'<blockquote class="frase">«{H(o["frase"])}»</blockquote>' if o["frase"]
                 else "<p>Nella scheda del prodotto Peck non scrive dove è fatto.</p>")
        nota = ""
        if o["nota"] and not re.search(r"nessuna frase|stessa origine", o["nota"]):
            nota = f'<p class="meta">Nota: {H(o["nota"])}</p>'
        riq = ""
        if z:
            titolo = (f'<a href="{r}produttore/{z["id"]}/">{H(z["nome"])}</a>'
                      if (z["trovata"] or z["id"] == "peck") else "Azienda non trovata")
            fonte = fonte_buona(z["fonti"])
            riq = (f'<div class="azienda-riquadro"><p class="etichetta">{"Chi lo fa" if o["stato"] == "peck" else "Chi c’è dietro"}</p>'
                   f'<h3>{titolo}</h3><p>{badge(o["stato"])}</p>'
                   + (f'<p class="meta">Marchio: {H(z["marchio"])}</p>' if z["marchio"] and z["trovata"] and z["id"] != "peck" else "")
                   + (f'<p class="meta">{H(testo_shop(z))}</p>' if z["id"] != "peck" else "")
                   + f'<div class="gruppo-bottoni">{azienda_riquadro_link(z)}</div>'
                   + (f'<p class="meta">Fonte: {ext(fonte, "dove l’abbiamo trovato")}</p>' if fonte else "")
                   + ("<details><summary>Note della ricerca</summary>" + "".join(f"<p>{H(n)}</p>" for n in z["note"]) + "</details>"
                      if z["note"] else "")
                   + "</div>")
        blocchi.append(f'<div class="origine"><p class="etichetta">{H(etichetta)}</p>{frase}'
                       + (f'<dl class="dati">{dl}</dl>' if dl else "") + nota + riq + "</div>")
    in_box = [boxes[b] for b in it["box"] if b in boxes]
    rt = it.get("ritaglio")
    if rt:
        nota_foto = ('<p class="meta">Peck non mostra una foto di questo prodotto da solo: questo è un ingrandimento della foto della box '
                     '(collegata dal sito di Peck, non copiata). Se non si carica, resta il nostro disegno.</p>')
        didascalia = (f'<p class="meta didascalia-ritaglio">{didascalia_ritaglio(rt, r)}'
                      + (f'. <span class="nota-r">{H(cap(rt["nota"]))}.</span>' if rt["certezza"] == "media" and rt["nota"] else "")
                      + "</p>")
    else:
        nota_foto = ('<p class="meta">Peck non mostra una foto di questo prodotto da solo: il disegno è nostro.</p>'
                     if it["disegno"] else "")
        didascalia = ""
    vedi_foto = ""
    if it["disegno"] and any(boxes[b]["foto"] for b in it["box"] if b in boxes):
        testo = ("Vedi la foto della box che lo contiene" if len(in_box) == 1
                 else "Vedi la foto delle box che lo contengono")
        vedi_foto = f'<p class="meta vedi-foto"><a href="#box">{testo}</a></p>'
    piu = ('<span class="meta"> Peck indica più di un luogo: sono tutti qui sotto.</span>' if len(it["origini"]) > 1 else "")
    chi, dove, stato = chi_fa(it, az)
    corpo = f"""{briciole(r, ("Dispensa", "dispensa/"), (it["nome"], None))}
<article>
<div class="dettaglio">
<div class="colonna-foto">{immagine_cibo(it, r, eager=True)}{didascalia}{vedi_foto}</div>
<div>
<p class="etichetta">{H(cap(it["categoria"]))}</p>
<h1>{H(it["nome"])}</h1>
<p class="originale">Nome su Peck: {H(it["nome_originale"])}</p>
{blocco_prezzo(it)}
{nota_foto}
<p>{badge(it["stato"])} {piu}</p>
</div>
</div>
<section class="sezione"><h2>Chi lo fa e dove</h2>
{"".join(blocchi) if blocchi else "<p>Nessuna indicazione.</p>"}
</section>
{blocco_storia(it, az, r)}
{blocco_confronto(it, az)}
{blocco_alternative(it)}
<section class="sezione" id="box"><h2>{"Dove lo trovi su Peck" if len(in_box) == 1 else f"Lo trovi in {len(in_box)} pagine di Peck"}</h2>
<ul class="griglia">{"".join(f"<li>{scheda_box_corta(b, r)}</li>" for b in in_box)}</ul>
<p class="meta" style="margin-top:1rem">Le pagine qui sopra sono le nostre; da ognuna puoi andare alla pagina originale di Peck.</p>
</section>
</article>"""
    sede = f" {dove}." if dove else ""
    descr = re.sub(r"<[^>]+>", "", f"{it['nome']}: {chi}.{sede} {AVVISO}")
    return corpo, descr


# ---------------------------------------------------------------------------
# Box regalo
# ---------------------------------------------------------------------------

def pagina_box_lista(box, items):
    ord_nome = {b["id"]: i for i, b in enumerate(sorted(box, key=lambda b: nz(b["nome"])))}
    voci = []
    for b in box:
        tipo = "Box regalo" if b["tipo"] == "box" else "Prodotto singolo"
        voci.append(
            f'<li class="it" data-k="{H(b["k"])}" data-t="{H(b["tipo"])}" data-o-nome="{ord_nome[b["id"]]}" '
            f'data-o-prezzo="{b["prezzo"] if b["prezzo"] is not None else 0}" data-o-n="{b["n_elementi"]}">'
            f'<a class="scheda" href="../box/{b["id"]}/">{foto_html(b["foto"], "Foto di " + b["nome"] + " dal sito Peck")}'
            f'<div class="corpo"><div class="col-a"><span class="cat">{tipo}</span><p class="nome">{H(b["nome"])}</p></div>'
            f'<p class="meta"><span class="col-b">{b["n_elementi"]} {"prodotto" if b["n_elementi"] == 1 else "prodotti"}</span>'
            f'<span class="col-c prezzo">{H(b["prezzo_testo"])}</span></p>'
            f'<div class="col-d"><span class="meta">{tipo}</span></div></div></a></li>')
    campi = (ctl_select("ord", "Ordina", [("prezzo-su", "Prezzo: dal più basso"), ("prezzo-giu", "Prezzo: dal più alto"),
                                          ("n", "Più prodotti")], modo="ord", vuoto="Nome") +
             ctl_select("tipo", "Tipo", [("box", "Box regalo"), ("singolo", "Prodotto singolo")], "t"))
    return f"""<section>
<h1 class="titolo-pagina">Box regalo</h1>
<p class="intro">Le {len(box)} pagine dello shop di Peck: box regalo e qualche prodotto singolo (panettoni, pandoro, salmone). Aprine una per vederla “spacchettata”: ogni prodotto con chi lo fa.</p>
{form_filtri("Filtri: box regalo", ctl_cerca("Cerca una box", "per esempio: Krug, tartufo, caffè"), campi)}
{barra_lista(conta_testo(len(box), "pagina", "pagine"))}
{lista_html(["Box", "Quanti prodotti", "Prezzo", "Tipo"], chr(10).join(voci), "pagina", "pagine")}
</section>"""


def pagina_box(b, items, az, r, bv=None):
    its = [items[i] for i in b["elementi"] if i in items]
    con_azienda = sum(1 for i in its if i["stato"] in ("certa", "probabile"))
    righe = []
    for it in its:
        chi, dove, stato = chi_fa(it, az)
        righe.append(f'<li><a class="riga-el" href="{r}prodotto/{it["id"]}/">'
                     f'<span><span class="cat">{H(cap(it["categoria"]))}</span><br><span class="nome">{H(it["nome"])}</span></span>'
                     f'<span class="meta">{chi}{(" · " + H(dove)) if dove else ""}</span>{badge(stato)}</a></li>')
    tipo = "Box regalo" if b["tipo"] == "box" else "Prodotto singolo"
    corpo = f"""{briciole(r, ("Box regalo", "box/"), (b["nome"], None))}
<article>
<div class="dettaglio">
{foto_html(b["foto"], "Foto di " + b["nome"] + " dal sito Peck")}
<div>
<p class="etichetta">{tipo}</p>
<h1>{H(b["nome"])}</h1>
<p><span class="prezzo">{H(b["prezzo_testo"])}</span><span class="meta"> · prezzo scritto da Peck, il giorno della fotografia dei dati</span></p>
<p>{len(its)} {"prodotto" if len(its) == 1 else "prodotti"}; per {con_azienda} abbiamo trovato l’azienda (certa o probabile).</p>
<div class="gruppo-bottoni">{ext(b["url"], "Vedi la pagina su Peck", "bottone secondario piccolo")}</div>
<p class="meta">Su questo sito non si compra niente: il link porta alla pagina originale di Peck.</p>
</div>
</div>
<section class="sezione"><h2>La box spacchettata</h2>
<ul class="righe">{"".join(righe)}</ul>
</section>
{blocco_valore(b, bv, items, r)}
</article>"""
    descr = f"{b['nome']} ({b['prezzo_testo']}): i {len(its)} prodotti della pagina Peck con chi li fa e dove. {AVVISO}"
    return corpo, descr


# ---------------------------------------------------------------------------
# Produttori
# ---------------------------------------------------------------------------

def pagina_produttori_lista(produttori):
    voci = []
    for z in produttori:
        dove = luogo(z["comune"], z["provincia"]) or z["paese"] or "sede non indicata"
        reg = f" · {z['regione']}" if z["regione"] and z["regione"] != z["paese"] else ""
        marchio = f"Marchio: {z['marchio']}" if z["marchio"] and z["trovata"] else ""
        n = len(z["prodotti"])
        per_peck = f"Per Peck: {n} {'prodotto' if n == 1 else 'prodotti'}" if n else "Fuori dallo shop del 2026"
        shop = ' <span class="badge b-shop">shop online</span>' if z["shop"] else ""
        voci.append(
            f'<li class="it" data-k="{H(z["k"])}" data-s="{H(z["certezza"])}" data-g="|{H(z["regione"])}|" '
            f'data-n="{1 if z["shop"] else 0}">'
            f'<a class="scheda azienda" href="../produttore/{z["id"]}/"><div class="corpo">'
            f'<div class="col-a"><p class="nome">{H(z["nome"] if z["trovata"] else "Azienda non trovata")}</p>'
            f'<p class="meta">{H(marchio)}</p></div>'
            f'<p class="meta"><span class="col-b">{per_peck}</span>'
            f'<span class="col-c">{H(dove)}{H(reg)}</span></p>'
            f'<div class="col-d">{badge(z["certezza"])}{shop}</div></div></a></li>')
    regioni = sorted({z["regione"] for z in produttori if z["regione"]}, key=str.lower)
    campi = (ctl_select("cert", "Quanto siamo sicuri", [(s, cap(STATI_TESTO[s])) for s in
                                                        ("certa", "probabile", "peck", "non trovata")], "s") +
             ctl_select("reg", "Regione o paese", [(g, g) for g in regioni], "g", "multi") +
             ctl_spunta("shop", "Ha uno shop online", "n"))
    return f"""<section>
<h1 class="titolo-pagina">Produttori</h1>
<p class="intro">Le aziende dietro i prodotti. Una scheda per azienda (o per indirizzo, se non siamo riusciti a risalire a chi sia). Molte fanno il prodotto che Peck poi vende con il suo nome.</p>
{form_filtri("Filtri: produttori", ctl_cerca("Cerca un’azienda, un comune o un marchio", "per esempio: Follador, Norcia, pasta"), campi)}
{barra_lista(conta_testo(len(produttori), "produttore", "produttori"))}
{lista_html(["Azienda", "Per Peck", "Dove", "Quanto siamo sicuri"], chr(10).join(voci), "produttore", "produttori", " data-classe=\"larga\"", foto=False)}
</section>"""


def pagina_produttore(z, items, az, r):
    prod = sorted((items[i] for i in z["prodotti"] if i in items), key=lambda x: nz(x["nome"]))
    dove = luogo(z["comune"], z["provincia"])
    chiavi = ""
    for c in z["chiavi"]:
        fonte = ext(c["fonte"], "fonte") if c["fonte"] else ""
        chiavi += (f"<li><strong>{H(TIPI_CHIAVE.get(c['tipo'], c['tipo']))}</strong>: {H(c['chiave'])} "
                   f"{badge(c['certezza'])}{(' · ' + fonte) if fonte else ''}</li>")
    altre = ""
    if len(z["fonti"]) > 1 or (len(z["fonti"]) == 1 and not any(c["fonte"] for c in z["chiavi"])):
        altre = '<p class="meta">Altre fonti: ' + " ".join(ext(f, "fonte") for f in z["fonti"]) + "</p>"
    note = ("<details><summary>Note della ricerca</summary>" + "".join(f"<p>{H(n)}</p>" for n in z["note"]) + "</details>"
            if z["note"] else "")
    dove_txt = " · ".join(x for x in [dove, z["regione"] if z["regione"] and z["regione"] != z["paese"] else "",
                                      z["paese"] if z["paese"] and z["paese"] != "Italia" else ""] if x)
    nome = z["nome"] if (z["trovata"] or z["id"] == "peck") else "Azienda non trovata"
    ragione = (f'<p class="originale">Come risulta nei registri: {H(z["ragione"])}</p>'
               if z["ragione"] and z["ragione"] != z["nome"] and z["trovata"] else "")
    dl = ""
    if z["marchio"] and z["id"] != "peck":
        dl += f"<dt>Marchio</dt><dd>{H(z['marchio'])}</dd>"
    dl += f"<dt>Dove</dt><dd>{H(dove_txt) if (dove or z['paese']) else 'sede non indicata nei dati di Peck'}</dd>"
    if z["id"] != "peck":
        dl += f"<dt>Negozio online</dt><dd>{H(testo_shop(z))}</dd>"
    righe = "".join(
        f'<li><a class="riga-el" href="{r}prodotto/{it["id"]}/"><span><span class="cat">{H(cap(it["categoria"]))}</span><br>'
        f'<span class="nome">{H(it["nome"])}</span></span><span class="meta">'
        f'{"in 1 pagina di Peck" if len(it["box"]) == 1 else f"in {len(it["box"])} pagine di Peck"}</span></a></li>'
        for it in prod)
    trovata = ""
    if z["chiavi"]:
        trovata = f'<section class="sezione"><h2>Come l’abbiamo trovata</h2><ul>{chiavi}</ul>{altre}{note}</section>'
    elif note:
        trovata = note
    if z.get("fuori"):
        voci_t = "".join(f"<li>{H(t)}</li>" for t in z.get("prodotti_testo") or [])
        sezione_prodotti = ('<section class="sezione"><h2>Fuori dallo shop online del 2026</h2>'
                            '<p>Nello shop online di Peck, nella fotografia del ' + data_lunga(DATA_FOTOGRAFIA) + ', non c’è nessun prodotto che risulti fatto da questa azienda. '
                            'La abbiamo trovata in una fotografia di una data passata (vedi sotto), nel servizio delivery di Peck o in un secondo giro di ricerche.</p>'
                            + (f'<p class="meta">Prodotti collegati, come li scrive la ricerca:</p><ul>{voci_t}</ul>' if voci_t else "") + "</section>")
    else:
        sezione_prodotti = (f'<section class="sezione"><h2>Cosa fa per Peck ({len(prod)})</h2>'
                            f'<ul class="righe">{righe}</ul></section>')
    sezione_prezzi = ""
    if z.get("n_conf"):
        sezione_prezzi = (f'<section class="sezione"><h2>Prezzi confrontati</h2><p>Abbiamo {z["n_conf"]} '
                          f'{"confronto" if z["n_conf"] == 1 else "confronti"} di prezzo con i prodotti di questa azienda: '
                          f'<a href="{r}prezzi/?q={quote(z["nome"])}">vedili in Prezzi confrontati</a>.</p></section>')
    corpo = f"""{briciole(r, ("Produttori", "produttori/"), (nome, None))}
<article>
<p class="etichetta">{"Peck stessa" if z["id"] == "peck" else "Produttore"}</p>
<h1>{H(nome)}</h1>
{ragione}
<p>{badge(z["certezza"])} {'<span class="badge b-shop">shop online</span>' if z["shop"] else ""}</p>
<dl class="dati">{dl}</dl>
<div class="gruppo-bottoni">{azienda_riquadro_link(z)}</div>
{trovata}
{sezione_prodotti}
{blocco_osservazioni(z, az, r)}
{sezione_prezzi}
</article>"""
    descr = (f"{nome}" + (f", {dove_txt}" if dove_txt else "") + (f": fa {len(prod)} "
             f"{'prodotto' if len(prod) == 1 else 'prodotti'} venduti da Peck." if prod else ": oggi non ha prodotti nello shop online di Peck.") + " Quanto siamo sicuri: "
             f"{STATI_TESTO.get(z['certezza'], z['certezza'])}. {AVVISO}")
    return corpo, descr


# ---------------------------------------------------------------------------
# Enoteca: lista, cantine, vini
# ---------------------------------------------------------------------------

def tipo_chip(t):
    cl = re.sub(r"[^a-z]+", "-", t)
    return f'<span class="tipo tipo-{cl}">{H("liquoroso" if t == "liquoroso/fortificato" else t)}</span>'


def bottoni_punteggi(w, classe="bottone secondario piccolo"):
    return (f'<a class="{classe}" href="{H(url_vivino(w["tt"]))}" target="_blank" rel="noopener noreferrer">'
            f'Vivino{sr_nuova_scheda()}</a>'
            f'<a class="{classe}" href="{H(url_wine_searcher(w["tt"], w["a"]))}" target="_blank" rel="noopener noreferrer">'
            f'Wine-Searcher{sr_nuova_scheda()}</a>'
            + bottone_tannico(w, classe))


def bottone_tannico(w, classe):
    if "tn" in w:
        a = f'<a class="{classe}" href="{H(w["tn"])}" target="_blank" rel="noopener noreferrer">Tannico{sr_nuova_scheda()}</a>'
        if "tf" in w:   # Tannico ha solo un altro formato (per esempio la 0,75 L per un magnum)
            a += (f'<span class="nota-tannico meta">su Tannico c’è la {H(w["tf"])}'
                  + (f', annata {H(w["ta"])}' if "ta" in w else "") + '</span>')
        elif "ta" in w:
            a += f'<span class="nota-tannico meta">su Tannico c’è l’annata {H(w["ta"])}</span>'
        return a
    return (f'<a class="{classe}" href="{H(url_tannico_ricerca(w["tt"]))}" target="_blank" rel="noopener noreferrer">'
            f'Cerca su Tannico{sr_nuova_scheda()}</a>')


def badge_voto(w):
    """Bollino piccolo con il voto migliore (es. «Parker 96», «WE 92», «Utenti 4,2★» o, per un'altra annata,
    «WE 92 · 2019»). Critici, Tannico e utenti hanno colori diversi (classe vk-c / vk-t / vk-u).
    Stessa logica di votoBadge() in app.js."""
    if "vb" not in w:
        return ""
    testo = w["vb"] + (f" · {w['vy']}" if w.get("vy") else "")
    tit = w["vf"] + (f" per l’annata {w['vy']}, non quella di Peck" if w.get("vy") else "")
    return f' <span class="voto-badge vk-{w["vk"]}" title="{H(tit)}">{H(testo)}</span>'


def nota_annata_voto(e, w):
    """«annata 2019 (in carta: 2020)» se l'annata del voto non e' quella di Peck, altrimenti vuoto."""
    if not e.get("diversa"):
        return ""
    return f' <span class="meta">· annata {H(e["anno"])} (in carta: {H(w["a"] or "senza annata")})</span>'


def riga_voto(fonte, valore, extra=""):
    return f'<li><span class="fonte">{fonte}</span><span>{valore}{extra}</span></li>'


def blocco_voti(w):
    v = w.get("voti")
    if not v:
        return ""
    t = v["t"]
    # --- Critici ---
    crit, fonti = "", []
    if t:
        for nome, valore, scala in t["critici"]:
            if scala.isdigit():
                val = f"<strong>{H(valore)}</strong>/{H(scala)}"
            else:
                val = f"<strong>{H(valore)}</strong>" + (f" {H(scala)}" if scala else "")
            nota = (f' <span class="meta">· annata {H(t["anno"] or "diversa")} (in carta: {H(w["a"] or "senza annata")})</span>'
                    if t.get("_diversa_da_peck") else "")
            crit += riga_voto(H(nome), val, nota + ' <span class="meta">· via Tannico</span>')
    for e in v["en"]:
        scala = e["scala"] or "100"
        punti = f"{e['voto']:g}".replace(".", ",")
        val = f"<strong>{H(punti)}</strong>/{H(scala)}"
        fonte = H(e["critico"] or e["fonte"])
        via = (f'<a href="{H(e["url"])}" target="_blank" rel="noopener noreferrer">{H(e["fonte"])}{sr_nuova_scheda()}</a>'
               if e["url"] else H(e["fonte"]))
        crit += riga_voto(fonte, val, nota_annata_voto(e, w) + f' <span class="meta">· via {via}</span>')
    for e in v["we"]:
        crit += riga_voto("Wine Enthusiast", f"<strong>{int(e['voto'])}</strong>/100",
                          (f' <span class="meta">· {H(e["critico"])}</span>' if e["critico"] else "") + nota_annata_voto(e, w))
    sezioni = ""
    if crit:
        sezioni += f'<h3>Critici</h3><ul class="voti">{crit}</ul>'
    # --- Tannico ---
    if t and t["tannico"] is not None:
        sezioni += (f'<h3>Tannico</h3><ul class="voti">'
                    + riga_voto("Giudizio di Tannico", f'<strong>{t["tannico"]}</strong>/100',
                                nota_annata_voto({"diversa": t.get("_diversa_da_peck"), "anno": t["anno"] or "diversa"}, w))
                    + '</ul><p class="meta">È il punteggio che Tannico dà ai suoi prodotti: non è il voto di un critico.</p>')
    # --- Utenti ---
    if v["xw"]:
        e = v["xw"][0]
        sezioni += ('<h3>Utenti (X-Wines)</h3><ul class="voti">'
                    + riga_voto("Media degli utenti", f"<strong>{stelle_it(e['voto'], 2)}</strong> su 5",
                                f' <span class="meta">· {num(e["n"])} voti</span>' + nota_annata_voto(e, w))
                    + '</ul><p class="meta">Media dei voti a stelle (da 1 a 5) lasciati da utenti di siti di vino: non sono voti di critici.</p>')
    avviso = ""
    if t and t.get("lontana"):
        avviso = (f'<p class="avviso-annata"><strong>Voti di Tannico dell’annata {H(t["anno"])}</strong>, lontana da quella in carta '
                  f'({H(w["a"])}): li riportiamo solo come riferimento sul vino, non sulla bottiglia.</p>')
    elif t and t["diversa"] and t.get("_diversa_da_peck"):
        anno = t["anno"] or "un’altra annata"
        avviso = (f'<p class="avviso-annata"><strong>Voti di Tannico dell’annata {H(anno)}</strong> '
                  f'(su Peck c’è la {H(w["a"] or "senza annata")}): non sono i voti della bottiglia della carta.</p>')
    # --- Fonti e licenze ---
    if t:
        fonti.append(f'Tannico: voti e critici come li riporta la scheda del prodotto, raccolti il {data_lunga(t["data"])}; '
                     f'non sono nostri. <a href="{H(t["url"])}" target="_blank" rel="noopener noreferrer">Vedi la scheda su Tannico{sr_nuova_scheda()}</a>.')
    if v["we"]:
        fonti.append('Wine Enthusiast: punteggi dalla raccolta «Wine Reviews» di Zack Thoutt (Kaggle), '
                     'licenza <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener noreferrer">'
                     f'CC BY-NC-SA 4.0{sr_nuova_scheda()}</a> (uso non commerciale, stessa licenza). Riportiamo il punteggio e il nome '
                     'di chi ha degustato, mai il testo della recensione.')
    if v["en"]:
        nomi = sorted({e["fonte"] for e in v["en"] if e["fonte"]})
        fonti.append(f'{H(", ".join(nomi) or "Enoteche")}: punteggi di critici come li riporta la scheda del negozio '
                     '(il link porta lì); non sono nostri, non copiamo il testo delle recensioni.')
    if v["xw"]:
        fonti.append('X-Wines: dataset di ricerca di de Azambuja, Morais e Filipe (2023), licenza '
                     '<a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank" rel="noopener noreferrer">'
                     f'CC0{sr_nuova_scheda()}</a>; <a href="{XW_DOI}" target="_blank" rel="noopener noreferrer">doi 10.3390/bdcc7010020'
                     f'{sr_nuova_scheda()}</a>. I voti sono quelli di utenti raccolti sul web nel 2022; gli autori non dicono da quale sito.')
    return (f'<section class="sezione" id="voti"><h2>Voti</h2>{avviso}{sezioni}'
            f'<ul class="fonti meta">' + "".join(f"<li>{f}</li>" for f in fonti) + '</ul></section>')


def url_foto_vino(w):
    if not w["ph"]:
        return ""
    return w["ph"] if w["ph"].startswith("http") else FOTO_WINERIM_PREFISSO + w["ph"]


def scheda_vino(w, r):
    """Scheda di una bottiglia (stessa struttura di quella che disegna app.js nell'elenco dell'enoteca)."""
    pagina = f"{r}vino/{w['d']}/"
    c = w["cantina"]
    formati = [f for f in w["f"] if f[2] is not None]
    principale = next((f for f in formati if f[5] == 0.75), formati[0] if formati else None)
    altri = [f for f in formati if f is not principale]
    prezzo = (euro_it(w["pr"]) + chip_formato_dopo(principale)) if w["pr"] is not None else '<span class="meta">Prezzo non indicato</span>'
    elenco = ""
    if altri:
        elenco = '<ul class="formati">' + "".join(
            f"<li>{chip_formato(f) or H(cap(f[0] or f[1]))} {euro_it(f[2])}</li>" for f in altri) + "</ul>"
    return (f'<article class="scheda vino">'
            f'{foto_html(url_foto_vino(w), "Bottiglia: " + w["n"] + (" " + w["a"] if w["a"] else ""), "vino")}'
            f'<div class="corpo"><div class="col-a"><p class="tipo-riga">{tipo_chip(w["tipo"])}'
            f'{(" <span class=meta>· " + H(w["a"]) + "</span>") if w["a"] else ""}{badge_voto(w)}</p>'
            f'<h3 class="nome"><a class="vai" href="{pagina}">{H(w["n"])}</a></h3></div>'
            f'<p class="meta"><span class="col-b"><a href="{r}cantina/{c["id"]}/">{H(c["nome"])}</a></span>'
            f'<span class="col-c">{H(" · ".join(x for x in (w["r"], w["paese"]) if x))}</span></p>'
            f'<div class="col-d"><p class="prezzo">{prezzo}</p>{elenco}</div>'
            f'<div class="bottoni">{bottoni_punteggi(w)}</div></div></article>')


def pagina_enoteca(V):
    M = V["meta"]
    regs = sorted({(p, rg) for p, rg in M["regioni"]}, key=lambda x: x[1].lower())
    campi = (
        ctl_select("tipo", "Tipo", [(t, cap(t)) for t in M["tipi"]]) +
        ctl_select("paese", "Paese", [(p, p) for p in M["paesi"]]) +
        ctl_select("reg", "Regione", [(rg, rg, p) for p, rg in regs], "", "eq", "Tutte", dip="paese") +
        '<div class="campo"><label for="f-can">Cantina</label><input type="text" id="f-can" name="can" '
        'list="lista-cantine" placeholder="scrivi il nome" autocomplete="off"><datalist id="lista-cantine"></datalist></div>'
        '<div class="campo"><label for="f-pmin">Prezzo da (€)</label><input type="number" id="f-pmin" name="pmin" '
        'min="0" step="1" inputmode="numeric" placeholder="da"></div>'
        '<div class="campo"><label for="f-pmax">Prezzo fino a (€)</label><input type="number" id="f-pmax" name="pmax" '
        'min="0" step="1" inputmode="numeric" placeholder="fino a"></div>' +
        ctl_select("fmt", "Formato", [("bottiglia", "Bottiglia 0,75 L"), ("piccoli", "Mezza e piccoli (sotto 0,75 L)"),
                                      ("litro", "Bottiglia da 1 litro"), ("magnum", "Magnum 1,5 L"),
                                      ("grandi", "Grandi formati (3 L e oltre)"), ("set", "Set e casse")], vuoto="Tutti i formati") +
        ctl_spunta("tan", "Su Tannico", "") +
        ctl_spunta("voto", "Con voto", "") +
        ctl_spunta("crit", "solo critici", "", "sotto") +
        ctl_select("ord", "Ordina", [("prezzo-su", "Prezzo: dal più basso"), ("prezzo-giu", "Prezzo: dal più alto"),
                                     ("litro-su", "Prezzo al litro: dal più basso"),
                                     ("annata-giu", "Annata: dalla più recente"), ("annata-su", "Annata: dalla più vecchia"),
                                     ("voto-giu", "Voto: dal più alto")],
                   modo="ord", vuoto="Nome"))
    cantine = "".join(f'<li><a href="../cantina/{c["id"]}/">{H(c["nome"])}</a> <span class="meta">({c["n"]})</span></li>'
                      for c in V["cantine"])
    return f"""<section>
<h1 class="titolo-pagina">Enoteca</h1>
<p class="intro">{num(M["n_vini"])} vini della carta dell’enoteca di Peck, di {M["n_cantine"]} cantine. Accanto al prezzo c’è sempre il formato (Bottiglia, Magnum, Jeroboam…) con i litri. Ogni vino ha la sua pagina, con il profilo di degustazione; per la scheda completa c’è il link all’enoteca (Winerim). I prezzi sono quelli della fotografia del {data_lunga(M["data"])}.</p>
{form_filtri("Filtri: enoteca", ctl_cerca("Cerca un vino, un’uva o una cantina", "per esempio: Barolo, Nebbiolo, Gaja"), campi)}
{barra_lista(conta_testo(M["n_vini"], "vino", "vini"))}
<p class="meta nota-ord" id="nota-ord" hidden>Ordinati per prezzo a parità di formato: prima le bottiglie da 0,75 L, poi gli altri formati (dal più piccolo al più grande), ciascuno dal prezzo che hai scelto. Con il filtro «Formato» vedi un formato solo.</p>
<p class="meta nota-ord" id="nota-voto" hidden>Ordine per voto senza mischiare le scale: prima i vini con il voto di un critico (su 100), poi quelli con il solo giudizio di Tannico (su 100), poi quelli con la sola media degli utenti (stelle da 1 a 5, moltiplicate per 20 solo per metterle in ordine tra loro; il bollino mostra sempre le stelle). Un punteggio di utenti non è confrontabile con quello di un critico.</p>
<div class="lista" id="lista" data-enoteca data-json="../vini.json" data-singolare="vino" data-plurale="vini">
<div class="intestazione-elenco" aria-hidden="true"><span></span><span>Vino</span><span>Cantina</span><span>Dove</span><span>Prezzo</span></div>
<ul class="griglia"></ul>
<p class="vuoto" hidden>Nessun risultato. Prova a togliere qualche filtro.</p>
<p class="caricamento">Carico i vini…</p>
<button type="button" class="bottone secondario altri" hidden>Mostra altri</button>
</div>
<noscript><p class="meta">Per cercare fra i vini serve JavaScript. Senza, puoi scorrere l’elenco delle cantine qui sotto: ogni cantina ha la sua pagina con tutte le etichette.</p></noscript>
<details class="elenco-cantine" id="cantine"><summary>Tutte le cantine, in ordine alfabetico ({M["n_cantine"]})</summary>
<ul class="colonne">{cantine}</ul>
</details>
</section>""", f"""I {num(M["n_vini"])} vini della carta dell’enoteca di Peck: cerca per tipo, paese, regione, cantina, formato e prezzo. {AVVISO}"""


def pagina_cantina(c, boxes, r):
    vini = sorted(c["vini"], key=lambda w: nz(w["n"]) + str(w["a"]))
    tipi = [(t, n) for t, n in c["tipi"].items() if n > 0]
    tipi_html = "<p>" + " · ".join(f"{tipo_chip(t)} {n}" for t, n in tipi) + "</p>" if tipi else ""
    prezzi = ""
    if c["pmin"] is not None:
        txt = euro_it(c["pmin"]) if c["pmin"] == c["pmax"] else f"{euro_it(c['pmin'])} – {euro_it(c['pmax'])}"
        prezzi = f"<div><b>{txt}</b>prezzi in carta</div>"
    in_box = [boxes[b] for b in c["box"] if b in boxes]
    box_html = ""
    if in_box:
        box_html = ('<section class="sezione"><h2>Compare anche nelle box regalo</h2><ul class="griglia">'
                    + "".join(f"<li>{scheda_box_corta(b, r)}</li>" for b in in_box) + "</ul></section>")
    corpo = f"""{briciole(r, ("Enoteca", "enoteca/"), (c["nome"], None))}
<article>
<p class="etichetta">Cantina</p>
<h1>{H(c["nome"])}</h1>
<p class="meta">{H(" · ".join(x for x in (c["paese"], c["regioni"]) if x))}</p>
<div class="stat"><div><b>{c["n"]}</b>{"etichetta in carta" if c["n"] == 1 else "etichette in carta"}</div>{prezzi}</div>
{tipi_html}
{('<p class="meta">Nota: ' + H(c["nota"]) + "</p>") if c["nota"] else ""}
{box_html}
<section class="sezione"><h2>Tutte le etichette ({len(vini)})</h2>
<p class="meta">I bottoni Vivino, Wine-Searcher e Tannico aprono la scheda o una ricerca sui loro siti. Il bollino con un voto può essere di un critico («Parker 96», «WE 92»), il giudizio di Tannico («Tannico 92») o la media degli utenti («Utenti 4,2★»): tre cose diverse, con colori diversi. Se l’annata è diversa da quella di Peck c’è scritto anche l’anno. Da dove vengono i voti: «Come funziona».</p>
<ul class="griglia">{"".join(f"<li>{scheda_vino(w, r)}</li>" for w in vini)}</ul>
</section>
</article>"""
    descr = (f"{c['nome']}" + (f" ({c['paese']})" if c["paese"] else "") + f": {c['n']} "
             f"{'etichetta' if c['n'] == 1 else 'etichette'} nella carta dell’enoteca di Peck. {AVVISO}")
    return corpo, descr


def punti(v):
    return "●" * v + "○" * (5 - v)


def radar_svg(prof):
    n = len(prof)
    cx, cy, R = 100, 88, 56

    def pt(i, v, extra=0):
        a = math.radians(-90 + i * 360 / n)
        rr = R * v / 5 + extra
        return cx + rr * math.cos(a), cy + rr * math.sin(a)
    anelli = "".join(
        '<polygon class="anello" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, k) for i in range(n))) + '"/>'
        for k in range(1, 6))
    assi = "".join(f'<line class="asse" x1="{cx}" y1="{cy}" x2="{pt(i, 5)[0]:.1f}" y2="{pt(i, 5)[1]:.1f}"/>' for i in range(n))
    area = '<polygon class="area" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i, (_, v) in enumerate(prof))) + '"/>'
    etich = ""
    for i, (nome, _) in enumerate(prof):
        x, y = pt(i, 5, 11)
        co = math.cos(math.radians(-90 + i * 360 / n))
        anc = "middle" if abs(co) < 0.3 else ("start" if co > 0 else "end")
        etich += f'<text x="{x:.1f}" y="{y + 3:.1f}" text-anchor="{anc}">{H(nome)}</text>'
    return (f'<svg class="radar" viewBox="-25 0 250 176" aria-hidden="true" focusable="false">{anelli}{assi}{area}{etich}</svg>')


def pagina_vino(w, V, r, correlati, CV):
    c = w["cantina"]
    M = V["meta"]
    link_winerim = w.get("l") or f"{LINK_WINERIM_PREFISSO}{w['id']}/{w['s']}"
    nome_completo = w["n"] + (f" {w['a']}" if w["a"] and w["a"] not in w["n"] else "")
    # profilo
    profilo = ""
    if w["at"]:
        righe = "".join(f'<li><span class="attr">{H(n)}</span><span class="punti" aria-hidden="true">{punti(v)}</span>'
                        f'<span class="sr">{v} su 5</span></li>' for n, v in w["at"])
        radar = radar_svg(w["at"]) if len(w["at"]) >= 3 else ""
        profilo = (f'<section class="sezione"><h2>Profilo di degustazione</h2>'
                   f'<div class="profilo"><ul class="attributi">{righe}</ul>{radar}</div>'
                   f'<p class="meta">Da 0 a 5, come li indica la scheda dell’enoteca (Winerim): sono giudizi suoi, non nostri.</p></section>')
    # formati
    con_nota = any(f[4] for f in w["f"])
    righe_f = ""
    for f in w["f"]:
        nome_f = H(f[6]) if f[6] else H(cap(f[0] or f[1] or "Formato non indicato"))
        litri_f = f"{litri_it(f[5])} L" if f[5] is not None else "non indicato"
        righe_f += (f"<tr><td>{nome_f}</td><td>{litri_f}</td>"
                    f"<td>{euro_it(f[2]) if f[2] is not None else 'non indicato'}</td>"
                    f"<td>{'disponibile' if f[3] else 'non disponibile'}</td>"
                    + (f"<td>{H(f[4])}</td>" if con_nota else "") + "</tr>")
    formati = (f'<section class="sezione"><h2>Formati e prezzi</h2><div class="tab-scorri"><table class="tab">'
               f'<thead><tr><th>Formato</th><th>Litri</th><th>Prezzo</th><th>Nella carta</th>' + ('<th>Nota</th>' if con_nota else '') + '</tr></thead>'
               f'<tbody>{righe_f}</tbody></table></div>'
               f'<p class="meta">Prezzi e disponibilità del {data_lunga(M["data"])}: nella carta dell’enoteca possono essere cambiati. '
               f'I litri vengono dalla capacità indicata da Winerim o, se c’è, dal formato scritto nel nome del vino; '
               f'il nome del formato cambia da regione a regione (3 litri sono un Jeroboam in Champagne e un Doppio Magnum a Bordeaux), i litri no.</p></section>')
    # dettagli
    ex = w["ex"]
    dl = ""
    if ex.get("gradazione"):
        dl += f"<dt>Gradazione</dt><dd>{H(ex['gradazione'].replace('.', ','))}% vol.</dd>"
    if ex.get("temperatura_servizio"):
        dl += f"<dt>Temperatura di servizio</dt><dd>{H(re.sub(r'\\s*°?C$', '', ex['temperatura_servizio']))} °C</dd>"
    if ex.get("bere_da") or ex.get("bere_fino_a"):
        dl += f"<dt>Da bere</dt><dd>{H(ex.get('bere_da', '?'))} – {H(ex.get('bere_fino_a', '?'))}</dd>"
    if ex.get("picco_da") or ex.get("picco_a"):
        dl += f"<dt>Al suo meglio</dt><dd>{H(ex.get('picco_da', '?'))} – {H(ex.get('picco_a', '?'))}</dd>"
    if ex.get("abbinamenti"):
        dl += f"<dt>Abbinamenti</dt><dd>{H(', '.join(ex['abbinamenti']))}</dd>"
    dettagli = ""
    if dl:
        dettagli = (f'<section class="sezione"><h2>Altri dati della scheda</h2><dl class="dati">{dl}</dl>'
                    f'<p class="meta">Sono indicazioni di massima scritte dalla scheda dell’enoteca, non lette dall’etichetta: '
                    f'per molti vini sono uguali (per esempio la stessa gradazione).</p></section>')
    uve = f"<dt>Uve</dt><dd>{H(', '.join(w['u']))}</dd>" if w["u"] else ""
    formati_p = [f for f in w["f"] if f[2] is not None]
    principale = next((f for f in formati_p if f[5] == 0.75), formati_p[0] if formati_p else None)
    prezzo = euro_it(w["pr"]) if w["pr"] is not None else "prezzo non indicato"
    prezzo_html = prezzo + chip_formato_dopo(principale) if w["pr"] is not None else prezzo
    if principale and principale[5] not in (None, 0.75):   # nella descrizione: il formato, se non è la bottiglia
        prezzo = f"{prezzo} ({principale[6]} {litri_it(principale[5])} L)"
    stock = "disponibile" if any(f[3] for f in w["f"]) else "non disponibile"
    # correlati
    corr = ""
    if correlati:
        corr = ('<section class="sezione"><h2>Vini correlati</h2><ul class="griglia">'
                + "".join(f"<li>{scheda_vino(x, r)}</li>" for x in correlati) + "</ul></section>")
    corpo = f"""{briciole(r, ("Enoteca", "enoteca/"), (c["nome"], f"cantina/{c['id']}/"), (w["n"], None))}
<article>
<div class="dettaglio">
{foto_html(url_foto_vino(w), "Bottiglia: " + nome_completo, "vino")}
<div>
<p>{tipo_chip(w["tipo"])}{(" <span class=meta>· " + H(w["a"]) + "</span>") if w["a"] else ""}{badge_voto(w)}</p>
<h1>{H(w["n"])}</h1>
<p class="originale"><a href="{r}cantina/{c["id"]}/">{H(c["nome"])}</a> · {H(" · ".join(x for x in (w["r"], w["paese"]) if x))}</p>
<dl class="dati">{uve}<dt>Prezzo</dt><dd><span class="prezzo">{prezzo_html}</span> · {stock}</dd></dl>
<div class="gruppo-bottoni">{bottoni_punteggi(w)}
<a class="bottone piccolo" href="{H(link_winerim)}" target="_blank" rel="noopener noreferrer">Scheda completa in enoteca{sr_nuova_scheda()}</a></div>
<p class="meta">Vivino e Wine-Searcher aprono una ricerca sui loro siti per questo vino, Tannico la scheda o una ricerca. Di Vivino e Wine-Searcher non copiamo i voti.</p>
</div>
</div>
{confronto_vino(w, CV)}
{blocco_voti(w)}
{profilo}
{formati}
{dettagli}
{corr}
</article>"""
    descr = (f"{nome_completo}: {w['tipo']}" + (f", {w['r']}" if w["r"] else "") + f", {w['paese']}. Cantina {c['nome']}. "
             f"Prezzo nella carta dell’enoteca di Peck: {prezzo}. {AVVISO}")
    return corpo, descr, nome_nome(w)


def nome_nome(w):
    return w["n"] + (f" {w['a']}" if w["a"] and w["a"] not in w["n"] else "")


def vini_correlati(vini):
    """Per ogni vino: fino a 3 della stessa cantina + fino a 3 della stessa regione e tipo (altra cantina)."""
    per_cantina = defaultdict(list)
    per_zona = defaultdict(list)
    for w in vini:
        per_cantina[w["c"]].append(w)
        per_zona[(w["p"], w["r"], w["t"])].append(w)

    def vicino(w, x):
        pw, px = w["pr"], x["pr"]
        dp = abs(pw - px) if pw is not None and px is not None else 1e9
        try:
            da = abs(int(w["a"]) - int(x["a"]))
        except ValueError:
            da = 99
        return (dp, da, x["id"])
    out = {}
    for w in vini:
        stessa = sorted((x for x in per_cantina[w["c"]] if x is not w), key=lambda x: (vicino(w, x)[1], vicino(w, x)[0], x["id"]))[:3]
        zona = sorted((x for x in per_zona[(w["p"], w["r"], w["t"])] if x["c"] != w["c"]), key=lambda x: vicino(w, x))[:3]
        out[w["id"]] = stessa + zona
    return out


# ---------------------------------------------------------------------------
# Confronto prezzi: Peck / produttore (cibo) e Peck / Tannico (vini)
#   cibo:  data/confronto/risultati_*.csv  (tutti, letti dinamicamente)
#   vini:  data/confronto/vini_tannico.csv (scritto da src/confronto_vini.py)
# ---------------------------------------------------------------------------

SOGLIA_OCCASIONE = 5.0       # «Angolo delle occasioni»: Peck costa meno che altrove, o al massimo il 5% in piu'
N_COSTA_DI_PIU = 20          # quante righe nel riquadro «Dove Peck costa di piu'»
SIM_PESO = {"stesso prodotto": 3, "molto simile": 2, "simile": 1, "non verificato": 0}   # «non trovato»: mai
SIM_BREVE = {"stesso prodotto": "Stesso prodotto", "molto simile": "Molto simile", "simile": "Simile",
             "non verificato": "Da verificare a mano"}
SIM_CLASSE = {"stesso prodotto": "stesso", "molto simile": "molto", "simile": "simile", "non verificato": "mano"}
SIM_SPIEGA = {
    "stesso prodotto": "Stesso produttore, stesso tipo di prodotto e stesso formato, con ingredienti uguali o quasi.",
    "molto simile": "Stesso produttore e stesso tipo di prodotto, ma il formato o la ricetta sono un po’ diversi "
                    "(la nota qui sotto dice come).",
    "simile": "Stesso produttore, ma un prodotto della stessa famiglia e non lo stesso: il confronto è solo indicativo.",
}
SOLO_BOX = "Da Peck si trova solo nelle box: non c’è un prezzo del prodotto singolo da confrontare."
A_MANO = "Confronto da fare a mano: il sito del produttore non accetta agenti automatici."
DATA_CONFRONTO_DEFAULT = "2026-10-25"


def num_conf(s):
    """'+21.7' -> 21.7,  '37.93 (al litro)' -> 37.93,  '' -> None."""
    m = re.search(r"[-+−]?\d+(?:[.,]\d+)?", s or "")
    if not m:
        return None
    try:
        return float(m.group().replace("−", "-").replace(",", "."))
    except ValueError:
        return None


def unita_di(formato):
    """'litro' se il formato e' in ml/cl/l, altrimenti 'kg'."""
    f = (formato or "").lower()
    if re.search(r"\d\s*(ml|cl|lt|l)\b", f) and not re.search(r"\d\s*(g|gr|kg)\b", f):
        return "litro"
    return "kg"


def percento_testo(dp):
    a = abs(dp)
    if a >= 10:
        return str(round(a))
    return f"{a:.1f}".replace(".", ",").removesuffix(",0")


def verdetto(dp):
    """'Da Peck costa il 72% in più' / 'l’8% in meno' / 'lo stesso'."""
    if dp is None:
        return ""
    if abs(dp) < 0.5:
        return "Da Peck costa praticamente lo stesso"
    p = percento_testo(dp)
    art = "l’" if p[0] == "8" or p == "11" else "il "
    return f"Da Peck costa {art}{p}% in {'più' if dp > 0 else 'meno'}"


def chip_testo(dp):
    if abs(dp) < 0.5:
        return "≈ pari al produttore"
    return f"{'+' if dp > 0 else '−'}{percento_testo(dp)}% vs produttore"


def carica_confronti_cibo():
    """Tutte le righe di data/confronto/risultati_*.csv, tranne «non trovato» (non si mostra mai)."""
    out = []
    for f in sorted(glob.glob(str(DATI / "confronto" / "risultati_*.csv"))):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                sim = (r.get("somiglianza") or "").strip().lower()
                if sim not in SIM_PESO:
                    continue
                c = {
                    "nome_peck": (r["nome_peck"] or "").strip(), "chiave": (r["chiave_dispensa"] or "").strip(),
                    "p_peck": num_conf(r["prezzo_peck"]), "f_peck": (r["formato_peck"] or "").strip(),
                    "kg_peck": num_conf(r["prezzo_peck_al_kg"]),
                    "azienda": (r["azienda"] or "").strip(), "nome_prod": (r["nome_produttore"] or "").strip(),
                    "url": (r["url_produttore"] or "").strip(),
                    "p_prod": num_conf(r["prezzo_produttore"]), "f_prod": (r["formato_produttore"] or "").strip(),
                    "kg_prod": num_conf(r["prezzo_produttore_al_kg"]),
                    "dp": num_conf(r["differenza_pct"]), "sim": sim,
                    "ingr": (r["ingredienti_confrontati"] or "").strip().lower() == "si",
                    "data": (r["data"] or DATA_CONFRONTO_DEFAULT).strip(), "nota": (r["nota"] or "").strip(),
                    "ordine": len(out), "item": None,
                    "cod": (r.get("cod_art_delivery") or "").strip(), "nome_delivery": (r.get("nome_delivery") or "").strip(),
                    "file": Path(f).name,
                }
                if sim == "non verificato":
                    c["p_peck"] = c["p_prod"] = c["dp"] = None     # nessun prezzo del produttore: niente da confrontare
                if c["dp"] is None and c["kg_peck"] and c["kg_prod"]:
                    c["dp"] = (c["kg_peck"] / c["kg_prod"] - 1) * 100
                if c["dp"] is None and c["p_peck"] and c["p_prod"]:
                    c["dp"] = (c["p_peck"] / c["p_prod"] - 1) * 100
                # su che base e' calcolata la differenza (controlliamo che i numeri tornino)
                c["base"] = ""
                if c["dp"] is not None:
                    if c["kg_peck"] and c["kg_prod"] and abs((c["kg_peck"] / c["kg_prod"] - 1) * 100 - c["dp"]) <= 0.6:
                        u1, u2 = unita_di(c["f_peck"]), unita_di(c["f_prod"])
                        c["base"] = f"al {u1}" if u1 == u2 else "al kg o al litro"
                    elif c["p_peck"] and c["p_prod"] and abs((c["p_peck"] / c["p_prod"] - 1) * 100 - c["dp"]) <= 0.6:
                        c["base"] = "per confezione"
                c["confrontabile"] = c["dp"] is not None and c["p_peck"] is not None and c["p_prod"] is not None
                out.append(c)
    return out


def collega_confronti(dispensa, az):
    """Attacca a ogni prodotto della Dispensa i suoi confronti (prima per chiave_dispensa, poi per nome).
    Le righe senza una pagina sulla Dispensa restano in 'senza_pagina'."""
    righe = carica_confronti_cibo()
    per_id = {d["id"]: d for d in dispensa}
    per_nome = {nz(d["nome_originale"]): d for d in dispensa}
    for d in dispensa:
        d["confronti"], d["chip"] = [], None
    for c in righe:
        c["item"] = per_id.get(c["chiave"]) or per_nome.get(nz(c["nome_peck"]))
        if c["item"]:
            c["item"]["confronti"].append(c)
    for d in dispensa:
        d["confronti"].sort(key=lambda c: (-SIM_PESO[c["sim"]], c["ordine"]))
        d["chip"] = next((c for c in d["confronti"] if SIM_PESO[c["sim"]] >= 2 and c["confrontabile"]), None)
    return righe


def sito_produttore(c, az):
    """Link al sito (o shop) del produttore, per le righe «da verificare a mano» che non hanno un indirizzo."""
    k = nz(c["azienda"])
    cand = None
    for z in az.values():
        if z["trovata"] and k and k in (nz(z["ragione"]), nz(z["nome"])):
            cand = z
            break
    if cand is None and c["item"]:
        cand = next((az[a] for a in c["item"]["aziende"] if a in az and az[a]["trovata"]), None)
    if cand is None:
        return ""
    return cand["link_shop"] if LINK.buono(cand["link_shop"]) else cand["sito"]


def prezzo_formato(prezzo, formato):
    if prezzo is None:
        return ""
    formato = re.sub(r"\s*\(([^)]*)\)", r", \1", formato or "").strip()   # niente parentesi dentro la parentesi
    return euro_it(prezzo) + (f' <span class="meta">({H(formato)})</span>' if formato else "")


def al_kg_testo(valore, formato):
    if not valore:
        return ""
    return f'<span class="meta">{euro_it(valore)} al {unita_di(formato)}</span>'


def blocco_confronto(it, az):
    """Il riquadro «Dal produttore» nella pagina di un prodotto."""
    confronti = it.get("confronti") or []
    if not confronti:
        return ""
    schede = []
    for c in confronti:
        sim = c["sim"]
        classe = SIM_CLASSE[sim]
        badge_sim = f'<span class="badge-sim s-{classe}">{H(SIM_BREVE[sim])}</span>'
        if sim == "non verificato":
            link = ext(sito_produttore(c, az), "Vai al sito del produttore", "bottone piccolo")
            schede.append(
                f'<div class="confronto s-{classe}"><p>{badge_sim}</p>'
                f'<h3>{H(c["azienda"])}</h3>'
                f'<p>{H(A_MANO)}</p>'
                + (f'<div class="gruppo-bottoni">{link}</div>' if link else "") + '</div>')
            continue
        # i due prezzi
        lato_peck = ""
        if c["p_peck"] is not None:
            lato_peck = (f'<div class="lato"><p class="et">Da Peck</p><p class="cifra">{prezzo_formato(c["p_peck"], c["f_peck"])}</p>'
                         f'<p>{al_kg_testo(c["kg_peck"], c["f_peck"])}</p></div>')
        lato_prod = ""
        if c["p_prod"] is not None:
            lato_prod = (f'<div class="lato"><p class="et">Dal produttore</p><p class="cifra">{prezzo_formato(c["p_prod"], c["f_prod"])}</p>'
                         f'<p>{al_kg_testo(c["kg_prod"], c["f_prod"])}</p></div>')
        prezzi = f'<div class="conf-prezzi">{lato_peck}{lato_prod}</div>' if (lato_peck or lato_prod) else ""
        if c["p_peck"] is None and c["p_prod"] is not None:
            esito = f'<p class="conf-solo-box">{H(SOLO_BOX)}</p>'
        elif c["confrontabile"]:
            dp = c["dp"]
            segno = "pari" if abs(dp) < 0.5 else ("piu" if dp > 0 else "meno")
            base = f' <span class="meta">({H(c["base"])})</span>' if c["base"] else ""
            esito = f'<p class="conf-verdetto v-{segno}">{H(verdetto(dp))}{base}</p>'
        else:
            esito = ""
        ingr = ('<p class="conf-ingr"><span class="spunta-ok" aria-hidden="true">✓</span> Ingredienti confrontati</p>'
                if c["ingr"] else '<p class="conf-ingr meta">Ingredienti non confrontati.</p>')
        link = ext(c["url"], "Compra dal produttore", "bottone piccolo")
        attenzione = ""
        if re.search(r"offerta|saldi|promozion", c["nota"], re.I):
            attenzione += '<p class="meta attenzione">Attenzione: il prezzo del produttore è in offerta (vedi le note del confronto).</p>'
        if re.search(r"risulta non disponibile|non disponibile online|contattare per acquistare", c["nota"], re.I):
            attenzione += ('<p class="meta attenzione">Attenzione: sul sito del produttore il prodotto potrebbe non essere '
                           'acquistabile online (vedi le note del confronto).</p>')
        nota = (f'<details><summary>Note del confronto</summary><p>{H(c["nota"])}</p></details>' if c["nota"] else "")
        nome_prod = c["nome_prod"] or it["nome"]
        schede.append(
            f'<div class="confronto s-{classe}"><p>{badge_sim}</p>'
            f'<h3>{H(nome_prod)}</h3><p class="meta">{H(c["azienda"])}</p>'
            f'<p class="conf-spiega">{H(SIM_SPIEGA[sim])}</p>'
            f'{prezzi}{esito}{ingr}{attenzione}'
            f'<div class="gruppo-bottoni">{link}</div>'
            f'<p class="meta">Prezzo visto il {data_lunga(c["data"])}.</p>{nota}</div>')
    return (f'<section class="sezione" id="dal-produttore"><h2>Dal produttore</h2>'
            f'<p class="meta">Lo stesso prodotto (o uno simile) sul sito di chi lo fa. Sono i prezzi scritti sui siti il giorno indicato, '
            f'spese di spedizione escluse; cambiano. Il dettaglio è in «Come funziona». Qui nessuno vende niente.</p>'
            + "".join(schede) + '</section>')


def chip_confronto(it):
    c = it.get("chip")
    if not c:
        return ""
    dp = c["dp"]
    classe = "pari" if abs(dp) < 0.5 else ("piu" if dp > 0 else "meno")
    tit = f"{verdetto(dp)} ({c['base'] or 'confronto'}) rispetto a {c['azienda']}: {SIM_BREVE[c['sim']].lower()}"
    return f' <span class="chip-conf c-{classe}" title="{H(tit)}">{H(chip_testo(dp))}</span>'


def litri_testo(x):
    return f"{litri_it(x)} L" if x is not None else ""


# --- vini ------------------------------------------------------------------
# Un «gruppo» = una bottiglia della carta di Peck in un formato (id vino + litri) con tutte le offerte confrontabili
# di altri negozi: Tannico (vini_tannico.csv) e le enoteche Callmewine, Millesima, Xtrawine (vini_enoteche_prezzi.csv).

ENOTECHE_CONFRONTO = ("Callmewine", "Millesima", "Xtrawine")
NOTE_NEGOZI = {
    "Millesima": "Millesima: prezzo del sito francese (IVA inclusa per la consegna in Francia, può cambiare per l’Italia).",
}


def ann_norm(a):
    a = (a or "").strip().upper()
    return "" if a in ("", "NV", "S.A.") else a


def carica_offerte_vini():
    """{id vino (testo): [gruppo, ...]}, un gruppo per formato di Peck, con le offerte confrontabili (confrontabile = si)."""
    gruppi = {}

    def prendi(r, litri_peck, a_peck, p_peck, pl_peck):
        if p_peck is None or not litri_peck:
            return None
        k = (r["id"], f"{litri_peck:g}")
        g = gruppi.get(k)
        if g is None:
            g = gruppi[k] = {"id": r["id"], "litri": litri_peck, "a_peck": (a_peck or "").strip(), "p_peck": p_peck,
                             "pl_peck": pl_peck or p_peck / litri_peck, "offerte": []}
        return g

    def aggiungi(g, o):
        if o["pl"] is None or o["p"] is None:
            return
        dp = (g["pl_peck"] / o["pl"] - 1) * 100 if o["pl"] else o["dp"]
        if dp is None:
            return
        o["dp"] = dp
        g["offerte"].append(o)

    f = DATI / "confronto" / "vini_tannico.csv"
    if f.exists():
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r["confrontabile"] or "").strip().lower() != "si":
                    continue
                g = prendi(r, num_conf(r["litri_peck"]), r["annata_peck"], num_conf(r["prezzo_peck"]), num_conf(r["prezzo_peck_al_litro"]))
                if g:
                    aggiungi(g, {"fonte": "Tannico", "tipo": "t", "url": (r["url_tannico"] or "").strip(),
                                 "a": (r["annata_tannico"] or "").strip(), "l": num_conf(r["litri_tannico"]),
                                 "p": num_conf(r["prezzo_tannico"]), "pl": num_conf(r["prezzo_tannico_al_litro"]),
                                 "dp": num_conf(r["differenza_pct"]),
                                 "disp": (r["disponibile_tannico"] or "").strip().lower() == "si",
                                 "data": (r["data"] or DATA_CONFRONTO_DEFAULT).strip(), "nota": (r["nota"] or "").strip()})
    f = DATI / "confronto" / "vini_enoteche_prezzi.csv"
    if f.exists():
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["retailer"] not in ENOTECHE_CONFRONTO or (r["confrontabile"] or "").strip().lower() != "si":
                    continue
                g = prendi(r, num_conf(r["litri_peck"]), r["annata_peck"], num_conf(r["prezzo_peck"]), num_conf(r["prezzo_peck_al_litro"]))
                if g:
                    aggiungi(g, {"fonte": r["retailer"], "tipo": "e", "url": (r["url"] or "").strip(),
                                 "a": (r["annata_fonte"] or "").strip(), "l": num_conf(r["litri_fonte"]),
                                 "p": num_conf(r["prezzo_fonte_eur_bottiglia"]), "pl": num_conf(r["prezzo_al_litro"]),
                                 "dp": num_conf(r["differenza_pct"]),
                                 "disp": (r["disponibile"] or "").strip().lower() == "si",
                                 "data": (r["data_pagina"] or DATA_CONFRONTO_DEFAULT).strip(), "nota": (r["nota"] or "").strip()})
    out = defaultdict(list)
    for g in gruppi.values():
        if not g["offerte"]:
            continue
        for o in g["offerte"]:
            o["stessa"] = ann_norm(o["a"]) == ann_norm(g["a_peck"])
        g["offerte"].sort(key=lambda o: (not o["disp"], not o["stessa"], o["pl"]))
        g["rif"] = riferimento(g, False)
        g["rif_stock"] = riferimento(g, True)
        out[g["id"]].append(g)
    for lst in out.values():
        lst.sort(key=lambda g: g["litri"])
    return dict(out)


def riferimento(g, solo_disponibili):
    """L'offerta con cui si confronta Peck: fra quelle in vendita (se ce ne sono; con solo_disponibili solo quelle),
    prima la stessa annata di Peck, poi il prezzo al litro piu' basso."""
    pool = [o for o in g["offerte"] if o["disp"]]
    if not pool and not solo_disponibili:
        pool = list(g["offerte"])
    if not pool:
        return None
    stessa = [o for o in pool if o["stessa"]]
    return min(stessa or pool, key=lambda o: o["pl"])


def classe_diff(dp):
    """Colore della differenza: verde se Peck costa meno (oltre il 5%), neutro entro il ±5%, caldo se costa di piu'."""
    if dp < -SOGLIA_OCCASIONE:
        return "meno"
    return "pari" if dp <= SOGLIA_OCCASIONE else "piu"


def barra_diff(dp):
    """Barra centrata sullo zero (scala ±100%): verde a sinistra se Peck costa meno, calda a destra se costa di piu'."""
    larg = min(abs(dp), 100) / 2
    pos = "dx" if dp > 0 else "sx"
    return (f'<span class="barra-diff d-{classe_diff(dp)}" role="img" aria-label="{H(verdetto(dp) or "")}">'
            f'<span class="riempi {pos}" style="width:{larg:.1f}%"></span></span>')


def etichetta_annata_offerta(o, a_peck):
    if o["stessa"]:
        return ""
    return (f'<span class="chip-annata" title="Annata diversa da quella di Peck ({H(a_peck or "senza annata")})">'
            f'annata {H(o["a"] or "?")}</span>')


def confronto_vino(w, CV):
    """Il riquadro «Prezzi altrove» nella pagina di un vino: tutte le offerte confrontabili (Tannico, Callmewine,
    Millesima, Xtrawine), per formato di Peck."""
    gruppi = CV.get(str(w["id"]))
    if not gruppi:
        return ""
    blocchi = []
    note_negozi = set()
    for g in gruppi:
        ref = g["rif"]
        dp = ref["dp"]
        stessa = ref["stessa"]
        formato = f'<h3>Bottiglia da {litri_testo(g["litri"])}</h3>' if len(gruppi) > 1 or g["litri"] != 0.75 else ""
        peck = (f'<div class="lato"><p class="et">Da Peck</p><p class="cifra">{euro_it(g["p_peck"])} '
                f'<span class="meta">({litri_testo(g["litri"])})</span></p>'
                f'<p><span class="meta">{euro_it(g["pl_peck"])} al litro</span></p></div>')
        righe = ""
        for o in g["offerte"]:
            if o["fonte"] in NOTE_NEGOZI:
                note_negozi.add(NOTE_NEGOZI[o["fonte"]])
            nd = "" if o["disp"] else ' <span class="chip-nd">non disponibile</span>'
            link = ext(o["url"], f"Vedi su {o['fonte']}", "bottone piccolo")
            righe += (f'<li class="offerta{"" if o["disp"] else " nd"}"><div class="of-chi"><strong>{H(o["fonte"])}</strong> '
                      f'{etichetta_annata_offerta(o, g["a_peck"])}{nd}</div>'
                      f'<div class="of-prezzo">{euro_it(o["p"])} <span class="meta">({litri_testo(o["l"])}) · {euro_it(o["pl"])} al litro</span></div>'
                      f'<div class="of-diff v-{classe_diff(o["dp"])}">{H(pct_segno(o["dp"]))}</div>'
                      f'<div class="of-link">{link}</div></li>')
        nome_rif = ref["fonte"] + ("" if stessa else f", annata {ref['a'] or '?'}")
        avviso = ""
        if not ref["disp"]:
            avviso = ('<p class="conf-ingr meta">Oggi nessuno di questi negozi ha la bottiglia in vendita: i prezzi sono gli ultimi che '
                      'abbiamo visto sulle loro schede.</p>')
        annata = ("" if stessa else f'<p class="meta">Annata: da Peck {H(g["a_peck"] or "senza annata")}, da {H(ref["fonte"])} {H(ref["a"] or "?")} '
                                   f'(vicine, ma non la stessa).</p>')
        cl = "stesso" if stessa else "molto"
        blocchi.append(
            f'<div class="confronto s-{cl}">{formato}'
            f'<p><span class="badge-sim s-{cl}">{"Stesso vino, stesso formato" if stessa else "Stesso vino, annata vicina"}</span></p>'
            f'<div class="conf-prezzi">{peck}</div>'
            f'<ul class="offerte">{righe}</ul>'
            f'<p class="conf-verdetto v-{classe_diff(dp)}">{H(verdetto(dp))} <span class="meta">(al litro, rispetto a {H(nome_rif)})</span></p>'
            f'{annata}{avviso}</div>')
    data = max(o["data"] for g in gruppi for o in g["offerte"])
    nomi = sorted({o["fonte"] for g in gruppi for o in g["offerte"]})
    return (f'<section class="sezione" id="prezzi-altrove"><h2>Prezzi altrove</h2>'
            + "".join(blocchi)
            + f'<p class="meta">Prezzi visti il {data_lunga(data)}, con IVA, divisi per i litri; cambiano. '
              f'{H(", ".join(nomi))}: negozi online di vino, non affiliati a questo sito. Il confronto vale solo quando il vino e il formato '
              f'sono gli stessi e l’annata dista al massimo 2 anni; per ogni bottiglia ci si confronta con l’offerta più bassa '
              f'(a parità di annata, se c’è) fra i negozi che la vendono. {H(" ".join(sorted(note_negozi)))} '
              f'Altri dettagli in «<a href="../../come-funziona/#confronto-prezzi">Come funziona</a>».</p></section>')


# --- alternative da un altro produttore (data/confronto/alternative_7.csv) -------------------------------

def carica_alternative(dispensa):
    """Stessa ricetta venduta da un ALTRO produttore (non quello di Peck). Mai «stesso prodotto», mai nelle occasioni."""
    f = DATI / "confronto" / "alternative_7.csv"
    if not f.exists():
        return []
    per_cod = {}
    if (DATI / "delivery_dispensa.csv").exists():
        per_cod = {r["cod_art"]: r["chiave_dispensa"] for r in leggi_csv("delivery_dispensa")}
    per_id = {d["id"]: d for d in dispensa}
    per_nome = {nz(d["nome_originale"]): d for d in dispensa}
    out = []
    with open(f, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("stesso_produttore") or "").strip().lower() != "no":
                continue
            a = {
                "nome_peck": (r["nome_peck"] or "").strip(), "p_peck": num_conf(r["prezzo_peck"]), "f_peck": (r["formato_peck"] or "").strip(),
                "kg_peck": num_conf(r["prezzo_peck_al_kg"]), "azienda": (r["azienda_alternativa"] or "").strip(),
                "nome_alt": (r["nome_alternativa"] or "").strip(), "url": (r["url_alternativa"] or "").strip(),
                "p_alt": num_conf(r["prezzo_alternativa"]), "f_alt": (r["formato_alternativa"] or "").strip(),
                "kg_alt": num_conf(r["prezzo_alternativa_al_kg"]), "dp": num_conf(r["differenza_pct"]),
                "ricetta": (r["ricetta"] or "").strip().lower(), "prod_peck": (r["produttore_peck"] or "").strip(),
                "data": (r["data"] or DATA_CONFRONTO_DEFAULT).strip(), "nota": (r["nota"] or "").strip(),
                "cod": (r["cod_art_delivery"] or "").strip(),
            }
            if a["dp"] is None and a["kg_peck"] and a["kg_alt"]:
                a["dp"] = (a["kg_peck"] / a["kg_alt"] - 1) * 100
            if a["dp"] is None or a["p_peck"] is None or a["p_alt"] is None:
                continue
            a["item"] = per_id.get(per_cod.get(a["cod"], "")) or per_nome.get(nz(a["nome_peck"]))
            if a["item"]:
                a["item"].setdefault("alternative", []).append(a)
            out.append(a)
    return out


RICETTA_TESTO = {"identica": "Ricetta identica", "molto simile": "Ricetta molto simile", "simile": "Ricetta simile"}


def base_alt(a):
    return "al kg o al litro" if unita_di(a["f_peck"]) != unita_di(a["f_alt"]) else f"al {unita_di(a['f_peck'])}"


def blocco_alternative(it):
    alt = it.get("alternative") or []
    if not alt:
        return ""
    schede = []
    for a in alt:
        peck_chi = f' ({H(a["prod_peck"])})' if a["prod_peck"] else ""
        schede.append(
            f'<div class="confronto s-simile alternativa"><p><span class="badge-sim s-simile">Un altro produttore</span> '
            f'<span class="badge-sim s-mano">{H(RICETTA_TESTO.get(a["ricetta"], "Ricetta " + a["ricetta"]))}</span></p>'
            f'<h3>{H(a["nome_alt"])}</h3><p class="meta">{H(a["azienda"])}</p>'
            f'<p class="conf-spiega">Non è chi lo fa per Peck{peck_chi}: è un’altra azienda che vende una ricetta simile con il proprio nome. '
            f'Non è lo stesso prodotto.</p>'
            f'<div class="conf-prezzi"><div class="lato"><p class="et">Da Peck</p><p class="cifra">{prezzo_formato(a["p_peck"], a["f_peck"])}</p><p>{al_kg_testo(a["kg_peck"], a["f_peck"])}</p></div>'
            f'<div class="lato"><p class="et">Dall’altro produttore</p><p class="cifra">{prezzo_formato(a["p_alt"], a["f_alt"])}</p><p>{al_kg_testo(a["kg_alt"], a["f_alt"])}</p></div></div>'
            f'<p class="conf-verdetto v-{classe_diff(a["dp"])}">{H(verdetto(a["dp"]))} <span class="meta">({base_alt(a)})</span></p>'
            f'<div class="gruppo-bottoni">{ext(a["url"], "Vedi sul sito", "bottone piccolo")}</div>'
            f'<p class="meta">Prezzo visto il {data_lunga(a["data"])}.</p>'
            + (f'<details><summary>Note del confronto</summary><p>{H(a["nota"])}</p></details>' if a["nota"] else "")
            + '</div>')
    return ('<section class="sezione" id="alternativa"><h2>Un’alternativa da un altro produttore</h2>'
            '<p class="meta">Qui non si parla di chi fa il prodotto per Peck, ma di un’altra azienda che vende qualcosa di simile: '
            'serve solo come riferimento di prezzo e non entra nell’Angolo delle occasioni.</p>' + "".join(schede) + "</section>")


# --- tutti i confronti in un'unica lista (per /occasioni/ e /prezzi/) --------------------------------------

SRC_PRODUTTORE, SRC_TANNICO, SRC_ENOTECHE, SRC_ALTRO = 1, 2, 4, 8
GRUPPI_VINO = [
    ("v-rosso-italia", "Vino rosso · Italia"), ("v-rosso-francia", "Vino rosso · Francia"),
    ("v-rosso-altri", "Vino rosso · altri paesi"), ("v-bianco-italia", "Vino bianco · Italia"),
    ("v-bianco-francia", "Vino bianco · Francia"), ("v-bianco-altri", "Vino bianco · altri paesi"),
    ("v-spumante-francia", "Spumanti e Champagne · Francia"), ("v-spumante-italia", "Spumanti · Italia"),
    ("v-spumante-altri", "Spumanti · altri paesi"), ("v-altri", "Rosati, dolci e liquorosi"),
]


def gruppo_vino(w):
    t, p = w["tipo"], w["paese"]
    sfx = {"Italia": "italia", "Francia": "francia"}.get(p, "altri")
    if t in ("rosso", "bianco", "spumante"):
        return f"v-{t}-{sfx}"
    return "v-altri"


def mediana(v):
    v = sorted(v)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


_FOTO_LOCALE = None


def foto_delivery_per_nome(nome):
    """URL pubblico della foto di un prodotto del delivery che non e' nella Dispensa (per le righe di «Prezzi confrontati»).
    Serve il catalogo salvato in data/locale/ (resta sul computer: l'URL e' pubblico, il catalogo no); senza, niente foto."""
    global _FOTO_LOCALE
    if _FOTO_LOCALE is None:
        _FOTO_LOCALE = {}
        for f in sorted((DATI / "locale").glob("delivery_catalogo_*.json")):
            try:
                for x in json.loads(f.read_text(encoding="utf-8"))["prodotti"]:
                    if x.get("img_web", "").startswith("WEB_"):
                        _FOTO_LOCALE[nz(x["des_art"])] = "https://delivery.peck.it/files/img_web/" + x["img_web"]
            except (OSError, ValueError, KeyError):
                pass
    return _FOTO_LOCALE.get(nz(nome), "")


def costruisci_righe_prezzi(righe_conf, alternative, V, CV):
    """Tutti i confronti, cibo e vini, in un'unica lista di dict (le righe «non trovato» e senza due prezzi non ci sono)."""
    righe = []
    for c in righe_conf:
        if not c["confrontabile"] or c["sim"] not in SIM_PESO or SIM_PESO[c["sim"]] < 1:
            continue
        it = c["item"]
        nome = it["nome"] if it else bello(c["nome_peck"])
        righe.append({
            "tipo": "c", "nome": nome, "item": it, "gruppo": it["categoria"] if it else categoria_di(c["nome_peck"].lower()),
            "sim": SIM_PESO[c["sim"]], "sim_testo": SIM_BREVE[c["sim"]], "dp": c["dp"], "base": c["base"], "data": c["data"],
            "p_peck": c["p_peck"], "f_peck": c["f_peck"], "kg_peck": c["kg_peck"],
            "fuori": [{"fonte": c["azienda"] or c["nome_prod"], "nome": c["nome_prod"], "url": c["url"], "p": c["p_prod"],
                       "f": c["f_prod"], "kg": c["kg_prod"], "dp": c["dp"]}],
            "src": SRC_PRODUTTORE, "occ": SIM_PESO[c["sim"]] >= 2, "solo_delivery": not it, "nd": False,
            "azienda": c["azienda"], "foto": "" if it else foto_delivery_per_nome(c["nome_peck"]),
        })
    for a in alternative:
        it = a["item"]
        righe.append({
            "tipo": "c", "nome": it["nome"] if it else bello(a["nome_peck"]), "item": it,
            "gruppo": it["categoria"] if it else categoria_di(a["nome_peck"].lower()),
            "sim": 0, "sim_testo": "Altro produttore · " + RICETTA_TESTO.get(a["ricetta"], a["ricetta"]).lower(),
            "dp": a["dp"], "base": base_alt(a), "data": a["data"],
            "p_peck": a["p_peck"], "f_peck": a["f_peck"], "kg_peck": a["kg_peck"],
            "fuori": [{"fonte": a["azienda"], "nome": a["nome_alt"], "url": a["url"], "p": a["p_alt"], "f": a["f_alt"],
                       "kg": a["kg_alt"], "dp": a["dp"]}],
            "src": SRC_ALTRO, "occ": False, "solo_delivery": not it, "nd": False, "azienda": a["azienda"],
            "foto": "" if it else foto_delivery_per_nome(a["nome_peck"]),
        })
    per_id = {str(w["id"]): w for w in V["vini"]}
    for vid, gruppi in CV.items():
        w = per_id.get(vid)
        if not w:
            continue
        for g in gruppi:
            ref = g["rif"]
            src = 0
            for o in g["offerte"]:
                src |= SRC_TANNICO if o["tipo"] == "t" else SRC_ENOTECHE
            stock = g["rif_stock"]
            righe.append({
                "tipo": "v", "nome": nome_nome(w), "w": w, "gruppo": gruppo_vino(w), "sim": 3 if ref["stessa"] else 2,
                "sim_testo": "Stesso vino, stessa annata" if ref["stessa"] else f"Stesso vino, annata {ref['a'] or '?'}",
                "dp": ref["dp"], "base": "al litro", "data": max(o["data"] for o in g["offerte"]),
                "g": g, "ref": ref, "src": src, "occ": stock is not None and stock["dp"] <= SOGLIA_OCCASIONE,
                "nd": stock is None, "solo_delivery": False,
            })
    return righe


def riepilogo_prezzi(righe):
    cibo = [r["dp"] for r in righe if r["tipo"] == "c" and r["sim"] >= 1]
    cibo_ok = [r["dp"] for r in righe if r["tipo"] == "c" and r["sim"] >= 2]
    vini = [r["dp"] for r in righe if r["tipo"] == "v"]
    vini_st = [r["dp"] for r in righe if r["tipo"] == "v" and not r["nd"]]
    alt = sum(1 for r in righe if r["tipo"] == "c" and r["sim"] == 0)
    return {"n": len(righe), "n_cibo": len(cibo) + alt, "n_vini": len(vini), "n_alt": alt, "n_cibo_pr": len(cibo),
            "med_cibo": mediana(cibo), "med_cibo_ok": mediana(cibo_ok), "n_cibo_ok": len(cibo_ok),
            "med_vini": mediana(vini), "med_vini_st": mediana(vini_st), "n_vini_st": len(vini_st),
            "meno_cibo": sum(1 for d in cibo if d <= SOGLIA_OCCASIONE), "meno_vini": sum(1 for d in vini if d <= SOGLIA_OCCASIONE)}


def pct_segno(dp):
    if dp is None:
        return "n.d."
    return "≈ 0%" if abs(dp) < 0.5 else f"{'+' if dp > 0 else '−'}{percento_testo(dp)}%"


# --- Angolo delle occasioni ------------------------------------------------

def voci_confronto(righe, r):
    """I confronti dell'Angolo: cibo «stesso prodotto» o «molto simile» con due prezzi veri; vini solo se almeno un negozio
    ha la bottiglia in vendita (prima la stessa annata, poi la piu' bassa). Le alternative di altri produttori non ci sono mai."""
    voci = []
    for c in righe:
        if c["tipo"] == "c":
            if c["sim"] < 2:
                continue
            it = c["item"]
            if it:
                foto, href = immagine_cibo(it, r), f"prodotto/{it['id']}/"
            else:
                foto, href = foto_html(c.get("foto", ""), c["nome"]), ""
            f = c["fuori"][0]
            voci.append({
                "tipo": "Cibo", "nome": c["nome"], "foto": foto, "href": href, "dp": c["dp"], "sim": c["sim_testo"],
                "peck": prezzo_formato(c["p_peck"], c["f_peck"]), "peck_u": al_kg_testo(c["kg_peck"], c["f_peck"]),
                "fuori": prezzo_formato(f["p"], f["f"]), "fuori_u": al_kg_testo(f["kg"], f["f"]),
                "et_fuori": "Dal produttore", "dove": c["azienda"] or f["nome"], "base": c["base"], "data": c["data"], "altri": "",
            })
        else:
            g, w = c["g"], c["w"]
            ref = g["rif_stock"]
            if ref is None:
                continue
            altri = [o for o in g["offerte"] if o is not ref and o["disp"]]
            testo_altri = ""
            if altri:
                testo_altri = ('<p class="meta">Anche: ' + "; ".join(
                    f'{H(o["fonte"])} {euro_it(o["p"])}' + ("" if o["stessa"] else f' (annata {H(o["a"] or "?")})') for o in altri) + "</p>")
            ann = "" if ref["stessa"] else f' <span class="meta">(annata {H(ref["a"] or "?")}; Peck: {H(g["a_peck"] or "senza annata")})</span>'
            voci.append({
                "tipo": "Vino", "nome": nome_nome(w), "foto": foto_html(url_foto_vino(w), "Bottiglia: " + nome_nome(w), "vino"),
                "href": f"vino/{w['d']}/", "dp": ref["dp"],
                "sim": "Stesso vino, stessa annata" if ref["stessa"] else f"Stesso vino, annata {ref['a'] or '?'}",
                "peck": f'{euro_it(g["p_peck"])} <span class="meta">({litri_testo(g["litri"])})</span>',
                "peck_u": f'<span class="meta">{euro_it(g["pl_peck"])} al litro</span>',
                "fuori": f'{euro_it(ref["p"])} <span class="meta">({litri_testo(ref["l"])})</span>{ann}',
                "fuori_u": f'<span class="meta">{euro_it(ref["pl"])} al litro</span>',
                "et_fuori": f'Su {ref["fonte"]}', "dove": ref["fonte"], "base": "al litro", "data": ref["data"], "altri": testo_altri,
            })
    return voci


def riga_occasione(v, r):
    dp = v["dp"]
    segno = classe_diff(dp)
    cifra = pct_segno(dp)
    frase = "Da Peck costa praticamente lo stesso" if abs(dp) < 0.5 else verdetto(dp)
    nome = (f'<a href="{r}{v["href"]}">{H(v["nome"])}</a>' if v["href"] else H(v["nome"]))
    base = f' <span class="meta">({H(v["base"])})</span>' if v["base"] else ""
    pagina = (f'<a class="vai-pagina" href="{r}{v["href"]}">Vai alla pagina<span class="sr"> di {H(v["nome"])}</span></a>'
              if v["href"] else "")
    return (f'<li class="occ">{v["foto"]}'
            f'<div class="occ-nome"><p class="cat">{H(v["tipo"])} · {H(v["sim"])}</p><p class="nome">{nome}</p><p class="meta">Confrontato con: {H(v["dove"])}</p>{pagina}</div>'
            f'<div class="occ-prezzi"><div class="lato"><p class="et">Da Peck</p><p class="cifra">{v["peck"]}</p><p>{v["peck_u"]}</p></div>'
            f'<div class="lato"><p class="et">{H(v["et_fuori"])}</p><p class="cifra">{v["fuori"]}</p><p>{v["fuori_u"]}</p>{v["altri"]}</div></div>'
            f'<div class="occ-diff v-{segno}"><p class="grande">{H(cifra)}</p>{barra_diff(dp)}<p class="meta">{H(frase)}{base}</p></div></li>')


def pagina_occasioni(voci, r):
    oggi_dati = max([v.get("data", "") for v in voci] + [DATA_CONFRONTO_DEFAULT])
    occasioni = sorted((v for v in voci if v["dp"] <= SOGLIA_OCCASIONE), key=lambda v: (v["dp"], v["nome"]))
    costano_di_piu = sorted(voci, key=lambda v: (-v["dp"], v["nome"]))[:N_COSTA_DI_PIU]
    soglia = f"{SOGLIA_OCCASIONE:g}".replace(".", ",")
    n_cibo = sum(1 for v in occasioni if v["tipo"] == "Cibo")
    n_vino = sum(1 for v in occasioni if v["tipo"] == "Vino")
    if occasioni:
        elenco = '<ul class="occasioni">' + "".join(riga_occasione(v, r) for v in occasioni) + "</ul>"
    else:
        elenco = '<p class="vuoto">Per ora nessun prodotto passa la soglia.</p>'
    corpo = f"""<section>
<h1 class="titolo-pagina">Angolo delle occasioni</h1>
<p class="intro">I prodotti che da Peck costano <strong>meno</strong> che altrove, o al massimo il <strong>{soglia}% in più</strong>, a parità di peso o di litri. Dentro ci sono solo i confronti sicuri: per il cibo lo stesso prodotto (o uno molto simile) sul sito di chi lo fa, per il vino la stessa bottiglia, dello stesso formato, in uno dei negozi che la vendono oggi (Tannico, Callmewine, Millesima, Xtrawine; prima la stessa annata, poi un’annata vicina, che in quel caso è scritta). Sono {conta_testo(len(occasioni), "prodotto", "prodotti")} ({n_cibo} di cibo, {n_vino} di vino), dal più conveniente. Vuoi vedere <em>tutti</em> i confronti, anche dove Peck costa di più? Sono in <a href="{r}prezzi/">Prezzi confrontati</a>.</p>
<p class="meta nota-ord">Confronto del {data_lunga(oggi_dati)}. I prezzi degli altri negozi si aggiornano in automatico una volta a settimana; i prezzi di Peck (servizio delivery e carta dell’enoteca) solo a mano, quindi possono essere più vecchi. La soglia (+{soglia}%) è una nostra scelta, non un giudizio su Peck: prezzi e formati cambiano, controlla sempre sulla pagina del negozio. Come si confronta: «<a href="{r}come-funziona/#confronto-prezzi">Come funziona</a>».</p>
{elenco}
<details class="costa-di-piu" id="costa-di-piu"><summary>Dove Peck costa di più ({len(costano_di_piu)} scarti maggiori)</summary>
<p class="meta">Gli stessi confronti, al contrario: i {len(costano_di_piu)} casi in cui da Peck si paga di più rispetto a chi il prodotto lo fa o lo vende. Peck è una gastronomia di lusso: il prezzo comprende anche il negozio, il marchio e il servizio.</p>
<ul class="occasioni">{"".join(riga_occasione(v, r) for v in costano_di_piu)}</ul>
</details>
</section>""", (f"Prodotti che da Peck costano meno che altrove, o al massimo il {soglia}% in più: cibo confrontato con il sito del produttore, "
                 f"vino con Tannico e le enoteche online. {AVVISO}")
    return corpo


# ---------------------------------------------------------------------------
# Storico: le frasi di origine di Peck in date passate (data/storico.csv, scritto da src/storico.py)
# ---------------------------------------------------------------------------

def carica_storico(dispensa, az, st):
    """Raggruppa le righe di storico.csv per (data, prodotto), le abbina alle aziende e ai prodotti della Dispensa di oggi.
    Aggiunge `storico` ai prodotti e `osservazioni` alle aziende."""
    if not (DATI / "storico.csv").exists():
        return []
    aziende, riga_a = st["_aziende"], st["_riga_a_azienda"]
    per_nome = {nz(d["nome_originale"]): d for d in dispensa}
    gruppi = {}
    for r in leggi_csv("storico"):
        k = (r["data_fonte"], r["nome_prodotto"])
        g = gruppi.get(k)
        if g is None:
            g = gruppi[k] = {
                "data": r["data_fonte"], "fonte": r["fonte"], "nome": bello(r["nome_prodotto"]),
                "confronto": r["confronto_2026"], "righe": [], "items": [], "aziende": [],
                "nomi_2026": [n.strip() for n in (r["nome_elemento_2026"] or "").split(" | ") if n.strip()],
                "nota_conf": r["nota_confronto"],
            }
        aid = ""
        if r["sede_peck"] == "si":
            aid = "peck"
        elif r["indirizzo"] or r["comune"] or r["bollo_ce"] or r["produttore_nominato"]:
            a, _ = aziende.cerca(r)
            if a:
                aid = riga_a.get((a["tipo_chiave"], nz(a["chiave"])), "")
        dove = (", ".join(x for x in (r["indirizzo"], r["cap"], luogo(r["comune"], r["provincia"])) if x)
                or r["bollo_ce"] or r["produttore_nominato"])
        g["righe"].append({"frase": r["frase_origine"], "luogo": dove, "aid": aid if aid in az else "", "nota": r["nota"]})
    for g in gruppi.values():
        for n in g["nomi_2026"]:
            it = per_nome.get(nz(n))
            if it and it not in g["items"]:
                g["items"].append(it)
                it.setdefault("storico", []).append(g)
        for ri in g["righe"]:
            if ri["aid"] and ri["aid"] not in g["aziende"]:
                g["aziende"].append(ri["aid"])
                az[ri["aid"]]["osservazioni"].append(g)
    return sorted(gruppi.values(), key=lambda g: (g["data"], g["nome"]))


def nome_azienda_link(aid, az, r):
    z = az.get(aid)
    if not z or not (z["trovata"] or aid == "peck"):
        return ""
    return f'<a href="{r}produttore/{z["id"]}/">{H(z["nome"])}</a>'


def oggi_di(it, az, r):
    """[html] di chi fa oggi (24 ottobre 2026) il prodotto: azienda e luogo, uno per origine diversa."""
    out, visti = [], set()
    for o in it["origini"]:
        if o["stato"] == "nessuna" or not o["azienda"]:
            continue
        z = az.get(o["azienda"])
        dove = luogo(o["comune"] or o.get("comune_azienda") or (z and z["comune"]) or "",
                     o["provincia"] or (z and z["provincia"]) or "")
        if o["stato"] == "peck":
            testo = "Peck stessa, in via Spadari 9, Milano"
        else:
            nome = nome_azienda_link(o["azienda"], az, r) or "azienda non trovata"
            testo = nome + (f", {H(dove)}" if dove else (f" ({H(o['bollo'])})" if o["bollo"] else ""))
        if testo not in visti:
            visti.add(testo)
            out.append(testo)
    return out


def riga_2025(ri, az, r):
    nome = nome_azienda_link(ri["aid"], az, r)
    if ri["luogo"] and nome:
        testo = f"{H(ri['luogo'])} — {nome}"
    elif ri["luogo"]:
        testo = H(ri["luogo"])
    else:
        testo = "<em>nessun luogo di produzione sull’etichetta</em>"
    if ri["aid"] == "peck" and ri["luogo"]:
        testo = f"{H(ri['luogo'])} — Peck stessa"
    frase = f'<blockquote class="frase">«{H(ri["frase"])}»</blockquote>' if ri["frase"] else ""
    return f'<div class="st-riga"><p>{testo}</p>{frase}</div>'


def blocco_storia(it, az, r):
    """«Storia del fornitore» nella pagina di un prodotto: l'etichetta di date passate contro lo shop di oggi."""
    storico = it.get("storico") or []
    if not storico:
        return ""
    blocchi = []
    for g in sorted(storico, key=lambda g: g["data"]):
        cambiato = g["confronto"] == "diverso"
        oggi = oggi_di(it, az, r)
        oggi_html = "".join(f"<p>{x}</p>" for x in oggi) if oggi else (
            "<p><em>nella scheda di oggi Peck non scrive più dove è fatto</em></p>" if cambiato
            else "<p><em>nessun luogo di produzione indicato</em></p>")
        testa = ('<p class="st-esito st-cambio">Il fornitore è cambiato</p>' if cambiato
                 else '<p class="st-esito st-uguale">Nessun cambiamento: stesso luogo di produzione</p>')
        nota = (f'<details><summary>Come abbiamo confrontato</summary><p>{H(g["nota_conf"])}</p></details>'
                if g["nota_conf"] else "")
        blocchi.append(
            f'<div class="storia{" cambiato" if cambiato else ""}">{testa}<ol class="linea">'
            f'<li><span class="data">{H(data_lunga(g["data"]))}</span><div>{"".join(riga_2025(ri, az, r) for ri in g["righe"])}'
            f'<p class="meta">{H(cap(g["fonte"]))}.</p></div></li>'
            f'<li class="oggi"><span class="data">{H(DATA_FOTOGRAFIA_LUNGA)}</span><div>{oggi_html}'
            f'<p class="meta">Shop online di Peck, il giorno della fotografia dei dati.</p></div></li></ol>{nota}</div>')
    return ('<section class="sezione" id="storia"><h2>Storia del fornitore</h2>'
            '<p class="meta">Che cosa diceva l’etichetta in date diverse, messa accanto a quello che dice oggi lo shop. '
            'Le date sono quelle in cui abbiamo visto la pagina: fra una e l’altra il fornitore può essere cambiato più volte. '
            'Dettagli in «<a href="' + r + 'come-funziona/#fotografie-datate">Come funziona</a>».</p>'
            + "".join(blocchi) + "</section>")


def blocco_osservazioni(z, az, r):
    """Le osservazioni datate di un'azienda, nella sua pagina."""
    oss = sorted(z.get("osservazioni") or [], key=lambda g: (g["data"], g["nome"]))
    if not oss:
        return ""
    voci = ""
    for g in oss:
        it = g["items"][0] if g["items"] else None
        prodotto = (f'<a href="{r}prodotto/{it["id"]}/">{H(g["nome"])}</a>' if it else H(g["nome"]))
        righe = [ri for ri in g["righe"] if ri["aid"] == z["id"]]
        dove = "; ".join(dict.fromkeys(ri["luogo"] for ri in righe if ri["luogo"])) or "luogo non indicato"
        frasi = "".join(f'<blockquote class="frase">«{H(ri["frase"])}»</blockquote>' for ri in righe if ri["frase"])
        if g["confronto"] == "non in vendita online nel 2026":
            esito = '<span class="st-badge st-cambio">non più nello shop online nel 2026</span>'
        elif g["confronto"] == "diverso":
            oggi = oggi_di(it, az, r) if it else []
            esito = ('<span class="st-badge st-cambio">oggi non è più così</span>'
                     + (f' <span class="meta">(oggi: {"; ".join(oggi)})</span>' if oggi else ""))
        else:
            esito = '<span class="st-badge st-uguale">stesso luogo anche nel 2026</span>'
        voci += (f'<li><p><strong>{H(data_lunga(g["data"]))}</strong> · {prodotto}<br>'
                 f'<span class="meta">{H(dove)}</span> {esito}</p>{frasi}</li>')
    return (f'<section class="sezione" id="osservazioni"><h2>Osservazioni datate ({len(oss)})</h2>'
            f'<p class="meta">Che cosa diceva l’etichetta dei prodotti collegati a questa azienda nelle fotografie salvate '
            f'in date diverse (<a href="{r}come-funziona/#fotografie-datate">come funziona</a>).</p><ul class="osservazioni">{voci}</ul></section>')


def sezione_fotografie_datate(storico, az):
    if not storico:
        return ""
    date = sorted({g["data"] for g in storico})
    n_prod = len(storico)
    cambiati = [g for g in storico if g["confronto"] == "diverso"]
    spariti = [g for g in storico if g["confronto"] == "non in vendita online nel 2026"]
    uguali = n_prod - len(cambiati) - len(spariti)
    fonti = "; ".join(f"{data_lunga(d)}: {next(g['fonte'] for g in storico if g['data'] == d)}" for d in date)
    li_cambiati = "".join(f"<li>{H(g['nome'])}</li>" for g in cambiati)
    li_spariti = "".join(
        f"<li>{H(g['nome'])}" + (" (" + ", ".join(az[a]["nome"] for a in g["aziende"] if a in az) + ")" if g["aziende"] else "") + "</li>"
        for g in spariti)
    return f"""<h2 id="fotografie-datate">Fotografie datate</h2>
<p>Lo shop di Peck cambia: i fornitori dei prodotti anche. Oltre alla fotografia di oggi ({H(DATA_FOTOGRAFIA_LUNGA)}) teniamo qualche <em>fotografia di una data passata</em>: una pagina dello shop salvata a mano dal proprietario del progetto in quel giorno ({H(fonti)}). Di ogni prodotto si legge solo la frase breve sull’origine, come per oggi (programma <code>src/storico.py</code>, tabella <code>data/storico.csv</code>, file in <code>data/storico_fonti/</code>: per aggiungere una data basta aggiungere un file e rilanciarlo).</p>
<ul>
<li><strong>Come si confronta.</strong> Il luogo di produzione di allora (via e comune, o il codice del bollo CE) si mette accanto a quello di oggi: «uguale» se è lo stesso, «diverso» se è cambiato o se oggi la scheda non dice più nulla, «non in vendita online nel 2026» se il prodotto non c’è più nello shop (o c’è in un altro formato). Sono {n_prod} prodotti: {uguali} uguali, {len(cambiati)} diversi, {len(spariti)} non più in vendita online.</li>
<li><strong>Dove si vede.</strong> Nella pagina di un prodotto, «Storia del fornitore» mostra le date una dopo l’altra e segnala quando il fornitore è cambiato. Nella pagina di un’azienda, «Osservazioni datate» elenca i prodotti che aveva in quelle date, anche se oggi non sono più nello shop: per questo ci sono pagine di aziende che oggi non fanno niente per lo shop online.</li>
<li><strong>Limiti.</strong> Una fotografia è un giorno solo: quello che c’era fra una data e l’altra non lo sappiamo. Se oggi una frase non c’è più non vuol dire che il prodotto sia cambiato, solo che Peck non la scrive più.</li>
</ul>
{("<p>Prodotti il cui fornitore è cambiato dopo la prima fotografia:</p><ul>" + li_cambiati + "</ul>") if cambiati else ""}
{("<p>Prodotti della prima fotografia che oggi non sono più (o non sono più così) nello shop online:</p><ul>" + li_spariti + "</ul>") if spariti else ""}
"""


# ---------------------------------------------------------------------------
# Valore spacchettato delle pagine dello shop (data/confronto/box_valore.csv e box_valore_righe.csv, da src/box_valore.py)
# ---------------------------------------------------------------------------

FONTE_PREZZO_BOX = {
    "delivery": "dal servizio delivery di Peck", "produttore": "dal sito del produttore",
    "scheda singola Peck": "dalla scheda singola dello shop di Peck", "enoteca Peck": "dalla carta dell’enoteca di Peck",
}


def carica_box_valore(box):
    f = DATI / "confronto" / "box_valore.csv"
    if not f.exists():
        return {}
    per_url = {b["url"]: b for b in box}
    out = {}
    with open(f, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            b = per_url.get((r["url"] or "").strip())
            if b:
                out[b["id"]] = {"r": r, "righe": []}
    f = DATI / "confronto" / "box_valore_righe.csv"
    if f.exists():
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                b = per_url.get((r["url_box"] or "").strip())
                if b and b["id"] in out:
                    out[b["id"]]["righe"].append(r)
    return out


def blocco_valore(b, bv, items, r):
    """«Valore spacchettato»: la somma dei prezzi dei singoli prodotti contro il prezzo della pagina, con la copertura."""
    if not bv:
        return ""
    x = bv["r"]
    n_prezzati = int(num_conf(x["n_prezzati"]) or 0)
    if b["tipo"] != "box" and n_prezzati == 0:
        return ""
    n_el = int(num_conf(x["n_elementi"]) or len(bv["righe"]))
    cop = num_conf(x["copertura_pct"]) or 0
    giudizio = (x.get("copertura_giudizio") or "").strip().lower() or ("buona" if cop >= 80 else "media" if cop >= 50 else "bassa")
    prezzo_box = num_conf(x["prezzo_box"])
    somma = num_conf(x.get("somma_totale")) if x.get("somma_totale") else None
    if somma is None:
        somma = (num_conf(x["somma_prezzi_peck"]) or 0) + (num_conf(x["somma_prezzi_produttore"]) or 0)
    s_peck, s_prod = num_conf(x["somma_prezzi_peck"]) or 0, num_conf(x["somma_prezzi_produttore"]) or 0
    dpc = num_conf(x.get("differenza_pct")) if (x.get("differenza_pct") or "").strip() else None
    n_stime = int(num_conf(x.get("n_stime")) or 0)
    frase = {
        "bassa": "Copertura bassa (sotto il 50%): la somma è solo una piccola parte del contenuto, quindi non dice se la box conviene "
                 "o no. Per questo non calcoliamo nessuna percentuale.",
        "media": "Copertura parziale: la somma è solo una parte del contenuto. La differenza con il prezzo della pagina comprende "
                 "anche i prodotti senza prezzo, quindi non è un ricarico.",
        "buona": "Copertura buona: quasi tutto il contenuto ha un prezzo. La differenza è, al massimo, il valore di confezione, "
                 "nastri e servizio (più i pochi prodotti senza prezzo).",
    }.get(giudizio, "")
    stat = (f'<div class="stat"><div><b>{euro_it(prezzo_box)}</b>prezzo della pagina Peck</div>'
            f'<div><b>{euro_it(somma)}</b>somma dei prezzi trovati</div>'
            f'<div><b>{n_prezzati} su {n_el}</b>prodotti con un prezzo</div>'
            f'<div><b>{num(round(cop))}%</b>copertura</div>'
            + (f'<div><b>{H(pct_segno(dpc))}</b>la pagina rispetto alla somma</div>' if dpc is not None and giudizio != "bassa" else "")
            + '</div>')
    barra = (f'<div class="copertura" role="img" aria-label="Copertura {round(cop)}%"><span style="width:{min(cop, 100):.0f}%"></span></div>')
    dettaglio_somma = (f'<p class="meta">La somma è di {euro_it(s_peck)} di prezzi di Peck (delivery, schede singole, carta dell’enoteca) '
                       f'e {euro_it(s_prod)} di prezzi dei produttori.'
                       + (f' {n_stime} dei prezzi sommati {"è una stima" if n_stime == 1 else "sono stime"} (a peso, in proporzione o con formato presunto).'
                          if n_stime else "") + '</p>')
    per_nome = {nz(items[i]["nome_originale"]): items[i] for i in b["elementi"] if i in items}
    righe = ""
    for ri in bv["righe"]:
        it = per_nome.get(nz(ri["prodotto"]))
        nome = (f'<a href="{r}prodotto/{it["id"]}/">{H(it["nome"])}</a>' if it else H(bello(ri["prodotto"])))
        p = num_conf(ri["prezzo"]) if ri["prezzo"] else None
        if p is not None:
            fonte = FONTE_PREZZO_BOX.get(ri["fonte"], ri["fonte"])
            q = (ri.get("qualita") or "").strip()
            stima = f' <span class="meta">({H(q)})</span>' if q and q != "diretto" else ""
            cella = f'<td class="num">{euro_it(p)}</td><td>{H(cap(fonte))}{stima}</td>'
        else:
            cella = f'<td class="num">—</td><td class="meta">{H(cap(ri["motivo_senza_prezzo"] or "senza prezzo"))}</td>'
        righe += f"<tr><td>{nome}</td>{cella}</tr>"
    tabella = (f'<details><summary>I prodotti, uno per uno ({len(bv["righe"])})</summary><div class="tab-scorri"><table class="tab">'
               f'<thead><tr><th>Prodotto</th><th>Prezzo</th><th>Da dove viene</th></tr></thead><tbody>{righe}</tbody></table></div></details>'
               if righe else "")
    nota = f'<details><summary>Note del calcolo</summary><p>{H(x["nota"])}</p></details>' if x.get("nota") else ""
    return (f'<section class="sezione" id="valore"><h2>Valore spacchettato</h2>'
            f'<p class="meta">Quanto costerebbero, presi uno a uno, i prodotti di questa pagina di cui abbiamo trovato un prezzo, '
            f'contro il prezzo della pagina. Nella somma non ci sono confezione, nastri e servizio. È un’indicazione, non un giudizio.</p>'
            f'{stat}{barra}<p class="avviso-annata">{H(frase)}</p>{dettaglio_somma}{tabella}{nota}</section>')


# ---------------------------------------------------------------------------
# Prezzi confrontati (/prezzi/): TUTTI i confronti, cibo e vini, con filtri; le righe sono in docs/prezzi.json
# e le disegna app.js (come l'Enoteca), a pagine.
# ---------------------------------------------------------------------------

def immagine_json(it, c=None):
    """Come si disegna la foto di una riga: ["r", url, x, y, w, h, media, disegno, box] ritaglio; ["d", disegno, alt];
    ["i", url] foto; ["n"] niente."""
    if not it:
        return ["n"]
    rt, d = it.get("ritaglio"), it.get("disegno")
    if rt and d:
        return ["r", rt["url"], round(rt["x"], 4), round(rt["y"], 4), round(rt["w"], 4), round(rt["h"], 4),
                1 if rt["certezza"] == "media" else 0, f"disegni/{d}.svg", rt["box_nome"]]
    if d:
        return ["d", f"disegni/{d}.svg", DISEGNI_NOMI.get(d, d)]
    return ["i", it["foto"]] if it.get("foto") else ["n"]


def r1(x):
    return None if x is None else round(x, 1)


def json_prezzi(righe, riep):
    gruppi_cibo = [(c, cap(c)) for c in ORDINE_CATEGORIE if any(x["tipo"] == "c" and x["gruppo"] == c for x in righe)]
    gruppi_vino = [(k, t) for k, t in GRUPPI_VINO if any(x["tipo"] == "v" and x["gruppo"] == k for x in righe)]
    regioni = sorted({(x["w"]["paese"], x["w"]["r"]) for x in righe if x["tipo"] == "v" and x["w"]["r"]},
                     key=lambda t: (t[0], t[1].lower()))
    out = []
    for x in righe:
        if x["tipo"] == "c":
            it = x["item"]
            out.append({
                "t": "c", "n": x["nome"], "g": x["gruppo"], "h": f"prodotto/{it['id']}/" if it else "",
                "im": immagine_json(it) if it else (["i", x["foto"]] if x.get("foto") else ["n"]),
                "sp": x["sim"], "st": x["sim_testo"], "dp": r1(x["dp"]), "b": x["base"], "d": x["data"], "s": x["src"],
                "x": 1 if x["sim"] >= 2 else 0, "sd": 1 if x["solo_delivery"] else 0,
                "pk": [x["p_peck"], x["f_peck"], x["kg_peck"], unita_di(x["f_peck"])],
                "fu": [[f["fonte"], f["nome"], f["url"], f["p"], f["f"], f["kg"], unita_di(f["f"])] for f in x["fuori"]],
            })
        else:
            w, g, ref = x["w"], x["g"], x["ref"]
            out.append({
                "t": "v", "n": x["nome"], "g": x["gruppo"], "h": f"vino/{w['d']}/", "ph": url_foto_vino(w),
                "a": w["a"], "r": w["r"], "pa": w["paese"], "ti": w["tipo"],
                "sp": x["sim"], "st": x["sim_testo"], "dp": r1(x["dp"]), "b": "al litro", "d": x["data"], "s": x["src"],
                "x": 1 if x["occ"] else 0, "nd": 1 if x["nd"] else 0, "l": g["litri"],
                "pk": [g["p_peck"], g["pl_peck"], g["a_peck"]],
                "fu": [[o["fonte"], o["url"], o["a"], o["p"], o["pl"], 1 if o["disp"] else 0, r1(o["dp"]),
                        1 if o["stessa"] else 0, 1 if o is ref else 0] for o in g["offerte"]],
            })
    return {
        "meta": {"data": max(x["data"] for x in righe), "soglia": SOGLIA_OCCASIONE,
                 "gruppi": [{"k": k, "t": t, "v": 0} for k, t in gruppi_cibo] + [{"k": k, "t": t, "v": 1} for k, t in gruppi_vino],
                 "regioni": [[p, r] for p, r in regioni], "riepilogo": {k: r1(v) if isinstance(v, float) else v for k, v in riep.items()}},
        "righe": out,
    }


def pagina_prezzi(righe, riep, r):
    soglia = f"{SOGLIA_OCCASIONE:g}".replace(".", ",")
    gruppi_cibo = [c for c in ORDINE_CATEGORIE if any(x["tipo"] == "c" and x["gruppo"] == c for x in righe)]
    gruppi_vino = [(k, t) for k, t in GRUPPI_VINO if any(x["tipo"] == "v" and x["gruppo"] == k for x in righe)]
    regioni = sorted({(x["w"]["paese"], x["w"]["r"]) for x in righe if x["tipo"] == "v" and x["w"]["r"]},
                     key=lambda t: (t[1].lower(), t[0]))
    opt_cat = ('<optgroup label="Cibo">' + "".join(f'<option value="{H(c)}">{H(cap(c))}</option>' for c in gruppi_cibo) + "</optgroup>"
               '<optgroup label="Vino">' + "".join(f'<option value="{H(k)}">{H(t)}</option>' for k, t in gruppi_vino) + "</optgroup>")
    opt_reg = "".join(f'<option value="{H(rg)}">{H(rg)} ({H(p)})</option>' for p, rg in regioni)
    campi = (
        f'<div class="campo"><label for="f-cat">Categoria</label><select id="f-cat" name="cat"><option value="">Tutte</option>{opt_cat}</select></div>'
        f'<div class="campo"><label for="f-reg">Regione del vino</label><select id="f-reg" name="reg"><option value="">Tutte</option>{opt_reg}</select></div>'
        '<div class="campo"><label for="f-fonte">Dove si confronta</label><select id="f-fonte" name="fonte"><option value="">Dappertutto</option>'
        '<option value="produttore">Dal produttore</option><option value="altro">Da un altro produttore</option>'
        '<option value="tannico">Tannico</option><option value="enoteche">Enoteche (Callmewine, Millesima, Xtrawine)</option></select></div>'
        '<div class="campo spunta"><input type="checkbox" id="f-stesso" name="stesso" value="1"><label for="f-stesso">Solo lo stesso prodotto</label></div>'
        f'<div class="campo spunta"><input type="checkbox" id="f-occ" name="occ" value="1"><label for="f-occ">Solo dove Peck costa meno (o al massimo +{soglia}%)</label></div>'
        '<div class="campo"><label for="f-ord">Ordina</label><select id="f-ord" name="ord"><option value="">Per categoria, poi dal più conveniente</option>'
        '<option value="dp-su">Tutto insieme: Peck costa meno prima</option><option value="dp-giu">Tutto insieme: Peck costa di più prima</option>'
        '<option value="nome">Per nome</option></select></div>')

    def segno(v):
        return "n.d." if v is None else pct_segno(v)
    s = riep
    corpo = f"""<section>
<h1 class="titolo-pagina">Prezzi confrontati</h1>
<p class="intro">Tutti i confronti di prezzo che abbiamo, in un posto solo: il cibo di Peck contro il sito di chi lo fa, il vino contro Tannico e le enoteche online (Callmewine, Millesima, Xtrawine). Ogni riga dice quanto costa a parità di peso o di litri e dove; la barra mostra la differenza: <span class="leg leg-meno">verde</span> se da Peck costa meno, <span class="leg leg-pari">neutra</span> entro il ±{soglia}%, <span class="leg leg-piu">calda</span> se costa di più. Gli abbinamenti sono nostri e possono sbagliare; prezzi e formati cambiano. Come si confronta: «<a href="{r}come-funziona/#confronto-prezzi">Come funziona</a>». Solo le migliori occasioni stanno nell’<a href="{r}occasioni/">Angolo delle occasioni</a>.</p>
<div class="riepilogo" id="riepilogo">
<div><b>{num(s["n"])}</b>confronti in tutto</div>
<div><b>{num(s["n_cibo"])}</b>di cibo{(" (" + str(s["n_alt"]) + " con un altro produttore)") if s["n_alt"] else ""}</div>
<div><b>{num(s["n_vini"])}</b>di vino</div>
<div><b>{segno(s["med_cibo"])}</b>differenza mediana, cibo (dal produttore)</div>
<div><b>{segno(s["med_vini"])}</b>differenza mediana, vino</div>
</div>
<p class="meta nota-ord">Differenza mediana: la metà dei confronti sta sotto e metà sopra. Per il cibo, sui soli «stesso prodotto» e «molto simile» è {segno(s["med_cibo_ok"])} ({num(s["n_cibo_ok"])} confronti); per il vino, sulle bottiglie ancora in vendita è {segno(s["med_vini_st"])} ({num(s["n_vini_st"])}). Peck costa meno, o al massimo il {soglia}% in più, in {num(s["meno_cibo"])} confronti di cibo e in {num(s["meno_vini"])} di vino. Confronto del {data_lunga(max(x["data"] for x in righe))}; i prezzi di Peck (delivery e carta dell’enoteca) si aggiornano solo a mano.</p>
{form_filtri("Filtri: prezzi confrontati", ctl_cerca("Cerca un prodotto, un vino o un’azienda", "per esempio: tartufo, Barolo, Tannico"), campi)}
<div class="barra-lista"><p class="conteggio" id="conteggio" role="status" aria-live="polite">{num(s["n"])} confronti</p><p class="meta" id="riepilogo-vivo"></p></div>
<div class="lista" id="lista" data-prezzi data-json="../prezzi.json" data-singolare="confronto" data-plurale="confronti">
<ul class="griglia occasioni prezzi"></ul>
<p class="vuoto" hidden>Nessun risultato. Prova a togliere qualche filtro.</p>
<p class="caricamento">Carico i confronti…</p>
<button type="button" class="bottone secondario altri" hidden>Mostra altri</button>
</div>
<noscript><p class="meta">Per filtrare i confronti serve JavaScript. Senza, trovi i migliori nell’<a href="{r}occasioni/">Angolo delle occasioni</a> e, in ogni pagina di prodotto o di vino, il confronto che la riguarda.</p></noscript>
</section>"""
    return corpo, (f"Tutti i confronti di prezzo: cibo di Peck contro il sito del produttore, vino contro Tannico e le enoteche online, "
                   f"con filtri e differenza al chilo o al litro. {AVVISO}")


# ---------------------------------------------------------------------------
# Come funziona
# ---------------------------------------------------------------------------

def pagina_come_funziona(dispensa, box, produttori, V, M, righe_conf, CV, storico=(), az=None, riep=None, n_alt=0, n_bv=0):
    conta = Counter(d["stato"] for d in dispensa)
    def _con(k):
        return sum(1 for w in V["vini"] if w.get("voti") and w["voti"][k])
    VOTI = {"n": sum(1 for w in V["vini"] if w.get("voti") and w["voti"]["t"]),
            "data": next((w["voti"]["t"]["data"] for w in V["vini"] if w.get("voti") and w["voti"]["t"]), "2026-10-25"),
            "tot": len(V["vini"]), "bollini": sum(1 for w in V["vini"] if "vb" in w),
            "c": sum(1 for w in V["vini"] if w.get("vk") == "c"), "t": sum(1 for w in V["vini"] if w.get("vk") == "t"),
            "u": sum(1 for w in V["vini"] if w.get("vk") == "u"),
            "we": _con("we"), "xw": _con("xw"), "en": _con("en"),
            "tcrit": sum(1 for w in V["vini"] if w.get("voti") and w["voti"]["t"] and w["voti"]["t"]["critici"])}
    en_nomi = sorted({e["fonte"] for w in V["vini"] if w.get("voti") for e in w["voti"]["en"] if e["fonte"]})
    riga_en = (f'<li><strong>Enoteche e negozi.</strong> Per {VOTI["en"]} vini abbiamo anche i punteggi di critici che un negozio'
               f' ({H(", ".join(en_nomi))}) riporta nella scheda del prodotto; sul bollino valgono come i critici, con il nome del negozio e il link.</li>'
               if VOTI["en"] else "")
    n_delivery = sum(1 for d in dispensa if d.get("delivery"))
    n_foto_delivery = sum(1 for d in dispensa if d.get("foto_tipo") == "delivery")
    csv_nomi = ["prodotti", "elementi", "indirizzi", "altre_origini", "aziende", "delivery_dispensa", "vini", "formati", "cantine", "vini_nelle_box", "tannico_voti", "voti_aperti"] + (["voti_enoteche"] if (DATI / "voti_enoteche.csv").exists() else []) +         [f"confronto/{Path(f).stem}" for f in sorted(glob.glob(str(DATI / "confronto" / "risultati_*.csv")))] +         (["confronto/vini_tannico"] if (DATI / "confronto" / "vini_tannico.csv").exists() else []) +         [f"confronto/{n}" for n in ("vini_enoteche_prezzi", "alternative_7", "box_valore", "box_valore_righe") if (DATI / "confronto" / f"{n}.csv").exists()] +         [n for n in ("ritagli", "storico") if (DATI / f"{n}.csv").exists()]
    righe_cat = "".join(
        f"<tr><td>{H(cap(c))}</td><td>" + H(", ".join(
            (f"inizia con «{p[1:].strip()}»" if p.startswith("^") else f"«{p.strip()}»") for p in parole)) + "</td></tr>"
        for c, parole in CATEGORIE)
    parole_disegno = dict(DISEGNI_PAROLE)
    cat_disegno = defaultdict(list)
    for c in ORDINE_CATEGORIE:
        cat_disegno[DISEGNO_CATEGORIA[c]].append(cap(c))
    ordine_disegni = list(dict.fromkeys([d for d, _ in DISEGNI_PAROLE] + list(DISEGNO_CATEGORIA.values())))
    righe_disegni = "".join(
        f'<tr><td class="cella-disegno"><img class="mini-disegno" src="../disegni/{d}.svg" width="40" height="40" '
        f'alt="Disegno: {H(DISEGNI_NOMI[d])}">{H(cap(d.replace("te-caffe", "tè e caffè").replace("-", " e " if d == "olio-aceto" else " ")))}</td><td>'
        + H(", ".join((f"inizia con «{p[1:].strip()}»" if p.startswith("^") else f"«{p.strip()}»")
                      for p in parole_disegno.get(d, [])) or "—")
        + f"</td><td>{H(', '.join(cat_disegno.get(d, [])) or '—')}</td></tr>"
        for d in ordine_disegni)
    li_csv = "".join(f'<li><a href="{REPO}/blob/main/data/{n}.csv" target="_blank" rel="noopener noreferrer">data/{n}.csv{sr_nuova_scheda()}</a></li>'
                     for n in csv_nomi)
    link_ok = sum(n for (campo, e), n in LINK.conteggi.items() if e == "ok")
    link_tot = sum(LINK.conteggi.values())
    link_rotti = sum(n for (campo, e), n in LINK.conteggi.items() if e in ("rotto", "dominio_parcheggiato"))
    link_bloc = sum(n for (campo, e), n in LINK.conteggi.items() if e in ("bloccato", "errore"))
    sezione_link = ""
    if link_tot:
        sezione_link = f"""<h2>I link ai negozi dei produttori</h2>
<p>Il bottone «Compra dal produttore» porta al negozio online dell’azienda, non a noi: noi non vendiamo niente. Un programma (<code>src/controlla_link.py</code>) apre ogni link e controlla che risponda; il {data_lunga(LINK.data)} ne ha controllati {link_tot}: {link_ok} si aprono (alcuni li abbiamo controllati a mano perché il sito rifiuta i programmi), {link_rotti} sono rotti o domini in vendita e per {link_bloc} il controllo non è possibile con un programma (di solito perché il sito rifiuta i robot). Un link rotto non diventa mai un bottone; quelli sbagliati sono stati cercati a mano e corretti in <code>data/aziende.csv</code> (la colonna <code>nota</code> dice cosa è cambiato). I negozi cambiano: se un bottone non funziona, segnalacelo.</p>"""
    conta_sim = Counter(c["sim"] for c in righe_conf)
    n_conf_ok = sum(1 for d in dispensa if d.get("chip"))
    n_item_conf = sum(1 for d in dispensa if d.get("confronti"))
    n_produttori_conf = len({c["azienda"] for c in righe_conf if c["azienda"]})
    n_vini_conf = len(CV)
    n_vini_disp = sum(1 for gl in CV.values() if any(g["rif_stock"] for g in gl))
    n_offerte_vini = Counter(o["fonte"] for gl in CV.values() for g in gl for o in g["offerte"])
    n_ritagli = sum(1 for d in dispensa if d.get("ritaglio"))
    sezione_datate = sezione_fotografie_datate(list(storico), az or {})
    soglia_t = f"{SOGLIA_OCCASIONE:g}".replace(".", ",")
    sezione_confronto = f"""<h2 id="confronto-prezzi">Confronto prezzi</h2>
<p>Per molti prodotti sappiamo chi li fa. Quando quel produttore vende lo stesso prodotto (o uno molto simile) sul suo sito, ne scriviamo il prezzo accanto a quello di Peck; per i vini facciamo lo stesso con Tannico. È un confronto fra prezzi scritti sui siti, non una valutazione: quello che Peck aggiunge (negozio, marchio, selezione, consegna) non si misura qui.</p>
<ul>
<li><strong>Come si abbina.</strong> Prima si cerca il catalogo pubblico del produttore; poi si sceglie il prodotto con lo stesso tipo, lo stesso formato o il più vicino, e dove ci sono si confrontano gli ingredienti (etichetta del delivery di Peck contro scheda del produttore). Abbiamo guardato {n_produttori_conf} produttori, con {n_item_conf} prodotti della Dispensa che hanno almeno un esito da mostrare. Gli abbinamenti non sono verità ufficiali e possono sbagliare: nel dubbio si scende di livello.</li>
<li><strong>I livelli di somiglianza.</strong> <em>Stesso prodotto</em>: stesso produttore, stesso tipo e stesso formato, ingredienti uguali o quasi ({conta_sim["stesso prodotto"]} confronti). <em>Molto simile</em>: stesso produttore e tipo, ma formato o ricetta un po’ diversi, e la nota dice come ({conta_sim["molto simile"]}). <em>Simile</em>: stesso produttore, prodotto della stessa famiglia, solo indicativo ({conta_sim["simile"]}). Se il prodotto non si trova sul sito del produttore, la riga non compare mai; quando non siamo sicuri non diciamo «stesso prodotto».</li>
<li><strong>Il confronto è al chilo o al litro.</strong> I formati sono spesso diversi (un tubetto da 30 g contro uno da 40 g), quindi la differenza si calcola sul prezzo al kg o al litro: «Da Peck costa il 72% in più» vuol dire che, a parità di peso, Peck costa il 72% in più. Quando i formati non sono confrontabili (per esempio 580 ml contro 450 g) lo diciamo e la differenza è per confezione. Il bollino «+72% vs produttore» sulle schede della Dispensa compare solo per «stesso prodotto» e «molto simile» con due prezzi veri; il filtro «Con confronto prezzi» mostra i {n_conf_ok} prodotti che lo hanno.</li>
<li><strong>Prodotti che si trovano solo nelle box.</strong> Molti prodotti Peck non si comprano da soli: stanno solo dentro le box, e non hanno un prezzo singolo. Di quelli mostriamo solo il prezzo del produttore e scriviamo «Da Peck si trova solo nelle box».</li>
<li><strong>Robots.txt e agenti automatici.</strong> Prima di scaricare un catalogo si legge il <code>robots.txt</code> del produttore e lo si rispetta, comprese le sezioni che vietano i programmi di intelligenza artificiale. Due produttori li vietano per nome: Panificio Follador e Casa Iuorio. Non li abbiamo confrontati, nemmeno cambiando il nome del programma: le loro righe dicono «confronto da fare a mano», con il link al loro sito, e i dati scaricati prima di accorgerci sono stati cancellati. Se un sito non ha un negozio con i prezzi, la riga non c’è.</li>
<li><strong>I vini con Tannico e le enoteche.</strong> Per ogni formato di Peck cerchiamo lo stesso vino (nome uguale, stessa cantina), con gli stessi litri e un’annata che disti al massimo 2 anni, da <strong>Tannico</strong> ({n_offerte_vini["Tannico"]} offerte) e dalle enoteche online <strong>Callmewine</strong> ({n_offerte_vini["Callmewine"]}), <strong>Millesima</strong> ({n_offerte_vini["Millesima"]}) e <strong>Xtrawine</strong> ({n_offerte_vini["Xtrawine"]}); prezzi con IVA, divisi per i litri. Sono {n_vini_conf} vini confrontabili, {n_vini_disp} dei quali in vendita oggi in almeno un negozio. Il confronto è con l’offerta più bassa fra i negozi che la vendono, preferendo la stessa annata di Peck; se l’unica offerta è di un’altra annata, l’anno è scritto (nella pagina del vino, in «Prezzi altrove», ci sono tutte le offerte). Millesima è il sito francese: il prezzo è quello con IVA per la consegna in Francia. Zachys (americano, prezzi senza imposte) e le casse, i set e gli en primeur non si confrontano mai. Se nessun negozio ha la bottiglia in vendita lo diciamo e non la mettiamo nell’Angolo delle occasioni.</li>
<li><strong>Un altro produttore.</strong> Per {n_alt} prodotti abbiamo trovato la stessa ricetta venduta da un’azienda <em>diversa</em> da quella che la fa per Peck. Sta in un riquadro a parte («Un’alternativa da un altro produttore»), non dice mai «stesso prodotto» e non entra nell’Angolo delle occasioni; in «Prezzi confrontati» ha la sua voce (filtro «Da un altro produttore»).</li>
<li><strong>Prezzi confrontati.</strong> La pagina <a href="../prezzi/">Prezzi confrontati</a> raccoglie tutti i confronti, cibo e vino, per categoria, con la differenza al kg o al litro (la barra è verde se Peck costa meno, neutra entro il ±{soglia_t}%, calda se costa di più) e i filtri per categoria, fonte e livello. Per il vino, «stesso prodotto» vuol dire stessa annata. Si disegna con JavaScript da un file di dati. Dentro ci sono anche i prodotti del delivery che non sono nello shop online e non hanno una pagina nostra.</li>
<li><strong>L’Angolo delle occasioni.</strong> Elenca i confronti in cui Peck costa meno, o al massimo il {soglia_t}% in più: la soglia è la costante <code>SOGLIA_OCCASIONE</code> in <code>src/sito.py</code> ed è una nostra scelta. Sotto, chiuso, ci sono i 20 casi in cui Peck costa di più.</li>
<li><strong>Il valore spacchettato.</strong> In ogni pagina di box, «Valore spacchettato» somma i prezzi dei singoli prodotti di cui abbiamo un prezzo (delivery di Peck, schede singole dello shop, carta dell’enoteca, siti dei produttori) e li mette accanto al prezzo della pagina, dicendo sempre la <em>copertura</em>: quanti prodotti su quanti hanno un prezzo. Sotto il 50% non calcoliamo nessuna percentuale, perché la somma è solo una piccola parte; in nessun caso la differenza è un ricarico, perché non contiene confezione, nastri e servizio né i prodotti senza prezzo. Per questo non la chiamiamo né risparmio né rincaro.</li>
<li><strong>Quando si aggiorna.</strong> I prezzi dei produttori e di Tannico sono pensati per essere ricontrollati una volta a settimana, in automatico. I prezzi di Peck (servizio delivery e carta dell’enoteca) invece si aggiornano solo a mano: se Peck cambia un prezzo, qui resta quello vecchio finché qualcuno non ricontrolla. Ogni confronto riporta la data in cui è stato fatto.</li>
</ul>

"""
    return f"""<article class="testo-lungo">
<h1>Come funziona</h1>
<p class="intro">Peck Tracker è un progetto di appassionati. Sembra un catalogo, ma non vende niente: dice chi fa i prodotti che Peck Milano vende online e che cosa c’è nella carta dei vini della sua enoteca.</p>
<p><strong>{H(AVVISO)}</strong></p>

<h2>Da dove vengono i dati</h2>
<ul>
<li><strong>Lo shop. </strong>Abbiamo letto le {len(box)} pagine dello shop online di Peck e, di ogni prodotto, solo la frase in cui Peck scrive dove è prodotto o confezionato ("Prodotto in via…", "Confezionato da…", il bollo CE degli stabilimenti). Non copiamo ingredienti né descrizioni.</li>
<li><strong>Le aziende. </strong>Per ogni indirizzo, bollo CE o produttore nominato abbiamo cercato a mano, sul web, chi c’è dietro. Ogni riga ha la sua fonte (registri delle imprese, siti ufficiali, gli elenchi europei degli stabilimenti riconosciuti). Non è un lavoro fatto da un programma.</li>
<li><strong>Il delivery. </strong>Il servizio delivery di Peck ha un catalogo con prezzi e foto. Per i {n_delivery} prodotti della Dispensa che abbiamo ritrovato lì (nome e formato controllati a mano, uno per uno) mostriamo prezzo e foto, scrivendo ogni volta «{FONTE_DELIVERY}»; se il formato non è lo stesso dello shop (per esempio nel delivery si compra a peso) lo diciamo. La foto è collegata, non copiata. Il resto del catalogo del delivery non è pubblicato qui, e i prezzi cambiano.</li>
<li><strong>L’enoteca. </strong>La carta dei vini è quella che l’enoteca di Peck pubblica su Winerim: {num(M["n_vini"])} vini di {M["n_cantine"]} cantine. Di ogni vino teniamo i dati strutturati (tipo, uve, formati e prezzi, profilo di degustazione da 0 a 5, qualche indicazione di massima); i testi descrittivi di Winerim non sono copiati: per quelli c’è il link «Scheda completa in enoteca».</li>
<li><strong>I punteggi. </strong>I bottoni Vivino e Wine-Searcher aprono una ricerca sui loro siti per quel vino. Non copiamo nessun punteggio: il vino cercato potrebbe non essere esattamente lo stesso (annata, formato), da controllare lì. Se su Tannico c’è solo un altro formato (per esempio la 0,75 L per un magnum) il bottone lo dice.</li>
<li><strong>Tannico. </strong>I link a Tannico vengono dal catalogo pubblico dei prodotti di Tannico, abbinato per nome ai nostri vini: {sum(1 for w in V['vini'] if 'tn' in w)} link diretti alla scheda (controllati a campione); per tutti gli altri il bottone «Cerca su Tannico» apre una ricerca sul loro sito.</li>
<li><strong>I voti. </strong>Vengono da tre fonti, tenute separate perché non sono la stessa cosa: i <em>critici</em> (punteggi su 100), il <em>giudizio di Tannico</em> (su 100, è il punteggio del negozio) e la <em>media degli utenti</em> (stelle da 1 a 5). Sui {num(VOTI["tot"])} vini della carta, {num(VOTI["bollini"])} hanno almeno un bollino: {num(VOTI["c"])} con un critico, {num(VOTI["t"])} con il solo giudizio di Tannico, {num(VOTI["u"])} con le sole stelle degli utenti. Registriamo solo i numeri (e il nome di chi ha dato il voto), mai il testo delle recensioni.
<ul>
<li><strong>Tannico.</strong> «Giudizio di Tannico» e punteggi dei critici (Parker, Suckling, Decanter…) come li riporta la scheda del vino abbinato, raccolti il {data_lunga(VOTI["data"])} per {VOTI["n"]} vini ({VOTI["tcrit"]} con almeno un critico). I prezzi di Tannico compaiono solo nel confronto con quelli di Peck (vedi «Confronto prezzi»).</li>
<li><strong>Wine Enthusiast.</strong> {VOTI["we"]} vini, con il punteggio su 100 e il nome di chi ha degustato. Vengono dalla raccolta «Wine Reviews» di Zack Thoutt (Kaggle, recensioni del 2017), licenza <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener noreferrer">CC BY-NC-SA 4.0{sr_nuova_scheda()}</a>: si possono riusare citando la fonte, <strong>solo senza scopo commerciale</strong> e condividendo con la stessa licenza (questo sito è un progetto senza scopo di lucro e senza niente in vendita). Del testo delle recensioni non copiamo niente.</li>
<li><strong>X-Wines (utenti).</strong> {VOTI["xw"]} vini, con la media dei voti a stelle e il numero di voti (mai meno di 10). È un dataset di ricerca di de Azambuja, Morais e Filipe (2023, <a href="{XW_DOI}" target="_blank" rel="noopener noreferrer">Big Data and Cognitive Computing 7(1), 20{sr_nuova_scheda()}</a>), licenza CC0 (libero). I voti sono di utenti raccolti sul web nel 2022; gli autori non dicono da quale sito. Sono gusti di chi beve, non giudizi di critici.</li>
{riga_en}</ul>
Il bollino segue questa priorità: un critico su 100 (prima Tannico, poi le enoteche, poi Wine Enthusiast), altrimenti il giudizio di Tannico, altrimenti gli utenti (solo con almeno 10 voti). Il voto si usa solo se l’annata è quella di Peck o dista al massimo 2 anni (per i vini senza annata, solo se manca da entrambe le parti); se è diversa, l’anno è scritto accanto al voto. Per le annate più lontane i voti di Tannico restano nella pagina del vino come riferimento, senza bollino; quelli delle altre fonti non li usiamo. Nell’Enoteca «Con voto» include tutte le fonti, «solo critici» tiene solo chi ha un critico; l’ordine per voto non mischia le scale (critici, poi Tannico, poi utenti; le stelle sono moltiplicate per 20 solo per metterle in ordine tra loro).</li>
</ul>

{sezione_confronto}{sezione_datate}
<h2>Quanto siamo sicuri</h2>
<p>Ogni azienda ha un’etichetta:</p>
<ul>
<li>{badge("certa")} una fonte mostra proprio quell’indirizzo o quel codice con quell’azienda.</li>
<li>{badge("probabile")} l’indizio è forte ma indiretto.</li>
<li>{badge("non trovata")} non siamo riusciti a risalire all’azienda.</li>
<li>{badge("peck")} Peck scrive di aver fatto o confezionato il prodotto nella sua sede di via Spadari 9, a Milano.</li>
<li>{badge("nessuna")} nella scheda del prodotto Peck non scrive dove è fatto.</li>
</ul>
<p>Sui {len(dispensa)} prodotti della dispensa: {conta["certa"]} hanno un’azienda certa, {conta["probabile"]} probabile, {conta["non trovata"]} non trovata, {conta["peck"]} sono fatti da Peck stessa e per {conta["nessuna"]} Peck non indica nulla. Se un prodotto ha più luoghi, l’etichetta mostra quella più sicura.</p>

<h2>I limiti, detti chiaramente</h2>
<ul>
<li>È una fotografia del {data_lunga(M["data"])}. Prezzi, box e vini cambiano: oggi il catalogo è quello delle “Selezioni Natalizie”.</li>
<li>Contiamo solo quello che Peck vende online, non quello che c’è nei suoi negozi.</li>
<li>L’indirizzo che Peck scrive può essere quello di chi confeziona, non di chi fabbrica. Peck usa “prodotto in”, “prodotto e confezionato in”, “confezionato da” senza spiegare la differenza: noi teniamo la parola e la frase esatta.</li>
<li>Molte aziende lavorano per conto terzi: fanno il prodotto che Peck vende con il suo nome. Non vuol dire che Peck non c’entri: dice solo chi lo fabbrica.</li>
<li>Il bollo CE dice dove sta lo stabilimento, non di chi è: l’azienda va cercata negli elenchi. Alcuni codici non sono bolli sanitari.</li>
<li>Le righe “non trovata” sono dove la ricerca non è arrivata; si possono riprovare. “Nessuno shop online” vuol dire solo che non l’abbiamo trovato sul sito ufficiale.</li>
<li>I testi di Peck hanno refusi (per esempio “Ortobello” per “Orbetello”). Le frasi sono copiate com’erano; dove due scritture indicano chiaramente lo stesso posto, le abbiamo unite.</li>
<li>Quasi nessun prodotto della Dispensa ha una foto tutta sua nello shop: Peck mostra solo la foto della box. Per {n_foto_delivery} prodotti la foto viene dal servizio delivery; per {n_ritagli} c’è un <em>ritaglio</em> della foto della box in cui il prodotto si vede (un ingrandimento fatto con il solo CSS: la foto resta sul server di Peck e non è copiata; se il prodotto è stato riconosciuto per esclusione lo scriviamo); per gli altri c’è un nostro disegno, scelto in base al nome. Se la foto non si carica, torna il disegno.</li>
<li>Nell’enoteca l’intestazione della carta parla di 1.005 cantine, ma l’elenco pubblico ne mostra {M["n_cantine"]} ({num(M["n_vini"])} vini). Non sappiamo perché: forse sono vini archiviati o nascosti.</li>
<li>Il profilo di degustazione, la gradazione, la temperatura di servizio e le finestre «da bere» sono indicazioni della scheda dell’enoteca, spesso di massima (per molti vini la gradazione è identica): non sono misure.</li>
<li>I vini senza prezzo nella carta compaiono con “prezzo non indicato”.</li>
<li>Il formato di ogni prezzo (Bottiglia, Magnum, Jeroboam…) è scritto in litri, presi dalla capacità indicata da Winerim o, se c’è, dal formato scritto nel nome del vino («Magnum 1,5 LT», «37,5 cl»): quando i due non coincidono vale il nome. Succede in 53 casi (per esempio 27 magnum registrati come bottiglie da 0,75 L) e la nota lo dice. Per 87 vini senza prezzo, quasi tutti di Borgogna, il formato non è indicato e resta vuoto. Un dubbio aperto: il Barbaresco Riserva Rabajà 2019 di Cortese è registrato come magnum ma il nome dice «Rehoboam 5 LT»; l’abbiamo messo a 5 litri, da verificare. I nomi dei formati cambiano da regione a regione (3 litri sono un Jeroboam in Champagne e un Doppio Magnum a Bordeaux): contano i litri. Nell’elenco ordinato per prezzo si confrontano formati uguali.</li>
<li>Tutti i voti sono abbinati ai vini per nome (cantina, nome, annata) e l’abbinamento può sbagliare; quelli incerti li abbiamo scartati. Se l’annata è diversa i voti non sono quelli della bottiglia di Peck. I voti dei critici su Tannico possono riferirsi all’annata “corrente” della scheda. Le stelle degli utenti sono medie di gusti, non giudizi tecnici, e arrivano da un dataset del 2022. Non tutti i vini hanno un voto.</li>
</ul>
{sezione_link}
<h2>Come sono scelte le categorie</h2>
<p>Le categorie dei prodotti sono decise da un programma che cerca alcune parole nel nome del prodotto: la prima categoria che trova vince. Non è una classificazione ufficiale e qualche prodotto può finire nella categoria sbagliata. Le parole sono queste (il resto va in «altro»):</p>
<div class="tab-scorri"><table class="tab"><thead><tr><th>Categoria</th><th>Parole cercate nel nome</th></tr></thead><tbody>{righe_cat}</tbody></table></div>

<h2 id="ritagli">I ritagli dalle foto delle box</h2>
<p>Per i prodotti senza una foto propria e non trovati nel delivery, dove possibile mostriamo il pezzo della foto della box in cui si vedono. I rettangoli (posizione e misura in frazioni della foto, con «alta» o «media» certezza) sono scelti a mano e stanno in <code>data/ritagli.csv</code>; il ritaglio è un riquadro quadrato con la foto collegata, ingrandita e spostata dal CSS, e sotto c’è sempre il disegno. «Media» vuol dire che il prodotto è stato riconosciuto per esclusione o dal colore, non dal nome sull’etichetta: la didascalia lo dice.</p>

<h2>Come sono scelti i disegni</h2>
<p>I prodotti senza una foto tutta loro (e senza ritaglio, e non trovati nel delivery) hanno un disegno. Anche qui decide un programma: cerca nel nome le parole qui sotto (vince la prima riga che trova); se non ne trova, usa il disegno della categoria. Chi ha una foto propria di Peck (panettoni, pandoro, veneziana, salmone, frutta disidratata) tiene la foto.</p>
<div class="tab-scorri"><table class="tab"><thead><tr><th>Disegno</th><th>Parole cercate nel nome</th><th>Categoria</th></tr></thead><tbody>{righe_disegni}</tbody></table></div>

<h2>Foto, caratteri e riservatezza</h2>
<p>I disegni della Dispensa sono nostri; le foto sono quelle delle pagine di Peck e del suo servizio delivery.</p>
<p>Le foto non sono copiate su questo sito: il tuo browser le carica dai server di Peck (shop.peck.it e delivery.peck.it) e di Winerim. Per questo quei server vedono la tua visita, e se cambiano o tolgono una foto qui compare un riquadro vuoto. I caratteri (Raleway e Playfair Display, gli stessi del sito di Peck) vengono da Google Fonts. Questo sito non usa cookie né statistiche. Il logo di Peck non è mai pubblicato qui.</p>

<h2>Dati e codice</h2>
<p>Tutto è pubblico: le tabelle (si aprono bene anche con Excel) e i programmi che le costruiscono.</p>
<ul>
<li><a href="{REPO}" target="_blank" rel="noopener noreferrer">Il progetto su GitHub{sr_nuova_scheda()}</a></li>
{li_csv}
</ul>
<p>Hai trovato un errore o sai chi fa un prodotto “non trovato”? Apri una segnalazione su GitHub: <a href="{REPO}/issues" target="_blank" rel="noopener noreferrer">segnalazioni{sr_nuova_scheda()}</a>.</p>
</article>"""


def pagina_404():
    corpo = f"""<div class="vuoto"><h1>Pagina non trovata</h1>
<p>Questo indirizzo non esiste (o i dati sono stati aggiornati).</p>
<p><a class="bottone" href="{PREFISSO_SITO}dispensa/">Vai alla dispensa</a></p></div>"""
    return layout(titolo="Pagina non trovata", descr="Questa pagina non esiste. " + AVVISO, corpo=corpo,
                  rel="", sezione="", assoluto=True)


# ---------------------------------------------------------------------------
# Scrittura delle pagine
# ---------------------------------------------------------------------------

CARTELLE_GENERATE = ["dispensa", "prodotto", "box", "produttori", "produttore", "enoteca", "cantina",
                     "vino", "occasioni", "prezzi", "come-funziona"]
FILE_GENERATI = ["index.html", "404.html", "vini.json", "prezzi.json", "dati.json", "sitemap.xml", "robots.txt"]


def pulisci_docs():
    DOCS.mkdir(exist_ok=True)
    for c in CARTELLE_GENERATE:
        shutil.rmtree(DOCS / c, ignore_errors=True)
    for f in FILE_GENERATI:
        (DOCS / f).unlink(missing_ok=True)


def scrivi_json(nome, dati):
    testo = json.dumps(dati, ensure_ascii=False, separators=(",", ":"))
    (DOCS / nome).write_text(testo, encoding="utf-8")
    return len(testo.encode("utf-8"))


def scrivi_sito():
    dispensa, box, produttori, st = costruisci_cibo()
    box_per_nome = {nz(b["nome"]): b["id"] for b in box}
    V, stv = costruisci_vini(box_per_nome)
    az, items, boxes = prepara_cibo(dispensa, box, produttori)
    righe_conf = collega_confronti(dispensa, az)
    CV = carica_offerte_vini()
    alternative = carica_alternative(dispensa)
    storico = carica_storico(dispensa, az, st)
    BV = carica_box_valore(box)
    righe_prezzi = costruisci_righe_prezzi(righe_conf, alternative, V, CV)
    riep = riepilogo_prezzi(righe_prezzi)
    chiavi_conf = Counter(nome_azienda_chiave(x["azienda"], "") for x in righe_prezzi if x["tipo"] == "c" and x.get("azienda"))
    for z in produttori:
        z["n_conf"] = chiavi_conf.get(nome_azienda_chiave(z["ragione"], ""), 0) if z["trovata"] else 0
    M = V["meta"]
    pulisci_docs()

    # --- Dispensa (home e /dispensa/)
    desc_dispensa = (f"I {len(dispensa)} prodotti alimentari che Peck vende online: per ognuno chi lo fa e dove, "
                     f"e quanto siamo sicuri. {AVVISO}")
    scrivi_pagina("dispensa", layout(titolo="Dispensa", descr=desc_dispensa, rel="dispensa", sezione="dispensa",
                                     corpo=pagina_dispensa(dispensa, az, "dispensa")), "dispensa")
    scrivi_pagina("", layout(titolo="Dispensa", descr=desc_dispensa, rel="", sezione="dispensa", home=True,
                             corpo=pagina_dispensa(dispensa, az, "", home=True)), "home")

    # --- Prodotti
    for it in dispensa:
        corpo, descr = pagina_prodotto(it, az, boxes, "../../")
        scrivi_pagina(f"prodotto/{it['id']}", layout(titolo=it["nome"], descr=descr, corpo=corpo,
                                                     rel=f"prodotto/{it['id']}", sezione="dispensa"), "prodotto")

    # --- Box
    scrivi_pagina("box", layout(titolo="Box regalo", sezione="box", rel="box", corpo=pagina_box_lista(box, items),
                                descr=f"Le {len(box)} pagine dello shop di Peck, “spacchettate”: ogni prodotto con chi lo fa. {AVVISO}"),
                  "box (elenco)")
    for b in box:
        corpo, descr = pagina_box(b, items, az, "../../", BV.get(b["id"]))
        scrivi_pagina(f"box/{b['id']}", layout(titolo=b["nome"], descr=descr, corpo=corpo,
                                               rel=f"box/{b['id']}", sezione="box"), "box")

    # --- Produttori
    scrivi_pagina("produttori", layout(titolo="Produttori", sezione="produttori", rel="produttori",
                                       corpo=pagina_produttori_lista(produttori),
                                       descr=f"Le {len(produttori)} aziende dietro i prodotti che Peck vende, con le fonti. {AVVISO}"),
                  "produttori (elenco)")
    for z in produttori:
        corpo, descr = pagina_produttore(z, items, az, "../../")
        scrivi_pagina(f"produttore/{z['id']}", layout(
            titolo=z["nome"] if (z["trovata"] or z["id"] == "peck") else "Azienda non trovata", descr=descr,
            corpo=corpo, rel=f"produttore/{z['id']}", sezione="produttori"), "produttore")

    # --- Enoteca
    corpo, descr = pagina_enoteca(V)
    scrivi_pagina("enoteca", layout(titolo="Enoteca", descr=descr, corpo=corpo, rel="enoteca", sezione="enoteca"),
                  "enoteca (elenco)")
    for c in V["cantine"]:
        corpo, descr = pagina_cantina(c, boxes, "../../")
        scrivi_pagina(f"cantina/{c['id']}", layout(titolo=c["nome"], descr=descr, corpo=corpo,
                                                   rel=f"cantina/{c['id']}", sezione="enoteca"), "cantina")
    corr = vini_correlati(V["vini"])
    for w in V["vini"]:
        corpo, descr, titolo = pagina_vino(w, V, "../../", corr[w["id"]], CV)
        scrivi_pagina(f"vino/{w['d']}", layout(titolo=titolo, descr=descr, corpo=corpo,
                                               rel=f"vino/{w['d']}", sezione="enoteca"), "vino")

    # --- Angolo delle occasioni
    corpo, descr = pagina_occasioni(voci_confronto(righe_prezzi, "../"), "../")
    scrivi_pagina("occasioni", layout(titolo="Angolo delle occasioni", descr=descr, corpo=corpo, rel="occasioni",
                                      sezione="occasioni"), "occasioni")

    # --- Prezzi confrontati
    corpo, descr = pagina_prezzi(righe_prezzi, riep, "../")
    scrivi_pagina("prezzi", layout(titolo="Prezzi confrontati", descr=descr, corpo=corpo, rel="prezzi", sezione="prezzi"), "prezzi")
    n_prezzi_json = scrivi_json("prezzi.json", json_prezzi(righe_prezzi, riep))

    # --- Come funziona, 404
    scrivi_pagina("come-funziona", layout(
        titolo="Come funziona", sezione="come-funziona", rel="come-funziona",
        descr=f"Da dove vengono i dati di Peck Tracker, quanto siamo sicuri e quali sono i limiti. {AVVISO}",
        corpo=pagina_come_funziona(dispensa, box, produttori, V, M, righe_conf, CV, storico, az, riep, len(alternative), len(BV))), "come funziona")
    (DOCS / "404.html").write_text(pagina_404(), encoding="utf-8")

    # --- dati per i filtri dell'enoteca, sitemap, robots
    n_json = scrivi_json("vini.json", json_vini(V))
    oggi = date.today().isoformat()
    urls = "".join(f"<url><loc>{URL_SITO}{rel + '/' if rel else ''}</loc><lastmod>{oggi}</lastmod></url>\n" for rel in PAGINE)
    (DOCS / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n",
                                      encoding="utf-8")
    (DOCS / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {URL_SITO}sitemap.xml\n", encoding="utf-8")
    st["storico"] = storico
    st["righe_prezzi"] = righe_prezzi
    st["riep"] = riep
    st["prezzi_json"] = n_prezzi_json
    st["box_valore"] = len(BV)
    st["alternative"] = len(alternative)
    return dispensa, box, produttori, V, st, stv, n_json


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dispensa, box, produttori, V, st, stv, n_json = scrivi_sito()
    print(f"pagine scritte: {sum(CONTA.values())}  (+ 404.html)")
    for k, n in CONTA.items():
        print(f"   {k:20} {n}")
    print(f"vini.json: {n_json/1024:.0f} KB   prezzi.json: {st['prezzi_json']/1024:.0f} KB")
    print("ritagli usati:", st["ritagli"], " senza box:", st["ritagli_senza_box"], " non usati:", st["ritagli_non_usati"])
    print("confronti:", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in st["riep"].items()})
    print("storico:", len(st["storico"]), " alternative:", st["alternative"], " box con valore:", st["box_valore"])
    print(f"elementi (dispensa): {st['elementi']}   box/pagine: {st['box']}   produttori: {st['produttori']}"
          f"   vini: {V['meta']['n_vini']}   cantine: {V['meta']['n_cantine']}")
    print(f"righe di origine con un luogo/codice: {st['righe_con_luogo']}, abbinate a un'azienda: "
          f"{st['righe_abbinate']}  ({st['come_abbinate']})")
    print("stato degli elementi:", st["stati_elementi"])
    print("categorie:", st["categorie"])
    print("foto elementi:", dict(st["foto_elementi"]), " foto box:", st["foto_box"], "/", st["box"])
    print("disegni della dispensa:", dict(st["disegni"].most_common()))
    mancanti = sorted(d for d in st["disegni"] if d in DISEGNI_NOMI and not (DOCS / "disegni" / f"{d}.svg").exists())
    if mancanti:
        print("ATTENZIONE, disegni che mancano in docs/disegni/:", mancanti)
    if st["approssimati"]:
        print("abbinamenti approssimati (da controllare):")
        for a, b in sorted(set(st["approssimati"])):
            print("   ", a, "->", b)
    if st["box_conteggio_diverso"]:
        print("box con numero di elementi diverso da prodotti.csv:", st["box_conteggio_diverso"])
    if st["aziende_non_usate"]:
        print("righe di aziende.csv non usate da nessun elemento:", st["aziende_non_usate"])
    print("vini senza foto:", stv["senza_foto"], " link diversi dal solito:", stv["link_diversi"],
          " cantine mancanti in cantine.csv:", stv["mancanti"], " vini senza prezzo:", V["meta"]["senza_prezzo"])
    print("vini con profilo di degustazione:", stv["con_profilo"], " con altri dati (gradazione, abbinamenti...):",
          stv["con_dettagli"])
    esclusi = sorted(u for u, e in LINK.esiti.items() if e in ("rotto", "dominio_parcheggiato"))
    print("link marcati rotti (non diventano bottoni):", len(esclusi))


if __name__ == "__main__":
    main()
