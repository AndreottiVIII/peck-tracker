"""Tannico: scarica il catalogo pubblico e abbina i vini della carta Peck.

    python -I src/tannico.py scarica [--forza] [--pausa 1.5]
    python -I src/tannico.py abbina

`scarica` usa solo cio' che Tannico (Shopify) pubblica per i motori di ricerca e che il suo
robots.txt non vieta: sitemap.xml, sitemap_products_N.xml e /products.json. Salva in
data/raw/tannico/ (non si pubblica). Delle schede tiene solo titolo, produttore, tipo, prezzo,
disponibilita': NON salva i testi descrittivi (body_html).
`abbina` scrive data/tannico.csv.
"""
import argparse
import csv
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
RAW = RADICE / "data" / "raw" / "tannico"
VINI = RADICE / "data" / "vini.csv"
USCITA = RADICE / "data" / "tannico.csv"
BASE = "https://www.tannico.it"
UA = "Mozilla/5.0 (compatible; peck-tracker research; non-commercial)"


# ---------------------------------------------------------------- scarico
def prendi(url, pausa):
    time.sleep(pausa)
    rich = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it"})
    for tentativo in range(3):
        try:
            with urllib.request.urlopen(rich, timeout=60) as r:
                return r.read()
        except Exception as e:  # rete / 429: aspetta e riprova
            print("  errore", url, e, file=sys.stderr)
            time.sleep(5 * (tentativo + 1))
    raise SystemExit("impossibile scaricare " + url)


def scarica(forza=False, pausa=1.5):
    RAW.mkdir(parents=True, exist_ok=True)
    # 1. elenco prodotti (products.json), 250 per pagina; salvo solo i campi utili
    pagina = 1
    while True:
        f = RAW / f"products_p{pagina:03d}.json"
        if f.exists() and not forza:
            n = len(json.loads(f.read_text(encoding="utf-8")))
        else:
            dati = json.loads(prendi(f"{BASE}/products.json?limit=250&page={pagina}", pausa))
            righe = []
            for p in dati.get("products", []):
                v = (p.get("variants") or [{}])[0]
                righe.append({
                    "id": p["id"], "title": p["title"], "handle": p["handle"],
                    "vendor": p.get("vendor", ""), "product_type": p.get("product_type", ""),
                    "tags": p.get("tags", []), "price": v.get("price"),
                    "available": v.get("available"), "updated_at": p.get("updated_at"),
                })
            f.write_text(json.dumps(righe, ensure_ascii=False), encoding="utf-8")
            n = len(righe)
            print(f"products.json pagina {pagina}: {n}")
        if n < 250:  # ultima pagina
            break
        pagina += 1
    # 2. sitemap dei prodotti (per confronto sul numero e sui titoli)
    indice = RAW / "sitemap.xml"
    if forza or not indice.exists():
        indice.write_bytes(prendi(BASE + "/sitemap.xml", pausa))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in ET.parse(indice).getroot().findall(".//s:loc", ns)]
    for u in locs:
        m = re.search(r"/sitemap_products_(\d+)\.xml", u)
        if m and "/en/" not in u:
            f = RAW / f"sitemap_products_{m.group(1)}.xml"
            if forza or not f.exists():
                f.write_bytes(prendi(u, pausa))
                print("sitemap", f.name)


def carica_catalogo():
    prod = []
    for f in sorted(RAW.glob("products_p*.json")):
        prod += json.loads(f.read_text(encoding="utf-8"))
    return prod


# ---------------------------------------------------------------- testo
def senza_accenti(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s):
    s = senza_accenti((s or "").lower())
    s = s.replace("&", " e ").replace("'", " ").replace("’", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# parole che non identificano il vino (denominazioni, formati, aggettivi di confezione)
PAROLE_VUOTE = set("""docg doc igt igp aoc aop dop vdt vdp ag
di del della dello dei degli delle da de du des la le il lo l i gli e et en the
cl lt l ml astuccio magnum jeroboam bottiglia bottiglie cassa box in con per a al ai
cofanetto confezione regalo limited edition""".split())


def token_vino(s):
    t = norm(s)
    t = re.sub(r"\b\d+[ ,.]?\d*\s?(cl|ml|lt|l)\b", " ", t)
    t = re.sub(r"\b(19|20)\d\d\b", " ", t)  # annate fuori: si confrontano a parte
    return [w for w in t.split() if w not in PAROLE_VUOTE]


def annata(s):
    m = re.findall(r"\b((?:19|20)\d\d)\b", s or "")
    return m[-1] if m else ""


FORMATI = [("doppio magnum", 3000), ("double magnum", 3000), ("jeroboam", 3000), ("magnum", 1500),
           ("rehoboam", 4500), ("mathusalem", 6000), ("matusalemme", 6000), ("methuselah", 6000),
           ("salmanazar", 9000), ("baldassarre", 12000), ("balthazar", 12000),
           ("nabucodonosor", 15000), ("melchiorre", 18000), ("melchior", 18000),
           ("mezza bottiglia", 375), ("half bottle", 375)]


def formato_da_testo(testo):
    """Millilitri indicati nel testo (titolo Tannico); 750 se non dice nulla."""
    t = norm(testo)
    for nome, ml in FORMATI:
        if re.search(r"\b" + nome + r"\b", t):
            return ml
    m = re.search(r"\b(\d+) (\d+) ?(l|lt)\b", t)  # 0,75 l  ->  "0 75 l"
    if m:
        return int(round(float(m.group(1) + "." + m.group(2)) * 1000))
    m = re.search(r"\b(\d+)\s?(?:(cl)|(ml)|(l|lt))\b", t)
    if m:
        v = float(m.group(1))
        return int(v * 10 if m.group(2) else v if m.group(3) else v * 1000)
    return 750


def formato_peck(riga):
    m = re.match(r"(\d+)ml", riga.get("formato", ""))
    if m:
        return int(m.group(1))
    return formato_da_testo(riga.get("variante", "")) if riga.get("variante") else 750


# ---------------------------------------------------------------- abbinamento
# parole di cantina che non identificano la cantina
CANTINA_GENERICA = set("""domaine chateau azienda agricola agraria agricoltura tenuta tenute cantina cantine
castello casa maison famille bodegas bodega weingut fattoria podere poderi vigneti vigneto vigna cellars
cellar estate winery vineyards vineyard wines wine vini vino societa soc srl spa di del della dei delle
de du des la le les il lo l i gli e et and the von van der den dos das do da marchesi marchese fratelli figli fili
f lli famiglia viticoltori produttori vignerons champagne champagnes
""".split())
# parole che in un nome di vino contano: non si possono ignorare quando uno dei due titoli le ha
IMPORTANTI = set("""riserva reserva gran grand grande cru 1er premier selezione superiore classico brut nature
zero extra dosage sec demi rose rosato rosso bianco rouge blanc noir blancs noirs vecchie vigne old vieilles
millesime millesimato vintage speciale special cuvee reserve rouges blanche rosa rosado tinto
frizzante spumante secco semisecco dolce dry passito trocken saten ripasso nobile recioto amarone
tardiva harvest moelleux liquoroso chinato bio biologico natural pet nat ancestrale
""".split())
# regioni e simili: se compaiono solo in un titolo non cambia il vino
REGIONI = set("""toscana piemonte lombardia veneto friuli venezia giulia trentino alto adige sicilia sardegna puglia
campania calabria basilicata abruzzo molise marche umbria lazio liguria emilia romagna valle aosta
italia francia spagna germania austria portogallo bordeaux bourgogne borgogna champagne rhone loira
provence languedoc roussillon alsazia alsace beaujolais rioja ribera duero priorat
""".split())


def tokens(s):
    return set(token_vino(s))


def tok_cantina(c):
    """Alternative di token distintivi per una cantina (le parentesi sono alternative)."""
    alt = [re.sub(r"\([^)]*\)", " ", c)] + re.findall(r"\(([^)]*)\)", c)
    out = []
    for a in alt:
        t = {w for w in tokens(a) if w not in CANTINA_GENERICA}
        t = t or tokens(a)
        if t:
            out.append(t)
    return out


def spezza_titolo(titolo, vendor):
    """Titolo Tannico -> (parte vino, parte cantina, annata, formato)."""
    t = titolo.strip()
    formato = formato_da_testo(t)
    parti = t.rsplit(" - ", 1)
    vino, casa = (parti[0], parti[1]) if len(parti) == 2 else (t, "")
    casa = re.sub(r"\([^)]*\)", " ", casa)
    anno = annata(vino)
    vino = re.sub(r"\([^)]*\)", " ", vino)
    return vino, (casa + ", " + vendor), anno, formato


class Prodotto:
    def __init__(self, p):
        self.p = p
        self.vino, self.casa, self.anno, self.formato = spezza_titolo(p["title"], p["vendor"])
        self.t_vino = tokens(self.vino)
        self.t_casa = tokens(self.casa)
        self.t_casa_dist = {w for w in self.t_casa if w not in CANTINA_GENERICA}
        self.gruppi = componenti_casa(p["title"], p["vendor"])
        n = norm(p["title"])
        self.box = (" + " in p["title"]) or (" - " not in p["title"] and bool(
            re.search(r"\b(box|kit|gift|confezione|cofanetto|degustazione|offerta|omaggio)\b", n)))
        self.url = f"{BASE}/products/{p['handle']}"


def costruisci_indice(prodotti):
    idx = {}
    for pr in prodotti:
        for w in pr.t_casa_dist:
            idx.setdefault(w, []).append(pr)
    return idx


def frequenze_generiche(prodotti, soglia=12):
    """Token del nome del vino che compaiono in molte cantine diverse: parole di denominazione."""
    cant = {}
    for pr in prodotti:
        for w in pr.t_vino:
            cant.setdefault(w, set()).add(pr.casa)
    return {w for w, c in cant.items() if len(c) >= soglia and w not in IMPORTANTI}


def componenti_casa(titolo, vendor):
    """Gruppi di token distintivi: il venditore e ogni nome dopo l'ultimo ' - ' del titolo."""
    parti = titolo.rsplit(" - ", 1)
    casa = re.sub(r"\([^)]*\)", " ", parti[1]) if len(parti) == 2 else ""
    gruppi = []
    for c in [vendor] + casa.split(","):
        t = {w for w in tokens(c) if w not in CANTINA_GENERICA} or tokens(c)
        if t:
            gruppi.append(t)
    return gruppi


def simili(a, b):
    """Due parole quasi uguali (varianti di scrittura)."""
    return len(a) >= 4 and len(b) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def nucleo(t, generici):
    """Parole del nome del vino senza denominazioni/regioni/parole di cantina molto comuni."""
    return {w for w in t if w in IMPORTANTI or not (w in generici or w in REGIONI or w in CANTINA_GENERICA)}


def confronta(riga, tc_alt, pr, generici):
    """(livello, somiglianza, cantina_esatta) fra un vino Peck e un prodotto Tannico, o None."""
    # cantina: i token distintivi di Peck devono stare nella casa (o nel nome) di Tannico
    esatta = any(a == g for a in tc_alt for g in pr.gruppi)
    if not esatta and not any(a <= (pr.t_casa | pr.t_vino) for a in tc_alt):
        return None
    togli = set().union(*tc_alt) | pr.t_casa
    vp = tokens(riga["nome"]) - togli
    vt = pr.t_vino - togli
    np_, nt = nucleo(vp, generici), nucleo(vt, generici)
    inter = np_ & nt
    gp, gt = vp & generici, vt & generici
    generici_compatibili = gp <= gt or gt <= gp  # es. "Barolo" contro "Barbaresco" NON va bene
    if vp == vt:
        liv = "uguale"
    elif np_ == nt and np_:
        liv = "uguale" if generici_compatibili else "simile"
    elif inter - IMPORTANTI:  # qualche parola distintiva in comune (non basta "grand cru")
        # parole distintive solo da una parte = vino diverso (Chambertin / Mazis Chambertin),
        # a meno che siano varianti di scrittura (Mazy / Mazis, Sainte / Saint)
        dp, dt = (np_ - nt) - IMPORTANTI, (nt - np_) - IMPORTANTI
        if any(not any(simili(w, x) for x in dt) for w in dp) or                 any(not any(simili(w, x) for x in dp) for w in dt):
            return None
        liv = "simile"
    else:
        return None
    union = np_ | nt
    jac = len(inter) / len(union) if union else 1.0
    return liv, jac, esatta


def abbina():
    prodotti = [Prodotto(p) for p in carica_catalogo()]
    prodotti = [pr for pr in prodotti
                if pr.p["product_type"] not in ("Spirits", "Accessori", "Soft Drink", "No-Low Alcol")
                and not pr.box]
    idx = costruisci_indice(prodotti)
    generici = frequenze_generiche(prodotti)
    print(len(prodotti), "prodotti Tannico utilizzabili,", len(generici), "parole generiche")
    with open(VINI, encoding="utf-8-sig", newline="") as f:
        righe = list(csv.DictReader(f))
    vini = {}  # un vino per id; i formati sono raccolti
    for r in righe:
        v = vini.setdefault(r["id"], {"riga": r, "formati": set()})
        if r["variante"] != "calice":
            v["formati"].add(formato_peck(r))
    uscita = []
    for v in vini.values():
        riga, formati = v["riga"], v["formati"] or {750}
        tc_alt = tok_cantina(riga["cantina"])
        cand = {}
        for a in tc_alt:
            for w in a:
                for pr in idx.get(w, []):
                    cand[pr.p["id"]] = pr
        a_peck = riga["annata"]
        migliori = []
        for pr in cand.values():
            r = confronta(riga, tc_alt, pr, generici)
            if r:
                migliori.append((r[0], r[1], r[2], pr))
        base = {"id": riga["id"], "nome": riga["nome"], "cantina": riga["cantina"], "annata": a_peck,
                "url_tannico": "", "titolo_tannico": "", "corrispondenza": "nessuna",
                "punteggio_abbinamento": 0, "nota": ""}
        if migliori:
            def distanza(pr):
                return abs(int(pr.anno) - int(a_peck)) if pr.anno and a_peck else 99

            def chiave(x):
                liv, jac, cant, pr = x
                return (liv == "uguale" and cant, liv == "uguale", pr.anno == a_peck,
                        pr.formato in formati, pr.formato == 750, jac, -distanza(pr),
                        pr.p["available"] is True)
            migliori.sort(key=chiave, reverse=True)
            liv, jac, cant, pr = migliori[0]
            stessa_annata = pr.anno == a_peck
            stesso_formato = pr.formato in formati
            note = []
            if not stesso_formato:
                note.append(f"formato diverso (Tannico {pr.formato} ml)")
            if not cant:
                note.append("cantina simile ma non identica")
            if liv == "simile":
                note.append("nome del vino solo simile")
            if liv == "uguale" and cant and stessa_annata and stesso_formato:
                corr = "esatta"
            elif liv == "uguale" and cant and a_peck and pr.anno and stesso_formato:
                corr = "annata diversa"
            else:
                corr = "da controllare"
            punteggio = round(100 * (jac if liv == "simile" else 1.0) * (1 if cant else 0.8)
                              * (1 if stessa_annata else 0.85) * (1 if stesso_formato else 0.85))
            if corr == "da controllare" and (liv == "simile" and jac < SOGLIA_SIMILE
                                             or not stessa_annata and not (a_peck and pr.anno)):
                corr = "nessuna"  # troppo debole: meglio nessun link che uno sbagliato
            if corr != "nessuna":
                base.update(url_tannico=pr.url, titolo_tannico=pr.p["title"], corrispondenza=corr,
                            punteggio_abbinamento=punteggio, nota="; ".join(note))
        uscita.append(base)
    campi = ["id", "nome", "cantina", "annata", "url_tannico", "titolo_tannico", "corrispondenza",
             "punteggio_abbinamento", "nota"]
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, campi)
        w.writeheader()
        w.writerows(uscita)
    from collections import Counter
    print(len(uscita), "vini;", Counter(u["corrispondenza"] for u in uscita))


SOGLIA_SIMILE = 0.6


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["scarica", "abbina"])
    ap.add_argument("--forza", action="store_true")
    ap.add_argument("--pausa", type=float, default=1.5)
    a = ap.parse_args()
    if a.comando == "scarica":
        scarica(a.forza, a.pausa)
    else:
        abbina()
