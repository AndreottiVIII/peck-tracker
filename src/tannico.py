"""Tannico: scarica il catalogo pubblico e abbina i vini della carta Peck.

    python -I src/tannico.py scarica [--forza] [--pausa 1.5]
    python -I src/tannico.py abbina
    python -I src/tannico.py voti [--forza] [--pausa 3] [--solo-analisi]

`scarica` usa solo cio' che Tannico (Shopify) pubblica per i motori di ricerca e che il suo
robots.txt non vieta: sitemap.xml, sitemap_products_N.xml e /products.json. Salva in
data/raw/tannico/ (non si pubblica). Delle schede tiene solo titolo, produttore, tipo, prezzo,
disponibilita': NON salva i testi descrittivi (body_html).
`abbina` scrive data/tannico.csv.
`voti` scarica le schede prodotto di Tannico (/products/<handle>, consentite dal robots.txt) dei vini
abbinati "esatta" o "annata diversa" (una volta per indirizzo, 3 secondi di pausa, 429 = si aspetta
60 secondi e si rallenta) in data/raw/tannico/prodotti/ e ne estrae SOLO i numeri: il giudizio di
Tannico e i punteggi dei critici (nome e voto), scrivendo data/tannico_voti.csv. Nessun testo.
"""
import argparse
import csv
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
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


def formato_esplicito(testo):
    """Millilitri indicati nel testo (titolo o indirizzo Tannico), oppure None se il testo non dice nulla.
    Prima i litri scritti con le cifre ("1,5l", "0.375l", "37,5 cl", "150cl", "(1l)"), poi le parole
    (magnum, jeroboam = 3 L, mathusalem = 6 L...)."""
    t = norm(testo)
    for m in re.finditer(r"(?<![0-9])(\d{1,3})(?: (\d{1,3}))?\s?(cl|ml|lt|l)\b", t):
        v = float(m.group(1) + ("." + m.group(2) if m.group(2) else ""))
        ml = v * 10 if m.group(3) == "cl" else v if m.group(3) == "ml" else v * 1000
        if 100 <= ml <= 30000:
            return int(round(ml))
    for nome, ml in FORMATI:
        if re.search(r"\b" + nome + r"\b", t):
            return ml
    return None


def formato_da_testo(testo):
    """Millilitri indicati nel testo; 750 se non dice nulla."""
    return formato_esplicito(testo) or 750


def formato_peck(riga):
    """Millilitri della riga Peck: dalla colonna `litri` di vini.csv (src/vini.py); se manca la colonna,
    dalla capacita' e dalla variante. None = formato sconosciuto (vini senza prezzo e senza indicazioni)."""
    if "litri" in riga:
        return int(round(float(riga["litri"]) * 1000)) if riga["litri"] else None
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


def spezza_titolo(titolo, vendor, handle=""):
    """Titolo Tannico -> (parte vino, parte cantina, annata, formato). Il formato si cerca nel titolo e,
    se il titolo tace, nell'indirizzo (handle): 750 ml solo se nessuno dei due dice altro."""
    t = titolo.strip()
    formato = formato_esplicito(t) or formato_esplicito(handle) or 750
    parti = t.rsplit(" - ", 1)
    vino, casa = (parti[0], parti[1]) if len(parti) == 2 else (t, "")
    casa = re.sub(r"\([^)]*\)", " ", casa)
    anno = annata(vino)
    vino = re.sub(r"\([^)]*\)", " ", vino)
    return vino, (casa + ", " + vendor), anno, formato


class Prodotto:
    def __init__(self, p):
        self.p = p
        self.vino, self.casa, self.anno, self.formato = spezza_titolo(p["title"], p["vendor"], p["handle"])
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
    vini = {}  # un vino per id; i formati (ml) sono raccolti. None = formato sconosciuto
    for r in righe:
        v = vini.setdefault(r["id"], {"riga": r, "formati": set(), "calice": False})
        if r["variante"] == "calice":
            v["calice"] = True
        elif r["prezzo_euro"] not in ("0", "0.0") and formato_peck(r):  # prezzo 0 = segnaposto; formato vuoto = sconosciuto
            v["formati"].add(formato_peck(r))
    uscita = []
    for v in vini.values():
        riga = v["riga"]
        formati = v["formati"] or {750}  # solo calici o formato sconosciuto: si assume la bottiglia (con nota)
        assunto = not v["formati"] and not v["calice"]
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
                return (liv == "uguale" and cant, liv == "uguale", pr.formato in formati,
                        pr.anno == a_peck, pr.formato == 750, jac, -distanza(pr),
                        pr.p["available"] is True)
            migliori.sort(key=chiave, reverse=True)
            liv, jac, cant, pr = migliori[0]
            stessa_annata = pr.anno == a_peck
            stesso_formato = pr.formato in formati
            note = []
            if not stesso_formato:
                peck = "/".join(f"{x:g}" for x in sorted(formati))
                note.append(f"formato diverso (Peck {peck} ml, Tannico {pr.formato} ml)")
            elif assunto:
                note.append("formato Peck non indicato (assunto 750 ml)")
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


# ---------------------------------------------------------------- voti
PRODOTTI = RAW / "prodotti"
USCITA_VOTI = RADICE / "data" / "tannico_voti.csv"
DATA_RACCOLTA = "2026-10-25"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")


def handle_di(url):
    return url.rstrip("/").rsplit("/products/", 1)[1].split("?")[0]


def url_da_scaricare():
    """Indirizzi unici dei vini abbinati 'esatta' o 'annata diversa', nell'ordine del file."""
    with open(USCITA, encoding="utf-8-sig", newline="") as f:
        righe = [r for r in csv.DictReader(f) if r["corrispondenza"] in ("esatta", "annata diversa")]
    visti, out = set(), []
    for r in righe:
        if r["url_tannico"] and r["url_tannico"] not in visti:
            visti.add(r["url_tannico"])
            out.append(r["url_tannico"])
    return out


def scarica_schede(forza=False, pausa=3.0):
    PRODOTTI.mkdir(parents=True, exist_ok=True)
    urls = url_da_scaricare()
    print(len(urls), "schede da controllare")
    nuove = 0
    for i, url in enumerate(urls, 1):
        f = PRODOTTI / (handle_di(url) + ".html")
        if f.exists() and not forza:
            continue
        rich = urllib.request.Request(url, headers={"User-Agent": UA_BROWSER, "Accept-Language": "it-IT,it;q=0.9"})
        for tentativo in range(4):
            time.sleep(pausa)
            try:
                with urllib.request.urlopen(rich, timeout=60) as r:
                    f.write_bytes(r.read())
                nuove += 1
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:  # troppe richieste: si aspetta e si rallenta, mai insistere
                    pausa *= 1.5
                    print(f"  429 su {url}: attendo 60 s, pausa ora {pausa:.1f} s", file=sys.stderr)
                    time.sleep(60)
                elif e.code in (404, 410):
                    print(f"  {e.code} {url}", file=sys.stderr)
                    break
                else:
                    print(f"  errore {e.code} {url}", file=sys.stderr)
                    time.sleep(10 * (tentativo + 1))
            except Exception as e:
                print("  errore", url, e, file=sys.stderr)
                time.sleep(10 * (tentativo + 1))
        if i % 20 == 0:
            print(f"  {i}/{len(urls)}", flush=True)
    print("scaricate", nuove, "schede nuove in", PRODOTTI)


# nome come scritto da Tannico (senza maiuscole) -> nome da mostrare. Gli altri restano come sono.
NOMI_CRITICI = {"suckling": "James Suckling", "james suckling": "James Suckling",
                "parker": "Robert Parker", "robert parker": "Robert Parker",
                "wine advocate": "Robert Parker", "the wine advocate": "Robert Parker",
                "gambero rosso": "Gambero Rosso", "veronelli": "Veronelli", "luca maroni": "Luca Maroni",
                "wine spectator": "Wine Spectator", "decanter": "Decanter", "vinous": "Vinous",
                "falstaff": "Falstaff", "bibenda": "Bibenda", "doctor wine": "Doctor Wine",
                "jancis robinson": "Jancis Robinson", "antonio galloni": "Antonio Galloni", "wine enthusiast": "Wine Enthusiast"}
# criteri che non sono su scala 100: unita' per il numero
SCALE_FISSE = {"Bibenda": "grappoli", "Gambero Rosso": "bicchieri", "Jancis Robinson": "20"}
SCALA_UNITA = [(r"grappol", "grappoli"), (r"bicchier", "bicchieri"), (r"\bviti?\b", "viti"),
               (r"stell", "stelle"), (r"corone", "corone"), (r"sole|soli", "soli")]


def nome_critico(n):
    n = re.sub(r"\s+", " ", n.strip())
    return NOMI_CRITICI.get(norm(n), n)


def pulisci(x):
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(x)).strip()


def leggi_scheda(testo):
    """Numeri di una scheda prodotto di Tannico: giudizio Tannico, annata, critici [(nome, valore, scala)]."""
    # -- giudizio di Tannico: JSON-LD (Punteggio Tannico), poi elenco caratteristiche, poi bollino
    m = (re.search(r'"name":\s*"(?:Punteggio|Giudizio di) Tannico",\s*"value":\s*"(\d+)\s*pt"', testo)
         or re.search(r"<strong>\s*(?:Giudizio di|Punteggio) Tannico:\s*</strong>\s*<span[^>]*>\s*(\d+)\s*pt", testo))
    i_main = testo.find('id="shopify-section-template--')
    i_main = testo.find("__main", i_main if i_main >= 0 else 0)
    i_gall = testo.find('data-controller="product-gallery"', max(i_main, 0))
    zona = testo[max(i_main, 0):i_gall] if i_gall > 0 else ""
    if not m:
        m = re.search(r'aria-label="Giudizio di Tannico:\s*(\d+)/100"', zona)
    tannico = int(m.group(1)) if m else None
    # -- annata
    a = re.search(r'"name":\s*"Annata",\s*"value":\s*"((?:19|20)\d\d)"', testo)
    annata_t = a.group(1) if a else ""
    # -- bollini in alto (nome: valore con la scala)
    critici = {}
    for nome, val in re.findall(r'role="img"\s+aria-label="([^":]+):\s*([^"]+)"', zona):
        nome = pulisci(nome)
        if norm(nome) in ("giudizio di tannico", "tannico", "punteggio tannico"):
            continue
        val = pulisci(val)
        mm = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+)", val)
        if mm:
            critici[nome_critico(nome)] = (mm.group(1).replace(",", "."), mm.group(2))
            continue
        mm = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s+(.+)", val)
        if mm:
            unita = next((u for pat, u in SCALA_UNITA if re.search(pat, mm.group(2).lower())), mm.group(2).lower())
            critici[nome_critico(nome)] = (mm.group(1).replace(",", "."), unita)
    # -- blocco "Riconoscimenti annata corrente": numero + nome (la scala non c'e')
    i = testo.find("Riconoscimenti annata corrente")
    if i >= 0:
        fine = testo.find("<product-description", i)
        blocco = testo[i:fine if fine > 0 else i + 3000]
        for num, nome in re.findall(r"<div[^>]*>\s*(\d+(?:[.,]\d+)?)\s*</div>\s*<div[^>]*>\s*([^<]+?)\s*</div>", blocco):
            nome = nome_critico(pulisci(nome))
            if nome not in critici:
                scala = SCALE_FISSE.get(nome) or ("100" if float(num.replace(",", ".")) > 20 else "?")
                critici[nome] = (num.replace(",", "."), scala)
    return tannico, annata_t, [(n, v, sc) for n, (v, sc) in critici.items()]


def scrivi_voto(nome, valore, scala):
    if scala == "100":
        return f"{nome} {valore}/100"
    if scala == "?":
        return f"{nome} {valore}"
    if scala.isdigit():
        return f"{nome} {valore}/{scala}"
    return f"{nome} {valore} {scala}"


def voti():
    with open(USCITA, encoding="utf-8-sig", newline="") as f:
        righe = [r for r in csv.DictReader(f) if r["corrispondenza"] in ("esatta", "annata diversa")]
    cache, uscita = {}, []
    senza_file = 0
    for r in righe:
        url = r["url_tannico"]
        if url not in cache:
            f = PRODOTTI / (handle_di(url) + ".html")
            cache[url] = (leggi_scheda(f.read_bytes().decode("utf-8", errors="replace"))
                          if f.exists() else None)
        dati = cache[url]
        if dati is None:
            senza_file += 1
            continue
        tannico, annata_t, critici = dati
        uscita.append({
            "id": r["id"], "url_tannico": url,
            "annata_tannico": annata_t or annata(r["titolo_tannico"]) or annata(url.rsplit("/", 1)[-1]),
            "corrispondenza": r["corrispondenza"],
            "punteggio_tannico": tannico if tannico is not None else "",
            "voti_critici": "; ".join(scrivi_voto(*c) for c in critici),
            "n_critici": len(critici), "data_raccolta": DATA_RACCOLTA})
    campi = ["id", "url_tannico", "annata_tannico", "corrispondenza", "punteggio_tannico",
             "voti_critici", "n_critici", "data_raccolta"]
    with open(USCITA_VOTI, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, campi)
        w.writeheader()
        w.writerows(uscita)
    from collections import Counter
    pagine = [d for d in cache.values() if d is not None]
    print(len(righe), "vini abbinati;", len(cache), "schede;", len(pagine), "lette;", senza_file, "vini senza scheda scaricata")
    print("con giudizio Tannico:", sum(1 for u in uscita if u["punteggio_tannico"] != ""),
          "| con critici:", sum(1 for u in uscita if u["n_critici"]),
          "| senza niente:", sum(1 for u in uscita if u["punteggio_tannico"] == "" and not u["n_critici"]))
    conta = Counter()
    for d in pagine:
        for n, v, sc in d[2]:
            conta[n] += 1
    print("critici (per scheda):", dict(conta.most_common()))


SOGLIA_SIMILE = 0.6


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["scarica", "abbina", "voti"])
    ap.add_argument("--forza", action="store_true")
    ap.add_argument("--pausa", type=float, default=None)
    ap.add_argument("--solo-analisi", action="store_true")
    a = ap.parse_args()
    if a.comando == "scarica":
        scarica(a.forza, a.pausa or 1.5)
    elif a.comando == "abbina":
        abbina()
    else:
        if not a.solo_analisi:
            scarica_schede(a.forza, a.pausa or 3.0)
        voti()
