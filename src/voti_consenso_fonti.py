"""Nuove fonti di voti dei critici per i vini della carta Peck -> data/voti_extra.csv.

    python -I src/voti_consenso_fonti.py jb_sitemap       # robots.txt + sitemap dei prodotti di Justerini & Brooks
    python -I src/voti_consenso_fonti.py jb_abbina        # pre-abbinamento coi nomi negli indirizzi -> candidati.csv
    python -I src/voti_consenso_fonti.py jb_scarica [N]   # scarica SOLO le schede candidate (pausa 3 s), tiene solo i voti
    python -I src/voti_consenso_fonti.py farr_sitemap      # robots.txt + sitemap di Farr Vintners
    python -I src/voti_consenso_fonti.py farr_scarica [N]  # scarica le ~5000 schede vino (pausa 2 s, riprende da dove era), tiene solo titolo e voti
    python -I src/voti_consenso_fonti.py ws_scarica       # Wine Spectator Top 100 (Zenodo 7930185, CC BY)
    python -I src/voti_consenso_fonti.py estrai           # legge tutto quello che c'e' su disco -> data/voti_extra.csv
    python -I src/voti_consenso_fonti.py verifica [N]     # N righe a caso da controllare a mano
    python -I src/voti_consenso_fonti.py riepilogo

Fonti e regole (la decisione sul perche' e' in JOURNAL.md):
  - Justerini & Brooks (justerinis.com, Diageo): la scheda di ogni annata porta l'elenco dei critici
    (testata, recensore, voto, data) nei dati della pagina. robots.txt: tutto aperto, nessuna sezione per
    agenti AI. Condizioni d'uso: niente divieto esplicito di accesso automatico, ma «copiare» e' vietato
    fuori dall'uso personale non commerciale: qui si tengono SOLO nome del critico e numero (mai le note di
    degustazione), per un lavoro non commerciale. Pausa 3 s, User-Agent che dice chi siamo.
  - Farr Vintners (farrvintners.com): schede con punteggi storici dei critici. robots.txt: aperto per le schede.
  - Wine Spectator Top 100 2003-2020 (Zenodo 7930185, licenza CC BY 4.0, base dati di terzi): il sito
    di Wine Spectator vieta ClaudeBot nel suo robots.txt, qui NON si visita: si usa la copia con licenza
    aperta (solo 100 vini l'anno). Fonte da togliere con FONTI_DA_ESCLUDERE se non la si vuole.
  - Global Wine Score: il dominio e' in vendita (HugeDomains), servizio e API non piu' raggiungibili.
  - CellarTracker: la WAF risponde con la sfida anti-bot anche a robots.txt: non si tocca.

Regole comuni: robots.txt riletto e rispettato (anche le sezioni per ClaudeBot/anthropic-ai), niente accessi
con login, niente aggiramento di blocchi (403/429 persistenti = si ferma), grezzo in data/raw/voti/<fonte>/.
"""
import csv
import hashlib
import html as htmllib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tannico as T  # noqa: E402
import voti_aperti as VA  # noqa: E402
import voti_enoteche as VE  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
RAW = RADICE / "data" / "raw" / "voti"
USCITA = RADICE / "data" / "voti_extra.csv"
OGGI = datetime.now(timezone.utc).strftime("%Y-%m-%d")

UA = "Mozilla/5.0 (compatible; peck-tracker research; non-commercial)"
PAUSA = 3.0
MAX_DISTANZA_ANNATA = 2
FONTI_DA_ESCLUDERE = set()      # es. {"Wine Spectator Top 100"} per toglierla dall'uscita

CAMPI = ["id", "fonte", "critico_o_tipo", "voto", "scala", "annata_fonte", "corrispondenza", "url",
         "licenza_note", "voto_testo", "recensore", "nome_fonte", "data_raccolta"]

LIC_JB = ("Dato fattuale (nome del critico + punteggio) letto dalla scheda pubblica di Justerini & Brooks; "
          "nessun testo copiato; uso non commerciale; robots.txt aperto")
LIC_FARR = ("Dato fattuale (nome del critico + punteggio) letto dalla scheda pubblica di Farr Vintners; "
            "nessun testo copiato; uso non commerciale; robots.txt aperto per le schede")
LIC_WS = ("CC BY 4.0 (Zenodo 10.5281/zenodo.7930185, «Database Wine and Scores», dati di Wine Spectator Top 100; "
          "copia di terzi, il sito di Wine Spectator non e' stato visitato)")


# ---------------------------------------------------------------- rete
def robots_ok_agenti(testo):
    """False se il robots.txt chiude tutto a ClaudeBot / anthropic / Claude (sezioni per agenti AI)."""
    blocco, nomi = [], []
    for riga in testo.splitlines() + ["User-agent: __fine__"]:
        riga = riga.split("#", 1)[0].strip()
        if ":" not in riga:
            continue
        k, v = (x.strip() for x in riga.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if blocco and nomi and any(re.search(r"claude|anthropic", n, re.I) for n in nomi) \
                    and any(b.replace(" ", "") == "disallow:/" for b in blocco):
                return False
            if blocco:
                nomi, blocco = [], []
            nomi.append(v)
        elif k in ("disallow", "allow"):
            blocco.append(f"{k}:{v}")
    return True


def prendi(url, timeout=90):
    rich = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9",
                                                "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(rich, timeout=timeout) as r:
        return r.read()


def prepara_sito(nome, host):
    """Scarica robots.txt (se manca), controlla le sezioni AI e restituisce l'oggetto Robots."""
    d = RAW / nome
    d.mkdir(parents=True, exist_ok=True)
    f = d / "robots.txt"
    if not f.exists():
        f.write_bytes(prendi(f"https://{host}/robots.txt"))
        time.sleep(PAUSA)
    testo = f.read_text(encoding="utf-8", errors="replace")
    if not robots_ok_agenti(testo):
        raise SystemExit(f"{nome}: il robots.txt chiude il sito agli agenti AI: mi fermo")
    return VE.Robots(testo)


def scarica_pagine(nome, host, urls, pagina_a_file, estrai_fn, limite=None):
    """Scarica le pagine di `urls` (una coda, pausa fissa), salva con estrai_fn() solo i numeri. Si ferma sui blocchi."""
    rob = prepara_sito(nome, host)
    cart = RAW / nome / "pagine"
    cart.mkdir(parents=True, exist_ok=True)
    log = RAW / nome / "scarico.log"

    def scrivi_log(m):
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")

    todo = [u for u in urls if not pagina_a_file(u).exists()]
    if limite:
        todo = todo[:limite]
    scrivi_log(f"avvio: {len(todo)} schede da scaricare su {len(urls)}, pausa {PAUSA} s, ua={UA}")
    nuove = tentativi = 0
    for i, url in enumerate(todo, 1):
        if not rob.permesso(url):
            scrivi_log("vietato da robots.txt: " + url)
            continue
        time.sleep(PAUSA)
        try:
            dati = prendi(url)
            if re.search(rb"(?i)captcha|are you a robot|access denied|unusual traffic|cf-chl|attention required",
                         dati[:20000]) and len(dati) < 60000:
                scrivi_log("pagina di blocco, mi fermo: " + url)
                print(nome, "BLOCCATO (pagina di verifica)", url)
                return
            out = estrai_fn(url, dati)
            pagina_a_file(url).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            nuove += 1
            tentativi = 0
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                scrivi_log(f"{e.code} {url}")
                pagina_a_file(url).write_text(json.dumps({"url": url, "errore": e.code}), encoding="utf-8")
            elif e.code in (401, 403):
                scrivi_log(f"{e.code} BLOCCO su {url}: mi fermo")
                print(nome, "BLOCCATO", e.code, url)
                return
            elif e.code == 429:
                tentativi += 1
                scrivi_log(f"429 su {url} (tentativo {tentativi})")
                if tentativi >= 3:
                    scrivi_log("429 persistente: mi fermo")
                    print(nome, "BLOCCATO (429 persistenti)")
                    return
                time.sleep(120 * tentativi)
            else:
                scrivi_log(f"errore {e.code} {url}")
        except Exception as e:  # rete: un nuovo giro piu' tardi
            scrivi_log(f"errore {e!r} {url}")
            time.sleep(15)
        if i % 25 == 0:
            print(f"{nome}: {i}/{len(todo)} (nuove {nuove})", flush=True)
    scrivi_log(f"fine: {nuove} schede nuove")
    print(nome, "finito:", nuove, "schede nuove")


def nome_file(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16] + ".json"


# ---------------------------------------------------------------- punteggi e critici
RX_VOTO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:[-–/]\s*(\d+(?:[.,]\d+)?))?\s*\+?\s*(?:/\s*(\d+))?\s*$")


def leggi_voto(testo, scala_default="100"):
    """'92-94/100' -> (93.0, '100', '92-94/100'); '17.5/20' -> (17.5, '20', ..); '95+' -> 95. None se non e' un voto."""
    t = (testo or "").strip().replace(",", ".")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*\+?\s*(?:/\s*(\d+))?\s*$", t)
    if not m:
        return None
    a = float(m.group(1))
    b = float(m.group(2)) if m.group(2) else None
    scala = m.group(3) or scala_default
    if b is not None:
        if b < a:                   # '92-4' = errore di scrittura: scarto
            return None
        v = (a + b) / 2
    else:
        v = a
    if scala not in ("100", "20"):
        return None
    if v > float(scala) or v <= 0:
        return None
    if scala == "100" and v < 50:
        return None
    return round(v, 2), scala, t


PUBBLICAZIONI = {   # nome sulla scheda -> (critico/rivista come nelle altre fonti, usa il recensore tra parentesi)
    "robert parker wine advocate": ("Robert Parker", False), "wine advocate": ("Robert Parker", False),
    "the wine advocate": ("Robert Parker", False), "robert parker": ("Robert Parker", False),
    "vinous": ("Vinous", True), "antonio galloni": ("Vinous (Antonio Galloni)", False),
    "the wine independent": ("The Wine Independent", False), "wine independent": ("The Wine Independent", False),
    "inside bordeaux": ("Jane Anson", False), "jane anson": ("Jane Anson", False),
    "jancis robinson": ("Jancis Robinson", False), "jancisrobinson.com": ("Jancis Robinson", False),
    "decanter": ("Decanter", False), "james suckling": ("James Suckling", False),
    "jamessuckling.com": ("James Suckling", False), "wine spectator": ("Wine Spectator", False),
    "burghound": ("Burghound", False), "allen meadows": ("Burghound", False),
    "jeb dunnuck": ("Jeb Dunnuck", False), "wine enthusiast": ("Wine Enthusiast", False),
    "revue du vin de france": ("Revue du Vin de France", False), "tim atkin": ("Tim Atkin", False),
    "john gilman": ("John Gilman", False), "view from the cellar": ("John Gilman", False),
    "the wine cellar insider": ("Jeff Leve (The Wine Cellar Insider)", False),
    "wine cellar insider": ("Jeff Leve (The Wine Cellar Insider)", False),
    "jean-marc quarin": ("Jean-Marc Quarin", False), "jean marc quarin": ("Jean-Marc Quarin", False),
    "bettane+desseauve": ("Bettane+Desseauve", False), "bettane & desseauve": ("Bettane+Desseauve", False),
    "gambero rosso": ("Gambero Rosso", False), "falstaff": ("Falstaff", False),
    "james halliday": ("James Halliday", False), "wine & spirits": ("Wine & Spirits", False),
    "wine & spirits magazine": ("Wine & Spirits", False), "stephen tanzer": ("Vinous (Stephen Tanzer)", False),
    "international wine cellar": ("Vinous (Stephen Tanzer)", False),
}


def critico_canonico(pubblicazione, recensore):
    p = (pubblicazione or "").strip()
    k = p.lower()
    if k in PUBBLICAZIONI:
        nome, con_rec = PUBBLICAZIONI[k]
        if con_rec and recensore:
            return f"{nome} ({recensore.strip()})"
        return nome
    if not p and recensore:
        return recensore.strip()
    return p + (f" ({recensore.strip()})" if recensore and recensore.strip().lower() not in p.lower() else "")


# ---------------------------------------------------------------- abbinamento da indirizzi (comune a JB)
def entrate_slug(urls, estrai):
    """estrai(url) -> (testo, annata|None) oppure None. Restituisce la lista di Slug-compatibili."""
    class S:
        pass
    out = []
    for u in urls:
        r = estrai(u)
        if not r:
            continue
        s = S()
        s.url = u
        s.testo, s.anno = r
        s.tok = VA.T.tokens(s.testo)
        out.append(s)
    return out


def abbina_slug(vini, prezzo, slugs, max_dist=MAX_DISTANZA_ANNATA):
    """Un vino Peck -> pagine con cantina nello slug, nome uguale parola per parola (VE.stesso_vino_slug), annata
    uguale o a meno di max_dist anni (si tengono solo le piu' vicine). Il formato non conta: il voto del critico
    e' del vino, non della bottiglia."""
    idx = defaultdict(list)
    for i, s in enumerate(slugs):
        for w in s.tok:
            idx[w].append(i)
    out = []
    for v in vini:
        alts = T.tok_cantina(v["cantina"])
        if not alts:
            continue
        cand = set()
        for a in alts:
            liste = [idx.get(w, []) for w in a]
            if liste and all(liste):
                cand.update(set(min(liste, key=len)))
        a_peck = v["annata"] or "NV"
        trovati = []
        for i in cand:
            s = slugs[i]
            d = VA.distanza(a_peck, s.anno)
            if d > max_dist:
                continue
            if not VE.cantina_nello_slug(alts, s.tok):
                continue
            if not VE.stesso_vino_slug(v, alts, s.testo):
                continue
            trovati.append((d, s))
        if not trovati:
            continue
        migliore = min(d for d, _ in trovati)
        for d, s in trovati:
            if d == migliore:
                out.append({"id": v["id"], "url": s.url, "annata_slug": s.anno, "distanza": d,
                            "prezzo": prezzo.get(v["id"], ""), "sotto200": int(prezzo.get(v["id"], 9999) < 200)})
    return out


def scrivi_candidati(nome, righe):
    righe.sort(key=lambda r: (-r["sotto200"], r["distanza"], r["id"]))
    f = RAW / nome / "candidati.csv"
    with open(f, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, ["id", "url", "annata_slug", "distanza", "prezzo", "sotto200"])
        w.writeheader()
        w.writerows(righe)
    ids = {r["id"] for r in righe}
    u200 = {r["id"] for r in righe if r["sotto200"]}
    print(f"{nome:11} vini con candidato {len(ids):4} (sotto 200 euro {len(u200):4}), "
          f"schede da scaricare {len({r['url'] for r in righe}):4}")


def leggi_candidati(nome):
    with open(RAW / nome / "candidati.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- Justerini & Brooks
JB = "justerinis"
JB_HOST = "www.justerinis.com"
RX_JB = re.compile(r'\\"vintageName\\":\\"([^"\\]*)\\",\\"scoreText\\":\\"([^"\\]*)\\",\\"tastingNote\\":.*?'
                   r'\\"dateReviewed\\":\\"([^"\\]*)\\",\\"reviewer\\":\\"([^"\\]*)\\",\\"publication\\":\\"([^"\\]*)\\"', re.S)


def jb_sitemap():
    rob = prepara_sito(JB, JB_HOST)
    f = RAW / JB / "sitemap_product.xml"
    if not f.exists():
        url = f"https://{JB_HOST}/product/sitemap.xml"
        if not rob.permesso(url):
            raise SystemExit("vietato " + url)
        f.write_bytes(prendi(url, 180))
    print("jb sitemap ok:", len(jb_urls()), "schede di annata")


def jb_urls():
    t = (RAW / JB / "sitemap_product.xml").read_text(encoding="utf-8")
    urls = list(dict.fromkeys(htmllib.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", t)))
    return [u for u in urls if re.match(r"https://www\.justerinis\.com/fine-wines/[^/]+/[^/]+/[^/]+/[^/]+/(?:19|20)\d\d$", u)]


def jb_estrai_slug(u):
    p = urllib.parse.urlsplit(u).path.strip("/").split("/")
    produttore, vino, anno = p[3], p[4], p[5]
    testo = (produttore + " " + vino).replace("-", " ")
    return testo, anno


def jb_abbina():
    vini, prezzo = VA.leggi_vini()
    slugs = entrate_slug(jb_urls(), jb_estrai_slug)
    print(len(vini), "vini Peck,", len(slugs), "schede J&B")
    scrivi_candidati(JB, abbina_slug(vini, prezzo, slugs))


def jb_pagina(u):
    return RAW / JB / "pagine" / nome_file(u)


def jb_leggi(url, dati):
    t = dati.decode("utf-8", errors="replace")
    titolo = re.search(r"<title>(.*?)</title>", t, re.S)
    critici, visti = [], set()
    for vint, voto, data, rec, pub in RX_JB.findall(t):
        k = (vint, voto, data, rec, pub)
        if k in visti:
            continue
        visti.add(k)
        critici.append({"annata": vint, "voto": htmllib.unescape(voto), "data": data,
                        "recensore": htmllib.unescape(rec), "pubblicazione": htmllib.unescape(pub)})
    return {"url": url, "titolo": htmllib.unescape(titolo.group(1)).strip() if titolo else "",
            "scaricata": OGGI, "critici": critici}


def jb_scarica(limite=None):
    urls = []
    for r in leggi_candidati(JB):
        if r["url"] not in urls:
            urls.append(r["url"])
    scarica_pagine(JB, JB_HOST, urls, jb_pagina, jb_leggi, limite)


# ---------------------------------------------------------------- Farr Vintners
FARR = "farr"
FARR_HOST = "www.farrvintners.com"
PAUSA_FARR = 2.0


def farr_pagina(u):
    return RAW / FARR / "pagine" / nome_file(u)


def farr_sitemap():
    rob = prepara_sito(FARR, FARR_HOST)
    f = RAW / FARR / "sitemap.xml"
    if not f.exists():
        url = f"https://{FARR_HOST}/sitemap.xml"
        if not rob.permesso(url):
            raise SystemExit("vietato " + url)
        f.write_bytes(prendi(url, 180))
    print("farr sitemap ok:", len(farr_urls()), "schede vino")


def farr_urls():
    """Schede vino della sitemap, dalle piu' recenti (id piu' alto) alle piu' vecchie."""
    t = (RAW / FARR / "sitemap.xml").read_text(encoding="utf-8", errors="replace")
    urls = list(dict.fromkeys(htmllib.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", t)))
    urls = [u for u in urls if "wine.php?wine=" in u]
    return sorted(urls, key=lambda u: -int(re.search(r"wine=(\d+)", u).group(1)))


RX_FARR_TITOLO = re.compile(r"<title>(.*?)</title>", re.S | re.I)
RX_FARR_PROD = re.compile(r"View all wines by ([^<]+)</nobr>", re.S)
RX_FARR_VOTO = re.compile(r'<span class="notranslate wine-score">([^<]*)</span></div><div class="notranslate"><i>([^<]*)</i>')


def farr_leggi(url, dati):
    """Solo titolo, produttore e, per ogni nota, voto + chi l'ha dato e quando. Le note di degustazione non si leggono."""
    t = dati.decode("utf-8", errors="replace")
    titolo = RX_FARR_TITOLO.search(t)
    prod = RX_FARR_PROD.search(t)
    voti = [{"voto": htmllib.unescape(v).strip(), "fonte": htmllib.unescape(f).strip()} for v, f in RX_FARR_VOTO.findall(t)]
    return {"url": url, "titolo": htmllib.unescape(titolo.group(1)).strip() if titolo else "",
            "produttore": htmllib.unescape(prod.group(1)).strip() if prod else "",
            "scaricata": OGGI, "voti": voti}


def farr_scarica(limite=None):
    global PAUSA
    PAUSA = PAUSA_FARR
    scarica_pagine(FARR, FARR_HOST, farr_urls(), farr_pagina, farr_leggi, limite)


MESI = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                    "september", "october", "november", "december"], 1)}
REGIONE_PAESE = {"bordeaux": "FR", "burgundy": "FR", "rhone": "FR", "rhône": "FR", "champagne": "FR", "alsace": "FR",
                 "loire": "FR", "jura": "FR", "france": "FR", "southern france": "FR", "italy": "IT", "germany": "DE",
                 "spain": "ES", "portugal": "PT", "california": "US", "usa": "US", "australia": "AU"}


def farr_critico(testo):
    """'Robert Parker, Wine Advocate (Mar 03), March 2003' -> (critico canonico, anno, mese) ; None se non e' un critico noto."""
    parti = [p.strip() for p in testo.split(",")]
    m = re.search(r"((?:19|20)\d\d)\s*$", testo)
    anno = int(m.group(1)) if m else 0
    mese = 0
    mm = re.search(r"([A-Za-z]+)\s+(?:19|20)\d\d\s*$", testo)
    if mm:
        mese = MESI.get(mm.group(1).lower(), 0)
    chiave = testo.lower()
    for k, nome in FARR_CRITICI:
        if k in chiave:
            return nome, anno, mese
    return None


# cosa si cerca nel testo -> critico come nelle altre fonti (l'ordine conta: i casi piu' specifici prima)
FARR_CRITICI = [("jancis robinson", "Jancis Robinson"), ("robert parker", "Robert Parker"),
                ("wine advocate", "Robert Parker"), ("lisa perrotti-brown", "Robert Parker"),
                ("william kelley", "Robert Parker"), ("neal martin", "Vinous (Neal Martin)"),
                ("antonio galloni", "Vinous (Antonio Galloni)"), ("vinous", "Vinous"),
                ("james suckling", "James Suckling"), ("wine spectator", "Wine Spectator"),
                ("decanter", "Decanter"), ("burghound", "Burghound"), ("allen meadows", "Burghound"),
                ("jeb dunnuck", "Jeb Dunnuck"), ("stephen tanzer", "Vinous (Stephen Tanzer)"),
                ("tim atkin", "Tim Atkin"), ("jean-marc quarin", "Jean-Marc Quarin"),
                ("jane anson", "Jane Anson"), ("wine enthusiast", "Wine Enthusiast"),
                ("revue du vin", "Revue du Vin de France"), ("bettane", "Bettane+Desseauve"),
                ("wine cellar insider", "Jeff Leve (The Wine Cellar Insider)"),
                ("jeff leve", "Jeff Leve (The Wine Cellar Insider)"),
                ("john gilman", "John Gilman"), ("james halliday", "James Halliday"),
                ("falstaff", "Falstaff")]


def farr_cands():
    """Una Cand per scheda Farr, con il voto piu' recente di ciascun critico."""
    cands = []
    for f in sorted((RAW / FARR / "pagine").glob("*.json")) if (RAW / FARR / "pagine").exists() else []:
        pag = json.loads(f.read_text(encoding="utf-8"))
        if pag.get("errore") or not pag.get("titolo"):
            continue
        m = re.match(r"^(.*?)\s+((?:19|20)\d\d)\.\s*Fine Wine from (.+)$", pag["titolo"])
        if not m or not pag.get("produttore"):
            continue
        vino, anno, regione = m.group(1).strip(), m.group(2), m.group(3).strip()
        migliori = {}
        for v in pag["voti"]:
            c = farr_critico(v["fonte"])
            num = re.match(r"\s*(\d+(?:\.\d+)?)", v["voto"])
            scala_def = "20" if num and float(num.group(1)) <= 20 else "100"
            val = leggi_voto(v["voto"].replace("/", "-"), scala_def)   # '89/92' e' un intervallo (voto da botte)
            if not c or not val:
                continue
            punti, scala, testo = val
            nome, anno_v, mese_v = c
            quando = (anno_v, mese_v)
            if nome not in migliori or quando >= migliori[nome][0]:
                migliori[nome] = (quando, punti, scala, v["voto"], v["fonte"])
        if not migliori:
            continue
        paese = REGIONE_PAESE.get(regione.lower(), "")
        voti = [(nome, p, sc, (vt, fonte)) for nome, (q, p, sc, vt, fonte) in migliori.items()]
        c = VA.Cand(pag["produttore"], vino, anno, paese, voti)
        c.url = pag["url"]
        c.titolo = pag["titolo"]
        cands.append(c)
    return cands


# ---------------------------------------------------------------- Wine Spectator Top 100 (Zenodo)
WS = "zenodo_7930185"
WS_NOME = "Wine Spectator Top 100"
WS_URL = "https://doi.org/10.5281/zenodo.7930185"


def ws_scarica():
    d = RAW / WS
    d.mkdir(parents=True, exist_ok=True)
    f = d / "base.xls"
    if not f.exists():
        nome = "Base%20Precios%20y%20Puntajes%2020%2001%202022.xls"
        f.write_bytes(prendi(f"https://zenodo.org/api/records/7930185/files/{nome}/content", 180))
    print("ws ok", f.stat().st_size)


def ws_righe(vini):
    import warnings
    import pandas as pd
    warnings.simplefilter("ignore")
    d = pd.read_excel(RAW / WS / "base.xls", sheet_name="Top 100", engine="xlrd")
    cands = []
    for _, r in d.iterrows():
        try:
            punti = int(r["points"])
        except (ValueError, TypeError):
            continue
        cantina = str(r["winery"]).replace("\xa0", " ").strip()
        nome = str(r["name"]).replace("\xa0", " ").strip()
        vino = nome[len(cantina):].strip() if nome.lower().startswith(cantina.lower()) else nome
        anno = str(int(r["yearvintage"])) if r["yearvintage"] == r["yearvintage"] else ""
        if not anno:
            continue
        paese = VA.PAESI_WE.get({"United States": "US"}.get(str(r["country"]), str(r["country"])), "")
        if not paese and str(r["country"]) == "United States":
            paese = "US"
        c = VA.Cand(cantina, vino, anno, paese, [(f"Wine Spectator (Top 100 del {int(r['yearranking'])})", punti, "100", "")])
        cands.append(c)
    return VA.abbina_fonte(vini, cands, WS_NOME, LIC_WS, lambda x: int(round(x)))


# ---------------------------------------------------------------- estrazione -> voti_extra.csv
def righe_jb(vini_id):
    out = []
    cand = defaultdict(list)
    for r in leggi_candidati(JB):
        cand[r["url"]].append(r)
    for url, rs in cand.items():
        f = jb_pagina(url)
        if not f.exists():
            continue
        pag = json.loads(f.read_text(encoding="utf-8"))
        if pag.get("errore"):
            continue
        anno_url = url.rsplit("/", 1)[1]
        for c in pag["critici"]:
            if c["annata"] != anno_url:
                continue
            v = leggi_voto(c["voto"])
            if not v:
                continue
            voto, scala, testo = v
            for r in rs:
                corr = "esatta" if r["distanza"] == "0" else "annata diversa ±2"
                out.append({"id": r["id"], "fonte": "Justerini & Brooks",
                            "critico_o_tipo": critico_canonico(c["pubblicazione"], c["recensore"]),
                            "voto": voto, "scala": scala, "annata_fonte": anno_url, "corrispondenza": corr,
                            "url": url, "licenza_note": LIC_JB, "voto_testo": testo,
                            "recensore": c["recensore"], "nome_fonte": pag["titolo"],
                            "data_raccolta": pag.get("scaricata", "")})
    return out


def righe_farr(vini):
    cands = farr_cands()
    if not cands:
        return []
    urls = {}
    for c in cands:
        urls.setdefault(f"{c.casa} | {c.vino} | {c.anno}", c.url)
    out = []
    for r in VA.abbina_fonte(vini, cands, "Farr Vintners", LIC_FARR, lambda x: round(float(x), 1)):
        if r["corrispondenza"] == "da controllare":
            continue
        out.append({"id": r["id"], "fonte": "Farr Vintners", "critico_o_tipo": r["critico/rivista"],
                    "voto": r["voto"], "scala": r["scala"], "annata_fonte": r["annata_fonte"],
                    "corrispondenza": "esatta" if r["corrispondenza"] == "esatta" else "annata diversa ±2",
                    "url": urls.get(r["_nome_fonte"], ""), "licenza_note": LIC_FARR, "voto_testo": r["voto"],
                    "recensore": "", "nome_fonte": r["_nome_fonte"], "data_raccolta": OGGI})
    return out


def estrai():
    vini, prezzo = VA.leggi_vini()
    righe = []
    if (RAW / JB / "candidati.csv").exists():
        righe += righe_jb(None)
    if (RAW / WS / "base.xls").exists():
        for r in ws_righe(vini):
            if r["corrispondenza"] == "da controllare":
                continue
            righe.append({"id": r["id"], "fonte": WS_NOME, "critico_o_tipo": "Wine Spectator",
                          "voto": r["voto"], "scala": "100", "annata_fonte": r["annata_fonte"],
                          "corrispondenza": "esatta" if r["corrispondenza"] == "esatta" else "annata diversa ±2",
                          "url": WS_URL, "licenza_note": LIC_WS, "voto_testo": r["voto"],
                          "recensore": r["critico/rivista"], "nome_fonte": r["_nome_fonte"],
                          "data_raccolta": OGGI})
    righe += righe_farr(vini)
    righe = [r for r in righe if r["fonte"] not in FONTI_DA_ESCLUDERE]
    # una riga per (vino, fonte, critico, annata_fonte, voto)
    viste, uniche = set(), []
    for r in righe:
        k = (r["id"], r["fonte"], r["critico_o_tipo"], r["annata_fonte"], r["voto"], r["url"])
        if k not in viste:
            viste.add(k)
            uniche.append(r)
    uniche.sort(key=lambda r: (int(r["id"]), r["fonte"], r["critico_o_tipo"], r["annata_fonte"]))
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, CAMPI, extrasaction="ignore")
        w.writeheader()
        w.writerows(uniche)
    print(len(uniche), "righe in", USCITA.name)
    riepilogo(uniche, prezzo)


def riepilogo(righe=None, prezzo=None):
    if righe is None:
        righe = list(csv.DictReader(open(USCITA, encoding="utf-8-sig", newline="")))
    if prezzo is None:
        prezzo = VA.leggi_vini()[1]
    vini = {v["id"]: v for v in VA.leggi_vini()[0]}
    for fonte in sorted({r["fonte"] for r in righe}):
        for liv in ("esatta", "annata diversa ±2"):
            ids = {r["id"] for r in righe if r["fonte"] == fonte and r["corrispondenza"] == liv}
            u200 = [i for i in ids if prezzo.get(i, 9999) < 200]
            print(f"{fonte:24} {liv:18} vini {len(ids):4} (sotto 200 euro {len(u200):4})")
    ids = {r["id"] for r in righe}
    print("vini con almeno un voto nuovo:", len(ids), "- Bourgogne:",
          sum(1 for i in ids if vini.get(i, {}).get("regione") == "Bourgogne"))
    print("critici:", Counter(r["critico_o_tipo"] for r in righe).most_common(15))


def verifica(n=30):
    righe = list(csv.DictReader(open(USCITA, encoding="utf-8-sig", newline="")))
    vini = {v["id"]: v for v in VA.leggi_vini()[0]}
    per_vino = {}
    for r in righe:
        per_vino.setdefault((r["id"], r["fonte"], r["url"]), r)
    random.seed(7)
    chiavi = random.sample(sorted(per_vino), min(n, len(per_vino)))
    out = []
    for k in chiavi:
        r = per_vino[k]
        v = vini[r["id"]]
        riga = (f"[{r['fonte'][:6]}|{r['corrispondenza']}] PECK: {v['cantina']} | {v['nome']} | {v['annata']}"
                f"   <->   FONTE: {r['nome_fonte'] or r['url']} | {r['annata_fonte']}   ({r['critico_o_tipo']} {r['voto_testo']})")
        print(riga)
        out.append(riga)
    (RAW / "_controllo_a_mano_extra.txt").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
    fn = {"jb_sitemap": jb_sitemap, "jb_abbina": jb_abbina, "jb_scarica": lambda: jb_scarica(arg),
          "farr_sitemap": farr_sitemap, "farr_scarica": lambda: farr_scarica(arg),
          "ws_scarica": ws_scarica, "estrai": estrai, "riepilogo": riepilogo,
          "verifica": lambda: verifica(arg or 30)}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
