"""Legge data/raw/ e scrive le tabelle in data/.

Uso:  python -I src/extract.py

Scrive:
  data/prodotti.csv        una riga per pagina prodotto dello shop
  data/elementi.csv        una riga per ogni frase di origine di ogni elemento
                           (un prodotto singolo = 1 elemento; una box = un elemento per
                           ogni prodotto contenuto). Un elemento senza nessuna frase di
                           origine ha comunque una riga, con i campi di origine vuoti.
  data/indirizzi.csv       indirizzi di produzione unici, con quante volte compaiono
  data/altre_origini.csv   origini senza indirizzo: bolli CE, produttori nominati, solo paese

Non si salvano ne' ingredienti ne' descrizioni: solo le frasi di origine.
"""
import csv
import difflib
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
BASE = "https://shop.peck.it"

# ---------------------------------------------------------------- frasi di origine

# verbo che apre una frase di origine (maiuscola iniziale o tutto maiuscolo)
VERBI = (r"(?:Prodott[oa]|PRODOTT[OA]|Confezionat[oae]|CONFEZIONAT[OAE]|Imbottigliat[oa]|"
         r"IMBOTTIGLIAT[OA]|Spumantizzat[oa]|SPUMANTIZZAT[OA]|Stagionat[oa]|Elaborat[oa]|"
         r"Lavorat[oa]|Realizzat[oa]|Distribuit[oa])")
RE_TRIG = re.compile(
    r"\b" + VERBI + r"(?:\s+e\s+(?:confezionat|imbottigliat|stagionat|CONFEZIONAT|IMBOTTIGLIAT)[oae]+)?"
    r"(?=[\s:])")
# dopo il verbo, queste parole indicano che NON e' una frase di origine
RE_NO_ORIGINE = re.compile(
    r"^\s*(?:dolciari|da forno|alimentar|a base|con\b|secondo|tradizional|artigianal|"
    r"in atmosfera protettiva(?!\s+da))", re.I)
# dopo il verbo ci vuole una preposizione, oppure un nome/indirizzo che inizia con maiuscola o cifra
RE_INIZIO_OK = re.compile(r"^\s*:?\s*(?:(?:in|da|presso|per)\b|[A-Z0-9])")

# fine frase: queste parole aprono la frase successiva
RE_STOP = re.compile(
    r"\s+(?=(?:Conservare|Conservazione|Durata|Consumare|Peso minimo|Una volta|Dopo l|"
    r"Preparazione|Pu\S{1,2}\s+contenere|Origine|Ingredienti|Dichiarazione|Certificato|"
    r"Da consumarsi)\b)")
# "PECK S.P.A." dopo l'indirizzo di produzione: e' il titolare del marchio, non il luogo.
# Non vale se e' preceduto da "per" ("Spumantizzato da X per PECK S.P.A.").
RE_PECK_STOP = re.compile(r"(?<!per)(?<!PER)\s+PECK\s*S\.?\s?P\.?\s?A", re.I)

# nome azienda in maiuscolo + forma giuridica + virgola ("NONINO DISTILLATORI S.R.L., Via ...")
RE_AZIENDA = re.compile(r"\b([A-Z][A-Z0-9'&.\- ]{3,}?\s(?:S\.R\.L\.?|S\.P\.A\.?|S\.A\.S\.?|SRL|SPA))\s*,")

# sigle che finiscono con un punto ma non chiudono la frase
ABBREV = {"s", "v", "loc", "str", "reg", "fraz", "soc", "agr", "n", "sns", "srl", "sa", "spa",
          "vp", "zi", "cda", "c", "ing", "dott", "dr", "f", "lli", "p", "pzza", "e", "sas", "snc",
          "cciaa", "arg", "sin", "dx", "ss", "sp", "km"}

PAESI = {"italia": "Italia", "italy": "Italia", "francia": "Francia", "spagna": "Spagna",
         "germania": "Germania", "scozia": "Scozia", "svizzera": "Svizzera",
         "portogallo": "Portogallo"}
PREFISSO_PAESE = {"IT": "Italia", "ES": "Spagna", "FR": "Francia", "DE": "Germania",
                  "AT": "Austria", "PT": "Portogallo", "NL": "Paesi Bassi", "BE": "Belgio"}

# parole con cui comincia un indirizzo (serve a separare un nome di azienda dall'indirizzo)
RE_VIA = re.compile(
    r"\b(?:via|viale|corso|piazza|piazzale|strada|str\.?|contrada|c\.da|zona|localit[aà]|loc\.?|"
    r"frazione|fraz\.?|vicolo|largo|regione|reg\.?|borgo|lungo|calle|vial)(?=[\s/.])|\bC/(?=[A-Za-z])",
    re.I)
CIVICO = r"\d+[A-Za-z]{0,2}(?![A-Za-z])(?:/\d+)?"


def chiudi_frase(testo, inizio, dopo_verbo):
    """Da `inizio` cerca dove finisce la frase e restituisce l'indice di fine.
    `dopo_verbo` e' la posizione subito dopo il verbo ("Prodotto e confezionato")."""
    n = len(testo)
    fine = n
    m = RE_STOP.search(testo, inizio)
    if m:
        fine = min(fine, m.start())
    # +8: non tagliare "Prodotto e confezionato da Peck S.p.a"
    m = RE_PECK_STOP.search(testo, dopo_verbo + 8)
    if m:
        fine = min(fine, m.start())
    # punto che chiude la frase (non una sigla)
    for m in re.finditer(r"\.(?=\s|$)", testo[:fine]):
        if m.start() < inizio:
            continue
        prima = testo[:m.start()].split()
        tok = re.sub(r"[^A-Za-z]", "", prima[-1]).lower() if prima else ""
        if tok in ABBREV:
            continue
        resto = testo[m.end():].lstrip()
        if resto == "" or resto[0].isupper() or resto[0] in "-–" or resto[0].isdigit():
            fine = min(fine, m.start())
            break
    return fine


def estrai_frasi(righe):
    """Restituisce le frasi di origine (testo verbatim) trovate nelle righe di un elemento."""
    # le righe che finiscono con "," o ":" proseguono sulla riga dopo
    testo = ""
    for riga in righe:
        riga = re.sub(r"[ \t]+", " ", riga).strip().lstrip("\\ ")
        if testo and testo.rstrip().endswith((",", ":")):
            testo = testo.rstrip() + " " + riga
        elif testo:
            testo += "\n" + riga
        else:
            testo = riga
    frasi, spans = [], []
    pos = 0
    while True:
        m = RE_TRIG.search(testo, pos)
        if not m:
            break
        dopo = testo[m.end():]
        if RE_NO_ORIGINE.match(dopo) or not dopo.strip() or not RE_INIZIO_OK.match(dopo):
            pos = m.end()
            continue
        fine = chiudi_frase(testo, m.start(), m.end())
        frase = re.sub(r"\s+", " ", testo[m.start():fine]).strip().rstrip(".;, ")
        if len(frase) > len(m.group(0)) + 1:
            frasi.append(frase)
            spans.append((m.start(), fine))
        pos = max(fine, m.end())
    # azienda con forma giuridica e indirizzo, senza verbo ("NONINO DISTILLATORI S.R.L., Via ...")
    for m in RE_AZIENDA.finditer(testo):
        if "PECK" in m.group(1).upper() or re.search(r"[A-Z]{3,}\.\s", m.group(1)):
            continue
        if any(a <= m.start() < b for a, b in spans):
            continue
        fine = chiudi_frase(testo, m.start(), m.end())
        frasi.append(re.sub(r"\s+", " ", testo[m.start():fine]).strip().rstrip(".;, "))
    return frasi


# ---------------------------------------------------------------- analisi di una frase

def estrai_bollo(testo):
    """Cerca un bollo/codice di stabilimento (es. 'IT 3 L CE', 'CE IT B0170').
    Ritorna (bollo, testo_senza_bollo)."""
    m = re.search(r"\bCE\s+(IT|ES|FR|DE)\s?[0-9A-Z]\w*\b", testo)
    if m:
        return m.group(0).strip(), (testo[:m.start()] + " " + testo[m.end():]).strip()
    for m in re.finditer(r"\b(IT|ES|FR|DE|AT|PT|NL|BE)(?=[\s0-9])\s?", testo):
        resto = testo[m.end():]
        presi, lung = [], 0
        for t in re.finditer(r"\S+", resto):
            parola = t.group(0)
            pulita = parola.rstrip(".,;)")
            if not re.fullmatch(r"[0-9A-Z./\-]+", pulita):
                break
            if not (re.search(r"\d", pulita) or len(pulita) <= 2 or pulita in ("CE", "UE")):
                break
            presi.append(pulita)
            lung = t.end()
            if pulita in ("CE", "UE") or parola.endswith("."):
                break
        if not presi or not re.search(r"\d", " ".join(presi)):
            continue
        bollo = (m.group(1) + " " + " ".join(presi)).strip()
        return bollo, (testo[:m.start()] + " " + testo[m.end() + lung:]).strip()
    m = re.search(r"\bIT[0-9]{2}[A-Z0-9]{6,}\b", testo)
    if m:
        return m.group(0), (testo[:m.start()] + " " + testo[m.end():]).strip()
    return "", testo


def spezza_indirizzo(s, ha_via):
    """Prova a separare 'via X 9, 12345 Comune (PR)' in indirizzo, cap, comune, provincia.
    Ritorna (dict, avvertenze)."""
    avv = []
    out = {"indirizzo": "", "cap": "", "comune": "", "provincia": "", "paese": ""}
    s = s.strip(" ,;-–:.")
    # paese in coda
    m = re.search(r"[,\-–]?\s*\b(Italia|Italy)\b\.?\s*$", s, re.I)
    if m:
        out["paese"] = "Italia"
        s = s[:m.start()].strip(" ,;-–")
    # provincia tra parentesi (il testo che segue, tipo "- Sardegna", si scarta)
    prov = re.search(r"\(\s*([A-Za-z][A-Za-z ]{1,20}?)\s*\)", s)
    if prov:
        p = prov.group(1)
        out["provincia"] = p.upper() if len(p) == 2 else p
        coda = s[prov.end():].strip(" ,;-–")
        s = s[:prov.start()].strip()
        if re.match(r"\d{5}\b", coda):          # "(IM) 18018 Regione ..." : il resto segue
            s = s + " " + coda
        elif coda and coda.split()[0].lower() not in ("sardegna", "sicilia", "italia"):
            avv.append("testo dopo la provincia: " + coda)
    # cap (5 cifre), eventualmente con prefisso D-
    cap = re.search(r"\b(?:D-)?(\d{5})\b", s)
    if cap:
        out["cap"] = cap.group(1)
        if cap.group(0).startswith("D-"):
            out["paese"] = "Germania"
        s = s[:cap.start()] + " , " + s[cap.end():]
    # separatori: virgole e trattini staccati; parti vuote scartate
    parti = [p.strip(" ,;-–") for p in re.split(r"\s*,\s*|\s+[-–]\s+", s)]
    parti = [p for p in parti if p]
    # provincia scritta in maiuscolo senza parentesi ("Langhirano PR", ", PV")
    if not out["provincia"] and parti:
        m = re.fullmatch(r"([A-Z]{2})", parti[-1])
        if m and len(parti) > 1:
            out["provincia"] = m.group(1)
            parti = parti[:-1]
        else:
            m = re.search(r"\s([A-Z]{2})$", parti[-1])
            if m and len(parti[-1].split()) > 1 and parti[-1].split()[-1] not in ("VP",):
                out["provincia"] = m.group(1)
                parti[-1] = parti[-1][:m.start()]
    # i numeri civici staccati si riattaccano alla via
    uniti = []
    for p in parti:
        mm = re.match(r"^(" + CIVICO + r")\s*(.*)$", p)
        if uniti and mm:
            uniti[-1] = uniti[-1] + " " + mm.group(1)
            if mm.group(2):
                uniti.append(mm.group(2))
        elif uniti and re.fullmatch(r"(sns|snc|s\.n\.c\.|s\.n\.)", p, re.I):
            uniti[-1] = uniti[-1] + " " + p
        else:
            uniti.append(p)
    parti = uniti
    if len(parti) >= 2:
        comune = parti[-1]
        if comune.lower().startswith("isola") and len(parti) >= 3:
            avv.append("isola: " + comune)
            comune = parti[-2]
            parti = parti[:-1]
        out["comune"] = comune
        out["indirizzo"] = ", ".join(parti[:-1])
    elif len(parti) == 1:
        p = parti[0]
        mm = re.match(r"^(.*?\b" + CIVICO + r")\s+([A-Za-zÀ-ÿ'][^\d]*)$", p)
        if ha_via and mm:
            out["indirizzo"], out["comune"] = mm.group(1), mm.group(2).strip()
        elif ha_via:
            out["indirizzo"] = p
            avv.append("comune non riconosciuto")
        else:
            out["comune"] = p          # solo una localita'
    # "loc. Oriolo Voghera" -> la localita' resta nell'indirizzo, il comune e' l'ultima parola
    mm = re.match(r"^(?:loc\.?|localit[aà]|frazione|fraz\.?)\s+(\S+)\s+(.+)$", out["comune"], re.I)
    if mm:
        out["indirizzo"] = (out["indirizzo"] + ", " if out["indirizzo"] else "") + \
            out["comune"][:len(out["comune"]) - len(mm.group(2))].strip()
        out["comune"] = mm.group(2)
    return out, avv


def analizza(frase):
    """Da una frase di origine ricava ruolo, indirizzo, produttore, bollo, paese."""
    r = {"ruolo": "", "indirizzo": "", "cap": "", "comune": "", "provincia": "", "paese": "",
         "produttore_nominato": "", "bollo_ce": "", "nota": []}
    m = RE_TRIG.match(frase)
    testo, prep = frase, ""
    if m:
        r["ruolo"] = re.sub(r"\s+", " ", m.group(0)).lower()
        testo = frase[m.end():]
        mp = re.match(r"\s*:?\s*(in|da|presso|per)\b\s*:?\s*", testo, re.I)
        if mp:
            prep = mp.group(1).lower()
            testo = testo[mp.end():]
        else:
            testo = testo.lstrip(" :")
    testo = re.sub(r"\s*[-–]?\s*www\.\S+", "", testo)
    # "per PECK ..." = il titolare del marchio, non il luogo
    mper = re.search(r"\s+per\s+PECK\b", testo, re.I)
    if mper:
        r["nota"].append("per conto di Peck")
        testo = testo[:mper.start()]
    mm = RE_PECK_STOP.search(testo, 6)
    if mm:
        testo = testo[:mm.start()]
    bollo, testo = estrai_bollo(testo)
    r["bollo_ce"] = bollo
    if bollo and not re.search(r"\b(CE|UE)\b", bollo):
        r["nota"].append("codice senza la sigla CE")
    testo = re.sub(r"\s+", " ", testo).strip(" ,;:-–.")
    # paese iniziale ("Italia da BANFI", "Francia da KRUG")
    mpa = re.match(r"^(Italia|Italy|Francia|Spagna|Germania|Scozia|Svizzera|Portogallo)\b[\s,]*",
                   testo, re.I)
    if mpa:
        r["paese"] = PAESI[mpa.group(1).lower()]
        testo = testo[mpa.end():]
        mda = re.match(r"^da\b\s*:?\s*", testo, re.I)
        if mda:
            testo = testo[mda.end():]
            prep = "da"
    testo = re.sub(r"^atmosfera protettiva da\s+", "", testo, flags=re.I).strip(" ,;:-–.")
    produttore, resto, ha_via = "", testo, False
    if testo:
        mv = RE_VIA.search(testo)
        if mv:
            ha_via = True
            if mv.start() > 0:
                produttore = testo[:mv.start()].strip(" ,;:-–")
                resto = testo[mv.start():]
        else:
            # nessuna via: un nome ("TV 1000", "KRUG") oppure "Nome - Localita', PV"
            parti = re.split(r"\s+[-–]\s+", testo, maxsplit=1)
            if prep in ("da", "per") or r["paese"]:
                produttore = parti[0].strip(" ,;")
                resto = parti[1] if len(parti) > 1 else ""
            elif not (re.search(r"\d|\([A-Za-z]{2}\)", testo) or "," in testo):
                # solo parole, senza prep: lo trattiamo come nome
                produttore, resto = testo, ""
    produttore = re.sub(r"\s+in$", "", produttore).strip()
    if re.match(r"^C\.?C\.?I\.?A\.?A", produttore):
        r["nota"].append("numero CCIAA (registro imprese), non il nome dell'azienda: " + produttore)
        produttore = ""
    if produttore:
        r["produttore_nominato"] = produttore
    if resto.strip(" ,;-–"):
        if ha_via or re.search(r"\d|\([A-Za-z]{2}\)", resto) or "," in resto:
            camp, avv = spezza_indirizzo(resto, ha_via)
            for k in ("indirizzo", "cap", "comune", "provincia"):
                r[k] = camp[k]
            if camp["paese"] and not r["paese"]:
                r["paese"] = camp["paese"]
            r["nota"] += avv
        else:
            r["comune"] = resto.strip()
    if r["provincia"] and not r["paese"] and re.fullmatch(r"[A-Z]{2}", r["provincia"]):
        r["paese"] = "Italia"
    if not r["paese"] and r["bollo_ce"]:
        b = r["bollo_ce"][3:] if r["bollo_ce"].startswith("CE ") else r["bollo_ce"]
        r["paese"] = PREFISSO_PAESE.get(b[:2], "")
    r["nota"] = "; ".join(r["nota"])
    return r


# correzioni manuali: frase verbatim -> campi da sovrascrivere (solo dove il parser sbaglia
# perche' il testo originale e' scritto male). Ogni voce ha una spiegazione in `nota`.
CORREZIONI = {
    "Prodotto in: via Arma di Taggia (IM) 18018 Regione Prati e Pescine, Argine sinistro": {
        "indirizzo": "via Arma di Taggia, Regione Prati e Pescine, Argine sinistro", "comune": "",
        "cap": "18018", "provincia": "IM",
        "nota": "testo confuso: il comune non e' indicato chiaramente (corretto a mano)"},
    "Imbottigliato in vuia Volterra 207, 50026 San Casciano V.P, Firenze, Italia": {
        "indirizzo": "vuia Volterra 207", "cap": "50026", "comune": "San Casciano V.P",
        "provincia": "Firenze", "nota": "nel testo 'vuia' (refuso); corretto a mano"},
    "Imbottigliato in via Volterrana 207, 50026 San Casciano V.P Firenze, Italy": {
        "indirizzo": "via Volterrana 207", "cap": "50026", "comune": "San Casciano V.P",
        "provincia": "Firenze", "nota": "corretto a mano"},
}


# ---------------------------------------------------------------- pagine

def testo_blocchi(p):
    for br in p.find_all("br"):
        br.replace_with("\n")
    return [re.sub(r"[ \t]+", " ", l).strip() for l in p.get_text().split("\n")]


def prezzo(soup):
    el = soup.select_one(".box_prezzo .prezzo")
    if not el:
        return ""
    t = el.get_text().replace("\xa0", " ")
    m = re.search(r"(\d+(?:\.\d{3})*),(\d{2})", t)
    if not m:
        return ""
    return m.group(1).replace(".", "") + "." + m.group(2)


def leggi_pagina(f):
    soup = BeautifulSoup(f.read_text(encoding="utf-8"), "html.parser")
    slug = f.stem[len("prodotto_"):]
    nome = soup.h1.get_text(" ", strip=True) if soup.h1 else ""
    cat = soup.select_one(".title_category a")
    sch = soup.find(id="scheda-prodotto_prod")
    desc = soup.find(id="descrizione_prod")
    elementi = []
    if sch:
        for p in sch.find_all("p"):
            righe = [x for x in testo_blocchi(p) if x]
            if not righe:
                continue
            if righe[0].rstrip(":").lower() == "ingredienti" and len(righe) > 1:
                nome_el, corpo = righe[1], righe[2:]
            else:
                nome_el, corpo = righe[0], righe[1:]
            utili = []
            for x in corpo:
                if x.lower().startswith("dichiarazione nutrizionale"):
                    break
                utili.append(x)
            elementi.append({"nome": nome_el, "righe": utili})
    righe_desc = len([x for x in testo_blocchi(desc) if x]) if desc else 0
    return {
        "slug": slug, "url": f"{BASE}/it/{slug}", "nome": nome,
        "categoria": cat.get_text(strip=True) if cat else "",
        "prezzo": prezzo(soup), "elementi": elementi, "righe_desc": righe_desc,
        "ha_scheda": sch is not None,
    }


def norm(s):
    return re.sub(r"\s+", " ", s.lower().replace(",", " ").replace(".", " ")).strip()


def nucleo_bollo(b):
    """Il bollo senza 'CE'/'UE' e senza spazi, per confrontare scritture diverse."""
    return re.sub(r"\b(CE|UE)\b|\s", "", b)


def stesso_luogo(a, b):
    """Due righe indicano lo stesso luogo? (scritture leggermente diverse della stessa via)"""
    ca, cb = norm(a["comune"]), norm(b["comune"])
    if not (ca == cb or (ca and cb and (ca.startswith(cb) or cb.startswith(ca)))):
        return False
    if a["provincia"] and b["provincia"] and a["provincia"] != b["provincia"]:
        return False
    ia, ib = norm(a["indirizzo"]), norm(b["indirizzo"])
    return difflib.SequenceMatcher(None, ia, ib).ratio() > 0.85


def sede_peck(r):
    return "spadari" in (r["indirizzo"] or "").lower()


def righe_origine(el):
    """Frasi di origine di un elemento, analizzate e senza doppioni."""
    frasi = estrai_frasi(el["righe"])
    viste, uniche = set(), []
    for f in frasi:
        k = norm(f)
        if k not in viste:
            viste.add(k)
            uniche.append(f)
    # una frase che e' solo l'inizio di un'altra piu' completa ("Prodotto in Italia" /
    # "Prodotto in Italia da BANFI") si scarta
    uniche = [f for f in uniche
              if not any(g != f and norm(g).startswith(norm(f) + " ") for g in uniche)]
    # "Prodotto e confezionato da CCIAA 32245/97/SI" e la versione completa con la localita'
    uniche = [f for f in uniche
              if not (re.search(r"CCIAA \S+$", f) and any(
                  g != f and f.split()[-1] in g for g in uniche))]
    res = []
    for f in uniche:
        r = analizza(f)
        if f in CORREZIONI:
            corr = dict(CORREZIONI[f])
            r["nota"] = "; ".join(x for x in (r["nota"], corr.pop("nota", "")) if x)
            r.update(corr)
        r["frase"] = f
        doppio = None
        for q in res:
            stessa_via = (q["comune"] and norm(q["comune"]) == norm(r["comune"])
                          and q["provincia"] == r["provincia"]
                          and (q["ruolo"].split() or [""])[0] == (r["ruolo"].split() or [""])[0]
                          and difflib.SequenceMatcher(None, norm(q["indirizzo"]),
                                                      norm(r["indirizzo"])).ratio() > 0.85)
            stesso_bollo = q["bollo_ce"] and nucleo_bollo(q["bollo_ce"]) == nucleo_bollo(r["bollo_ce"]) and \
                not r["indirizzo"] and not q["indirizzo"]
            if stessa_via or stesso_bollo:
                doppio = q
                break
        if doppio is not None:
            doppio["nota"] = (doppio["nota"] + "; " if doppio["nota"] else "") + \
                "stessa origine scritta una seconda volta con piccole differenze: «" + f + "»"
            continue
        res.append(r)
    # una riga con solo il paese ("Prodotto in Italia") non serve se l'elemento ha righe piu' precise
    solo_paese = [q for q in res if not (q["indirizzo"] or q["comune"] or q["bollo_ce"]
                                         or q["produttore_nominato"])]
    if solo_paese and len(solo_paese) < len(res):
        paese = solo_paese[0]["paese"]
        res = [q for q in res if q not in solo_paese]
        for q in res:
            if not q["paese"]:
                q["paese"] = paese
    return res


def main():
    pagine = [leggi_pagina(f) for f in sorted(RAW.glob("prodotto_*.html"))]
    if not pagine:
        sys.exit("nessuna pagina in data/raw: lanciare prima src/fetch.py")

    prodotti, elementi = [], []
    for pag in pagine:
        n = len(pag["elementi"])
        prodotti.append({"url": pag["url"], "nome": pag["nome"],
                         "tipo": "box" if n > 1 else "singolo",
                         "prezzo": pag["prezzo"], "numero_elementi": n,
                         "categoria": pag["categoria"]})
        for el in pag["elementi"]:
            rr = righe_origine(el)
            base = {"url_pagina": pag["url"], "nome_pagina": pag["nome"], "nome_elemento": el["nome"]}
            if not rr:
                elementi.append({**base, "ruolo": "", "frase_origine": "", "indirizzo": "", "cap": "",
                                 "comune": "", "provincia": "", "paese": "", "produttore_nominato": "",
                                 "bollo_ce": "", "sede_peck": "",
                                 "nota": "nessuna frase di origine nel testo"})
                continue
            for r in rr:
                elementi.append({**base, "ruolo": r["ruolo"], "frase_origine": r["frase"],
                                 "indirizzo": r["indirizzo"], "cap": r["cap"], "comune": r["comune"],
                                 "provincia": r["provincia"], "paese": r["paese"],
                                 "produttore_nominato": r["produttore_nominato"],
                                 "bollo_ce": r["bollo_ce"], "sede_peck": "si" if sede_peck(r) else "",
                                 "nota": r["nota"]})

    def scrivi(nome, righe, campi):
        with open(OUT / nome, "w", newline="", encoding="utf-8-sig") as fh:  # BOM: si apre bene in Excel
            w = csv.DictWriter(fh, fieldnames=campi, extrasaction="ignore")
            w.writeheader()
            w.writerows(righe)

    scrivi("prodotti.csv", prodotti, ["url", "nome", "tipo", "prezzo", "numero_elementi", "categoria"])
    campi_el = ["url_pagina", "nome_pagina", "nome_elemento", "ruolo", "frase_origine", "indirizzo", "cap",
                "comune", "provincia", "paese", "produttore_nominato", "bollo_ce", "sede_peck", "nota"]
    scrivi("elementi.csv", elementi, campi_el)

    # ---- indirizzi unici
    gruppi = []   # lista di liste di righe che puntano allo stesso luogo
    for e in elementi:
        if not e["indirizzo"] and not e["comune"]:
            continue
        for g in gruppi:
            if stesso_luogo(g[0], e):
                g.append(e)
                break
        else:
            gruppi.append([e])
    ind = []
    for rs in gruppi:
        primo = max(rs, key=lambda r: bool(r["cap"]) + bool(r["provincia"]))   # la scrittura piu' completa
        elems = list(OrderedDict.fromkeys(r["nome_elemento"] for r in rs))
        ind.append({
            "indirizzo": primo["indirizzo"], "cap": next((r["cap"] for r in rs if r["cap"]), ""),
            "comune": primo["comune"], "provincia": next((r["provincia"] for r in rs if r["provincia"]), ""),
            "paese": next((r["paese"] for r in rs if r["paese"]), ""),
            "sede_peck": "si" if any(r["sede_peck"] for r in rs) else "",
            "produttori_nominati": "; ".join(OrderedDict.fromkeys(
                r["produttore_nominato"] for r in rs if r["produttore_nominato"])),
            "ruoli": "; ".join(OrderedDict.fromkeys(r["ruolo"] for r in rs if r["ruolo"])),
            "n_prodotti_distinti": len(elems),
            "n_pagine": len(set(r["url_pagina"] for r in rs)),
            "n_occorrenze": len(rs),
            "prodotti": " | ".join(elems),
        })
    ind.sort(key=lambda r: (bool(r["sede_peck"]), -r["n_pagine"], r["comune"], r["indirizzo"]))
    scrivi("indirizzi.csv", ind, ["indirizzo", "cap", "comune", "provincia", "paese", "sede_peck",
                                  "produttori_nominati", "ruoli", "n_prodotti_distinti", "n_pagine",
                                  "n_occorrenze", "prodotti"])

    # ---- origini senza indirizzo
    altre = defaultdict(list)
    for e in elementi:
        if e["indirizzo"] or e["comune"] or not e["frase_origine"]:
            continue
        if e["bollo_ce"]:
            altre[("bollo", e["bollo_ce"])].append(e)
        elif e["produttore_nominato"]:
            altre[("produttore_nominato", e["produttore_nominato"])].append(e)
        else:
            altre[("solo_paese_o_vaga", e["frase_origine"])].append(e)
    out = []
    for (t, v), rs in altre.items():
        elems = list(OrderedDict.fromkeys(r["nome_elemento"] for r in rs))
        out.append({"tipo": t, "valore": v,
                    "paese": next((r["paese"] for r in rs if r["paese"]), ""),
                    "n_prodotti_distinti": len(elems),
                    "n_pagine": len(set(r["url_pagina"] for r in rs)),
                    "n_occorrenze": len(rs), "prodotti": " | ".join(elems)})
    out.sort(key=lambda r: (r["tipo"], -r["n_pagine"], r["valore"]))
    scrivi("altre_origini.csv", out, ["tipo", "valore", "paese", "n_prodotti_distinti", "n_pagine",
                                      "n_occorrenze", "prodotti"])

    # ---- riepilogo a video
    n_box = sum(1 for p in prodotti if p["tipo"] == "box")
    el_distinti = OrderedDict()
    for e in elementi:
        el_distinti.setdefault((e["url_pagina"], e["nome_elemento"]), []).append(e)
    con = sum(1 for v in el_distinti.values() if any(x["frase_origine"] for x in v))
    print(f"pagine prodotto: {len(prodotti)} (box {n_box}, singoli {len(prodotti) - n_box})")
    print(f"elementi (pagina+nome): {len(el_distinti)}; con frase di origine: {con}; "
          f"senza: {len(el_distinti) - con}")
    print(f"righe in elementi.csv: {len(elementi)}")
    print(f"indirizzi unici: {len(ind)}; altre origini: {len(out)}")


if __name__ == "__main__":
    main()
