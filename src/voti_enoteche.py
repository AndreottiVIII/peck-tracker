"""Voti dei critici dalle schede di cinque enoteche online (solo numeri e nomi dei critici, mai i testi).

    python -I src/voti_enoteche.py sitemap            # scarica robots.txt e le sitemap dei prodotti in data/raw/voti/<enoteca>/
    python -I src/voti_enoteche.py abbina             # pre-abbinamento coi nomi negli indirizzi -> <enoteca>/candidati.csv
    python -I src/voti_enoteche.py scarica <enoteca>  # scarica SOLO le schede candidate (una coda per sito, pausa fissa)
    python -I src/voti_enoteche.py estrai             # legge le schede scaricate -> data/voti_enoteche.csv
    python -I src/voti_enoteche.py verifica [N]       # N righe a caso da controllare a mano
    python -I src/voti_enoteche.py riepilogo          # conteggi per il rapporto

Enoteche (tutte con robots.txt che lascia aperte le schede prodotto, riletto a ogni avvio):
  bbr         Berry Bros & Rudd: JSON-LD `review` di tipo CriticReview. Il suo robots.txt NON nomina ClaudeBot e simili
              (chiude CCBot, Amazonbot, ImagesiftBot... ma non tocca noi) e per tutti chiede pausa di 10 s
              (Crawl-delay) e visite solo 02:00-07:00 UTC (Visit-time): si scarica solo in quella finestra, a 10 s
              (`python -I src/voti_enoteche.py bbr_sitemap`, poi `abbina`, poi `scarica bbr`).
  millesima   Millesima.fr: JSON `__NEXT_DATA__` (elenco `ratings`).
  callmewine  Callmewine.com: elenco `awards` nei dati della pagina (valore, massimo, tipo).
  zachys      Zachys.com (Shopify): blocco HTML "Critic Reviews". Chiede agli agenti di dichiararsi:
              si usa uno User-Agent che dice chi siamo, mai uno da browser.
  xtrawine    Xtrawine.com (Shopify): icone dei premi nella scheda.

Regole: pausa di 3 s per sito (BBR 10 s), una coda per sito, mai oltre i limiti del robots.txt, mai aggirare
un blocco (403/429 persistenti = si ferma quel sito). L'abbinamento riusa la normalizzazione di tannico.py e
voti_aperti.py ed e' prudente: nome uguale parola per parola, stessa annata (o a meno di 2 anni) e stesso formato.
"""
import csv
import html as htmllib
import json
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tannico as T  # noqa: E402
import voti_aperti as VA  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
RAW = RADICE / "data" / "raw" / "voti"
USCITA = RADICE / "data" / "voti_enoteche.csv"
DATA_RACCOLTA = "2026-10-25"

UA_BROWSER = T.UA_BROWSER
UA_DICHIARATO = "Mozilla/5.0 (compatible; peck-tracker research; non-commercial)"

# enoteca -> (host, pausa in secondi, User-Agent)
ENOTECHE = {
    "millesima": ("www.millesima.fr", 3.0, UA_BROWSER),
    "callmewine": ("www.callmewine.com", 3.0, UA_BROWSER),
    "zachys": ("www.zachys.com", 3.0, UA_DICHIARATO),
    "xtrawine": ("www.xtrawine.com", 3.0, UA_BROWSER),
    "bbr": ("www.bbr.com", 10.0, UA_BROWSER),
}
NOMI_FONTE = {"millesima": "Millesima", "callmewine": "Callmewine",
              "zachys": "Zachys", "xtrawine": "Xtrawine", "bbr": "Berry Bros & Rudd"}
MAX_DISTANZA_ANNATA = 2
CAMPI = ["id", "fonte", "url", "critico", "voto", "scala", "annata_fonte", "litri_fonte", "corrispondenza",
         "data_raccolta"]


# ---------------------------------------------------------------- robots.txt
class Robots:
    """Regole `User-agent: *` di un robots.txt, con * e $ (il modulo urllib non li capisce)."""

    def __init__(self, testo):
        self.regole = []   # (permesso, schema)
        self.ritardo = None
        attivo = False
        for riga in testo.splitlines():
            riga = riga.split("#", 1)[0].strip()
            if ":" not in riga:
                continue
            k, v = (x.strip() for x in riga.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                attivo = (v == "*")
            elif attivo and k == "disallow" and v:
                self.regole.append((False, v))
            elif attivo and k == "allow" and v:
                self.regole.append((True, v))
            elif attivo and k == "crawl-delay":
                try:
                    self.ritardo = float(v)
                except ValueError:
                    pass

    @staticmethod
    def _rx(schema):
        p = re.escape(schema).replace(r"\*", ".*")
        return re.compile("^" + (p[:-2] + "$" if p.endswith(r"\$") else p))

    def permesso(self, url):
        u = urllib.parse.urlsplit(url)
        percorso = u.path + (("?" + u.query) if u.query else "")
        migliore = (-1, True)
        for ok, schema in self.regole:
            if self._rx(schema).match(percorso):
                if (len(schema), ok) > migliore:
                    migliore = (len(schema), ok)
        return migliore[1]


def robots_di(nome):
    return Robots((RAW / nome / "robots.txt").read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- scarico di base
def prendi(url, ua, timeout=90):
    rich = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
                                                "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(rich, timeout=timeout) as r:
        return r.read()


# sitemap dei soli prodotti, per enoteca (indirizzo -> file locale)
def elenco_sitemap(nome):
    host, _, ua = ENOTECHE[nome]
    d = RAW / nome
    if nome == "bbr":
        idx = (d / "sitemap.xml").read_text(encoding="utf-8")
        locs = [htmllib.unescape(x) for x in re.findall(r"<loc>([^<]+)</loc>", idx)]
        return [(u, d / re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.urlsplit(u).path.strip("/"))) for u in locs
                if "product" in u.lower()]
    if nome == "millesima":
        return [("https://www.millesima.fr/sitemap/product_11652.xml", d / "product_11652.xml")]
    if nome == "callmewine":
        return [("https://www.callmewine.com/sitemap/pdp-it.xml", d / "pdp-it.xml")]
    idx = (d / "sitemap.xml").read_text(encoding="utf-8")
    out = []
    for loc in re.findall(r"<loc>([^<]*sitemap_products_\d+\.xml[^<]*)</loc>", idx):
        loc = htmllib.unescape(loc)
        n = re.search(r"sitemap_products_(\d+)", loc).group(1)
        out.append((loc, d / f"sitemap_products_{n}.xml"))
    return out


def bbr_sitemap():
    """Berry Bros & Rudd: robots.txt, indice e sitemap dei prodotti, SOLO dentro la finestra 02:00-07:00 UTC, pausa 10 s."""
    host, pausa, ua = ENOTECHE["bbr"]
    d = RAW / "bbr"
    d.mkdir(parents=True, exist_ok=True)

    def aspetta():
        txt = (d / "robots.txt").read_text(encoding="utf-8", errors="replace") if (d / "robots.txt").exists() else             "Visit-time: 0200-0700"
        while True:
            ok, attesa = finestra_ok("bbr", txt)
            if ok:
                return
            print("fuori finestra, attendo", attesa, "s", flush=True)
            time.sleep(min(attesa, 1800))

    aspetta()
    (d / "robots.txt").write_bytes(prendi(f"https://{host}/robots.txt", ua))
    rob = Robots((d / "robots.txt").read_text(encoding="utf-8", errors="replace"))
    time.sleep(pausa)
    for url in ("https://www.bbr.com/sitemap.xml",):
        if not rob.permesso(url):
            print("vietato", url)
            return
        aspetta()
        (d / "sitemap.xml").write_bytes(prendi(url, ua, 120))
        time.sleep(pausa)
    for url, f in elenco_sitemap("bbr"):
        if not f.exists():
            if not rob.permesso(url):
                print("vietato", url)
                continue
            aspetta()
            print("scarico", url, flush=True)
            f.write_bytes(prendi(url, ua, 180))
            time.sleep(pausa)
    print("bbr sitemap ok")


def scarica_sitemap():
    for nome, (host, pausa, ua) in ENOTECHE.items():
        if nome == "bbr":      # solo nella sua finestra oraria: vedi bbr_sitemap()
            continue
        d = RAW / nome
        d.mkdir(parents=True, exist_ok=True)
        rob = prendi(f"https://{host}/robots.txt", ua)
        (d / "robots.txt").write_bytes(rob)
        time.sleep(pausa)
        if not (d / "sitemap.xml").exists():
            idx = {"bbr": "https://www.bbr.com/sitemap.xml", "callmewine": "https://www.callmewine.com/sitemap.xml",
                   "zachys": "https://www.zachys.com/sitemap.xml", "xtrawine": "https://www.xtrawine.com/sitemap.xml"}
            if nome in idx:
                (d / "sitemap.xml").write_bytes(prendi(idx[nome], ua))
                time.sleep(pausa)
        for url, f in elenco_sitemap(nome):
            if not f.exists():
                print("scarico", url)
                f.write_bytes(prendi(url, ua, 180))
                time.sleep(pausa)
        print(nome, "ok")


# ---------------------------------------------------------------- indirizzi -> vino
REGIONI_BBR = set("""burgundy bordeaux rhone champagne loire alsace provence languedoc roussillon beaujolais jura savoie
sud ouest corsica italy tuscany piedmont veneto sicily umbria abruzzo friuli campania spain portugal germany austria
california usa oregon washington australia new zealand argentina chile south africa lebanon greece hungary
switzerland england canada uruguay israel slovenia croatia mosel rheingau pfalz napa sonoma barossa
marlborough mendoza douro rioja ribera duero priorat sherry madeira port""".split())
MAX_FORMATO_ML = 30000


def anno_e_testo(nome, url):
    """(testo senza anno e senza formato per i confronti, annata '2015'|'NV'|None se piu' annate, ml del formato)."""
    u = urllib.parse.urlsplit(url).path.rstrip("/")
    if nome == "bbr":
        s = re.sub(r"^/products-\d+-", "", u)
    elif nome == "millesima":
        s = re.sub(r"\.html$", "", u.lstrip("/"))
    elif nome == "callmewine":
        s = re.sub(r"-P\d+\.htm$", "", u.lstrip("/"))
    else:
        s = re.sub(r"^/products/", "", u)
    t = s.replace("-", " ")
    anni = {a for a in re.findall(r"(?<![0-9])((?:19|20)\d\d)(?![0-9])", t)}
    if len(anni) > 1:
        return None, None, None
    anno = anni.pop() if anni else "NV"
    ml = T.formato_esplicito(t) or 750
    if nome == "bbr":
        # tolgo dalla coda le regioni/paesi (burgundy, rhone, california usa...)
        parole = t.split()
        while parole and T.norm(parole[-1]) in REGIONI_BBR:
            parole.pop()
        t = " ".join(parole)
    return t, anno, ml


class Slug:
    def __init__(self, nome, url):
        self.url = url
        testo, self.anno, self.ml = anno_e_testo(nome, url)
        self.ok = testo is not None
        self.testo = testo or ""
        self.tok = VA.T.tokens(self.testo) if self.ok else set()


def lista_url(nome):
    urls = []
    for _, f in elenco_sitemap(nome):
        t = f.read_text(encoding="utf-8", errors="replace")
        urls += [htmllib.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", t)]
    if nome in ("zachys", "xtrawine"):
        urls = [u for u in urls if "/products/" in u]
    elif nome == "bbr":
        urls = [u for u in urls if re.search(r"/products-\d+-", u)]
    elif nome == "callmewine":
        urls = [u for u in urls if u.endswith(".htm")]
    else:
        urls = [u for u in urls if u.endswith(".html")]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def simile_parola(a, b):
    return len(a) >= 6 and len(b) >= 6 and T.simili(a, b) and not (a.isdigit() or b.isdigit())


def uguali_con_varianti(a, b):
    """Due insiemi di parole uguali, salvo varianti di scrittura (Mazy / Mazis)."""
    if a == b:
        return True
    da, db = a - b, b - a
    if len(da) != len(db):
        return False
    db = set(db)
    for w in da:
        m = next((x for x in db if simile_parola(w, x)), None)
        if m is None:
            return False
        db.discard(m)
    return True


def cantina_nello_slug(alts, tok):
    for a in alts:
        if all(w in tok or any(simile_parola(w, x) for x in tok) for w in a):
            return True
    return False


COLORI = {"rouge": "rosso", "rosso": "rosso", "red": "rosso", "tinto": "rosso", "noir": "rosso",
          "blanc": "bianco", "bianco": "bianco", "white": "bianco", "blanco": "bianco"}


CRU = {"cru", "grand", "1er", "premier", "classe"}


def stesso_vino_slug(v, alts, testo_slug):
    """Nome uguale parola per parola, tolta la cantina; denominazioni/vitigni ignorabili solo se stanno da una parte.
    'Brut' da solo e' ignorabile (Peck lo omette spesso); 'rouge/blanc' che Peck non scrive contano solo se
    il colore e' quello del vino Peck (altrimenti e' un altro vino: Domaine de Chevalier rosso / bianco)."""
    togli = set().union(*alts)
    testo_slug = re.sub(r"d(alba|asti|abruzzo|alsazia)", r"", testo_slug)    # d'Alba scritto "dalba" negli indirizzi
    np_, ip = VA.nucleo_stretto(v["nome"], togli)
    nf, i_f = VA.nucleo_stretto(testo_slug, togli)
    for ins, ign in ((np_, ip), (nf, i_f)):
        # "Grand Cru Classe", "1er Cru": Peck e i negozi li scrivono o li omettono; il nome vero resta richiesto uguale
        for w in CRU & ins:
            ins.discard(w)
            ign.add(w)
        if "brut" in ins:
            ins.discard("brut")
            ign.add("brut")
    for w in sorted((nf - np_) & set(COLORI)):
        if v.get("tipo") not in ("rosso", "bianco") or COLORI[w] != v["tipo"]:
            return False
        nf.discard(w)
    if not uguali_con_varianti(np_, nf):
        return False
    return ip <= i_f or i_f <= ip


def abbina_enoteca(nome, vini, prezzo):
    slugs = [s for s in (Slug(nome, u) for u in lista_url(nome)) if s.ok]
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
        ml_peck = T.formato_peck(v) or 750
        trovati = []
        for i in cand:
            s = slugs[i]
            if s.ml != ml_peck:
                continue
            d = VA.distanza(a_peck, s.anno)
            if d > MAX_DISTANZA_ANNATA:
                continue
            if not cantina_nello_slug(alts, s.tok):
                continue
            if not stesso_vino_slug(v, alts, s.testo):
                continue
            trovati.append((d, s))
        if not trovati:
            continue
        trovati.sort(key=lambda x: x[0])
        migliore = trovati[0][0]
        for d, s in trovati:
            if d == migliore:       # sempre la/le annate piu' vicine; a pari distanza (+/-) tutte
                out.append({"id": v["id"], "enoteca": nome, "url": s.url, "annata_slug": s.anno,
                            "litri_slug": s.ml / 1000, "distanza": d,
                            "prezzo": prezzo.get(v["id"], ""), "sotto200": int(prezzo.get(v["id"], 9999) < 200)})
    return out


def abbina():
    vini, prezzo = VA.leggi_vini()
    print(len(vini), "vini Peck")
    for nome in ENOTECHE:
        if nome == "bbr" and not (RAW / "bbr" / "sitemap.xml").exists():
            continue
        righe = abbina_enoteca(nome, vini, prezzo)
        # priorita': sotto 200 euro, poi annata esatta, poi in ordine di id
        righe.sort(key=lambda r: (-r["sotto200"], r["distanza"], r["id"]))
        f = RAW / nome / "candidati.csv"
        with open(f, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, ["id", "enoteca", "url", "annata_slug", "litri_slug", "distanza", "prezzo", "sotto200"])
            w.writeheader()
            w.writerows(righe)
        ids = {r["id"] for r in righe}
        urls = {r["url"] for r in righe}
        u200 = {r["id"] for r in righe if r["sotto200"]}
        print(f"{nome:11} vini con candidato {len(ids):4} (sotto 200 euro {len(u200):4}), schede da scaricare {len(urls):4}")


# ---------------------------------------------------------------- scarico delle schede candidate
def nome_file(url):
    u = urllib.parse.urlsplit(url).path.strip("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", u)[:180] + ".html"


def leggi_candidati(nome):
    with open(RAW / nome / "candidati.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def finestra_ok(nome, robots_testo):
    """BBR: Visit-time 02:00-07:00 UTC. Altri siti: sempre."""
    m = re.search(r"Visit-time:\s*(\d{4})-(\d{4})", robots_testo) if nome == "bbr" else None
    if not m:
        return True, 0
    a, b = int(m.group(1)), int(m.group(2))
    ora = datetime.now(timezone.utc)
    hhmm = ora.hour * 100 + ora.minute
    if a <= hhmm < b:
        return True, 0
    # secondi alla prossima apertura
    prossima = ora.replace(hour=a // 100, minute=a % 100, second=0, microsecond=0)
    if prossima <= ora:
        prossima += timedelta(days=1)
    return False, max(30, int((prossima - ora).total_seconds()))


def scarica_schede(nome, limite=None):
    host, pausa, ua = ENOTECHE[nome]
    rob_testo = (RAW / nome / "robots.txt").read_text(encoding="utf-8", errors="replace")
    rob = Robots(rob_testo)
    if rob.ritardo:
        pausa = max(pausa, rob.ritardo)
    cart = RAW / nome / "pagine"
    cart.mkdir(parents=True, exist_ok=True)
    log = RAW / nome / "scarico.log"
    urls = []
    for r in leggi_candidati(nome):
        if r["url"] not in urls:
            urls.append(r["url"])
    if limite:
        urls = urls[:limite]

    def scrivi_log(msg):
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")

    scrivi_log(f"avvio: {len(urls)} schede candidate, pausa {pausa} s, ua={ua[:30]}")
    nuove = salta = 0
    for i, url in enumerate(urls, 1):
        f = cart / nome_file(url)
        if f.exists():
            continue
        if not rob.permesso(url):
            scrivi_log("vietato da robots.txt, salto " + url)
            salta += 1
            continue
        tentativi = 0
        while True:
            ok, attesa = finestra_ok(nome, rob_testo)
            if ok:
                break
            scrivi_log(f"fuori dalla finestra consentita, attendo {attesa} s")
            time.sleep(min(attesa, 1800))
        time.sleep(pausa)
        try:
            dati = prendi(url, ua, 90)
            if re.search(rb"(?i)captcha|are you a robot|access denied|unusual traffic|cf-chl|attention required", dati[:20000]) \
                    and len(dati) < 60000:
                scrivi_log("pagina di blocco, mi fermo: " + url)
                print(nome, "BLOCCATO (pagina di verifica)", url)
                return
            f.write_bytes(dati)
            nuove += 1
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                scrivi_log(f"{e.code} {url}")
                f.with_suffix(".404").write_text(str(e.code))
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
            print(f"{nome}: {i}/{len(urls)} (nuove {nuove})", flush=True)
    scrivi_log(f"fine: {nuove} schede nuove, {salta} vietate")
    print(nome, "finito:", nuove, "schede nuove")


# ---------------------------------------------------------------- estrazione dalle schede
NOMI_CRITICI = dict(T.NOMI_CRITICI)
NOMI_CRITICI.update({
    "j suckling": "James Suckling", "js": "James Suckling", "rp": "Robert Parker",
    "robert parker s wine advocate": "Robert Parker", "robert parker wine advocate": "Robert Parker",
    "wine advocate": "Robert Parker", "parker": "Robert Parker", "the wine advocate": "Robert Parker",
    "wa": "Robert Parker", "ws": "Wine Spectator", "we": "Wine Enthusiast",
    "vinous neal martin": "Vinous (Neal Martin)", "neal martin": "Vinous (Neal Martin)",
    "antonio galloni": "Vinous (Antonio Galloni)", "galloni": "Vinous (Antonio Galloni)",
    "jr": "Jancis Robinson", "jancis robinson mw": "Jancis Robinson",
    "revue du vin de france": "Revue du Vin de France", "rvf": "Revue du Vin de France",
    "la revue du vin de france": "Revue du Vin de France",
    "the wine independent": "The Wine Independent", "wine independent": "The Wine Independent",
    "gambero rosso": "Gambero Rosso", "vitae": "Vitae (AIS)", "vitae ais": "Vitae (AIS)", "ais": "Vitae (AIS)",
    "decanter": "Decanter", "wine spectator": "Wine Spectator", "falstaff": "Falstaff",
    "bettane desseauve": "Bettane+Desseauve", "bettane et desseauve": "Bettane+Desseauve", "burghound": "Burghound",
    "allen meadows": "Burghound", "jeb dunnuck": "Jeb Dunnuck", "jeff leve": "Jeff Leve (The Wine Cellar Insider)",
    "wine cellar insider": "Jeff Leve (The Wine Cellar Insider)", "tim atkin": "Tim Atkin",
    "james halliday": "James Halliday", "veronelli": "Veronelli", "i vini di veronelli": "Veronelli",
    "luca maroni": "Luca Maroni", "bibenda": "Bibenda", "doctor wine": "Doctor Wine", "slow wine": "Slow Wine",
    "gilbert gaillard": "Gilbert & Gaillard", "gilbert et gaillard": "Gilbert & Gaillard",
    "guide hachette": "Hachette", "hachette": "Hachette",
    "j robinson": "Jancis Robinson", "la rvf": "Revue du Vin de France", "bettane e desseauve": "Bettane+Desseauve",
    "figaro": "Le Figaro Vin", "le figaro vin": "Le Figaro Vin", "meadow": "Burghound",
    "r gabriel": "René Gabriel", "rene gabriel": "René Gabriel", "terre de vins": "Terre de Vins",
    "terres de vins": "Terre de Vins", "vinous a galloni": "Vinous (Antonio Galloni)", "vinous media": "Vinous",
    "wein wisser": "Weinwisser", "weinwisser": "Weinwisser", "kerin o keefe": "Kerin O'Keefe",
})
# nomi che Millesima mostra ma che non identificano un critico: "Wine Decider" (non e' una testata nota, non si sa
# chi sia) e "Alexandre Ma" (nome troncato dal sito, voto "94-/100")
CRITICI_SCARTATI = {"wine decider", "alexandre ma", "gardini notes"}
SCALA_ICONE = {"Bibenda": "grappoli", "Gambero Rosso": "bicchieri", "Vitae (AIS)": "viti", "Veronelli": "stelle",
               "Slow Wine": "chiocciole"}


def nome_critico(n):
    n = htmllib.unescape(re.sub(r"\s+", " ", n or "").strip())
    return NOMI_CRITICI.get(T.norm(n), n)


def numero(txt):
    """Primo numero (virgola o punto) di un testo, oppure None. Un intervallo (90-92: assaggi da botte, primeur)
    NON si usa: (None, True). Cosi' nel csv ci sono solo voti pubblicati cosi' come sono."""
    t = (txt or "").replace(",", ".")
    if re.search(r"\d\s*[-–]\s*\d", t):
        return None, True
    m = re.search(r"\d+(?:\.\d+)?", t)
    return (float(m.group(0)), False) if m else (None, False)


def formatta(x):
    return str(int(round(x))) if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def voce(critico, valore, scala):
    """Una riga (critico, voto, scala) se il voto e' plausibile, altrimenti None."""
    if valore is None:
        return None
    try:
        scala_n = float(scala)
    except ValueError:
        scala_n = None
    if scala_n == 100 and not (50 <= valore <= 100):
        return None
    if scala_n == 20 and not (8 <= valore <= 20):
        return None
    if scala_n is None and valore <= 0:
        return None
    return (nome_critico(critico), formatta(valore), scala)


class Scheda:
    """Quello che serve di una scheda: testo d'identita', annata, ml e voti [(critico, voto, scala)]."""

    def __init__(self):
        self.identita = ""
        self.anno = None
        self.ml = None
        self.voti = []


def json_ld_prodotto(t):
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', t, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict):
                if x.get("@type") == "Product":
                    return x
                g = x.get("@graph")
                for y in g if isinstance(g, list) else []:
                    if isinstance(y, dict) and y.get("@type") == "Product":
                        return y
    return None


def anno_da_testo(txt):
    anni = re.findall(r"(?<![0-9])((?:19|20)\d\d)(?![0-9])", txt or "")
    return anni[-1] if anni else None


def estrai_bbr(t):
    s = Scheda()
    p = json_ld_prodotto(t) or {}
    marca = p.get("brand")
    marca = marca.get("name", "") if isinstance(marca, dict) else (marca or "")
    s.identita = f"{p.get('name', '')} {marca}"
    rec = p.get("review") or []
    if isinstance(rec, dict):
        rec = [rec]
    for r in rec:
        if not isinstance(r, dict) or "CriticReview" not in str(r.get("@type")):
            continue
        rr = r.get("reviewRating") or {}
        try:
            val = float(str(rr.get("ratingValue")).replace(",", "."))
            migliore = float(str(rr.get("bestRating", 5)).replace(",", "."))
        except ValueError:
            continue
        autore = r.get("author")
        if isinstance(autore, dict):
            autore = autore.get("name")
        testata = r.get("publisher") or r.get("sourceOrganization") or r.get("itemReviewed") or {}
        if isinstance(testata, dict):
            testata = testata.get("name")
        crit = testata or autore or ""
        v = voce(crit, val * 100 / migliore if migliore else None, "100")
        if v:
            s.voti.append(v)
    s.anno = anno_da_testo(p.get("name", ""))
    return s


def estrai_millesima(t):
    s = Scheda()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    if not m:
        return s
    d = json.loads(m.group(1))
    pp = d["props"]["pageProps"]
    c = pp.get("initialReduxState", {}).get("product", {}).get("content", {}) or {}
    a = c.get("attributes", {}) or {}

    def val(k):
        x = a.get(k)
        if isinstance(x, list):
            x = x[0] if x else {}
        return (x or {}).get("value", "") if isinstance(x, dict) else ""

    s.identita = f"{val('producteur')} {val('produit')} {c.get('title', '')}"
    mil = val("millesime")
    s.anno = mil if re.fullmatch(r"(19|20)\d\d", mil or "") else ("NV" if mil in ("0000", "NV", "") else None)
    fm = a.get("format")
    if isinstance(fm, dict):
        fm = [fm]
    capacita = set()
    for x in fm or []:
        mm = re.match(r"(\d+)\s*CL", str(x.get("shortValue", "")).upper())
        if mm:
            capacita.add(int(mm.group(1)) * 10)
    s.ml = capacita.pop() if len(capacita) == 1 else None
    visti = set()
    for r in pp.get("ratings") or []:
        crit = r.get("critic") or ""
        if crit.strip() == "Vinous" and (r.get("author") or "").strip():
            crit = "Vinous (" + r["author"].strip() + ")"      # Vinous (Antonio Galloni), (Neal Martin)...
        if T.norm(crit) in CRITICI_SCARTATI:
            continue
        nota = str(r.get("note") or "")
        mm = re.match(r"\s*(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\s*(?:/\s*(\d+))?", nota)
        if not mm:
            continue
        valore, _ = numero(mm.group(1))
        v = voce(crit, valore, mm.group(2) or "100")
        if v and v not in visti:
            visti.add(v)
            s.voti.append(v)
    # molte schede hanno l'elenco `ratings` vuoto ma le note negli attributi note_*: stesso voto = una riga sola
    for k, x in a.items():
        if not k.startswith("note_") or not isinstance(x, dict):
            continue
        nota = str(x.get("value") or "")
        mm = re.match(r"\s*(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\s*(?:/\s*(\d+))?", nota)
        if not mm:
            continue
        valore, _ = numero(mm.group(1))
        nome_c = x.get("name", "")
        if T.norm(nome_c) in CRITICI_SCARTATI:
            continue
        v = voce(nome_c, valore, mm.group(2) or ("20" if k == "note_jr" else "100"))
        if v and v not in visti:
            visti.add(v)
            s.voti.append(v)
    return s


def estrai_callmewine(t):
    s = Scheda()
    p = json_ld_prodotto(t) or {}
    marca = p.get("brand", {}).get("name", "") if isinstance(p.get("brand"), dict) else ""
    s.identita = f"{p.get('name', '')} {marca}"
    u = t.replace('\\"', '"')
    mm = re.search(r'"vintageYear":\{[^{}]*?"key":"([^"]*)"', u)
    if mm:
        s.anno = mm.group(1) if re.fullmatch(r"(19|20)\d\d", mm.group(1)) else "NV"
    else:
        s.anno = anno_da_testo(p.get("name", ""))
    mm = re.search(r'"size":\{[^{}]*?"name":"([^"]*)"', u)
    if mm:
        s.ml = T.formato_esplicito(mm.group(1))
    mm = re.search(r'"awards":\{"items":\[(.*?)\]\}', u, re.S)
    if mm:
        try:
            items = json.loads("[" + mm.group(1) + "]")
        except ValueError:
            items = []
        for it in items:
            crit = nome_critico(it.get("title", ""))
            try:
                valore, mx = float(it.get("value")), float(it.get("maxValue"))
            except (TypeError, ValueError):
                continue
            if it.get("type") == "icona" or mx not in (100, 20):
                scala = SCALA_ICONE.get(crit, "su " + formatta(mx))
                v = (crit, formatta(valore), scala) if valore > 0 else None
            else:
                v = voce(crit, valore, formatta(mx))
            if v:
                s.voti.append(v)
    return s


def estrai_zachys(t):
    s = Scheda()
    mm = re.search(r"<title>(.*?)</title>", t, re.S)
    titolo = htmllib.unescape(re.sub(r"\s+", " ", mm.group(1))).strip() if mm else ""
    nome = titolo.split("|")[0].strip()
    s.identita = nome
    s.anno = anno_da_testo(nome) or "NV"
    s.ml = T.formato_esplicito(nome)
    for blocco in re.split(r'class="testimonial__item\b', t)[1:]:
        c = re.search(r'testimonial__user__name"[^>]*>\s*<strong>(.*?)</strong>', blocco, re.S)
        h = re.search(r'testimonial__heading"[^>]*>\s*<strong>(.*?)</strong>', blocco, re.S)
        if not c or not h:
            continue
        crit = re.sub(r"<[^>]+>", "", c.group(1))
        if T.norm(crit) in CRITICI_SCARTATI:
            continue
        testo = htmllib.unescape(re.sub(r"<[^>]+>", "", h.group(1)))
        if not re.search(r"(?i)points?|pts|/\s*(100|20)", testo):
            continue
        valore, _ = numero(testo)
        scala = "20" if re.search(r"(?i)jancis|robinson", crit) else "100"
        v = voce(crit, valore, scala)
        if v:
            s.voti.append(v)
    return s


def estrai_xtrawine(t):
    s = Scheda()
    mm = re.search(r"<title>(.*?)</title>", t, re.S)
    titolo = htmllib.unescape(re.sub(r"\s+", " ", mm.group(1))).strip() if mm else ""
    p = json_ld_prodotto(t) or {}
    nome = str(p.get("name", ""))
    s.identita = nome if nome else titolo.split("|")[0]
    s.anno = anno_da_testo(nome) or anno_da_testo(titolo)
    s.ml = T.formato_esplicito(titolo) or T.formato_esplicito(nome)
    for m in re.finditer(r'<div class="awardbox\b.*?</li>', t, re.S):
        b = m.group(0)
        logo = re.search(r'awardLogo">\s*(?:<img[^>]*src="[^"]*?/files/([^?"/]+)\?|([^<]*?)\s*</span>)', b, re.S)
        if not logo:
            continue
        if logo.group(1):
            crit = re.sub(r"\.(webp|png|jpg|svg)$", "", logo.group(1))
            crit = re.sub(r"^logo-", "", crit).replace("-", " ")
        else:
            crit = logo.group(2)
        dot = re.search(r'<span class="awarddot">(.*?)</span>\s*</div>', b, re.S)
        testo = re.sub(r"<[^>]+>", " ", dot.group(1)) if dot else ""
        m2 = re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+)", testo)
        if m2:
            valore, _ = numero(m2.group(1))
            v = voce(crit, valore, m2.group(2))
        else:
            n_icone = len(re.findall(r'class="aw-icon\b', b))
            nc = nome_critico(crit)
            v = (nc, str(n_icone), SCALA_ICONE[nc]) if n_icone and nc in SCALA_ICONE else None
        if v:
            s.voti.append(v)
    return s


ESTRATTORI = {"bbr": estrai_bbr, "millesima": estrai_millesima, "callmewine": estrai_callmewine,
              "zachys": estrai_zachys, "xtrawine": estrai_xtrawine}


def verifica_pagina(v, alts, riga, sch):
    """(corrispondenza, annata_fonte, litri) se la scheda e' davvero quel vino, altrimenti None."""
    a_peck = v["annata"] or "NV"
    anno = sch.anno or riga["annata_slug"]
    ml = sch.ml or int(round(float(riga["litri_slug"]) * 1000))
    if ml != (T.formato_peck(v) or 750):
        return None
    d = VA.distanza(a_peck, anno)
    if d > MAX_DISTANZA_ANNATA:
        return None
    # il titolo della scheda (a volte senza cantina) non deve contraddire il nome gia' accettato dall'indirizzo
    if not stesso_vino_slug(v, alts, sch.identita):
        return None
    return ("esatta" if d == 0 else "annata diversa"), anno, ml / 1000


def estrai():
    vini, _ = VA.leggi_vini()
    V = {v["id"]: v for v in vini}
    uscita = []
    stat = Counter()
    for nome in ENOTECHE:
        if not (RAW / nome / "candidati.csv").exists():
            continue
        cart = RAW / nome / "pagine"
        cache = {}
        for riga in leggi_candidati(nome):
            f = cart / nome_file(riga["url"])
            if not f.exists():
                stat[nome, "non scaricata"] += 1
                continue
            if riga["url"] not in cache:
                try:
                    cache[riga["url"]] = ESTRATTORI[nome](f.read_text(encoding="utf-8", errors="replace"))
                except Exception as e:  # una scheda strana non ferma le altre
                    print("errore estrazione", nome, riga["url"], repr(e), file=sys.stderr)
                    cache[riga["url"]] = Scheda()
            sch = cache[riga["url"]]
            v = V[riga["id"]]
            ok = verifica_pagina(v, T.tok_cantina(v["cantina"]), riga, sch)
            if not ok:
                stat[nome, "scartata dal controllo"] += 1
                continue
            corr, anno, litri = ok
            if not sch.voti:
                stat[nome, "senza voti"] += 1
                continue
            stat[nome, "con voti"] += 1
            visti = set()
            voti = []
            for crit, voto, scala in sch.voti:       # un solo voto per critico per scheda: vale il primo elencato
                if crit in visti:
                    continue
                visti.add(crit)
                voti.append((crit, voto, scala))
            # "Vinous" senza nome uguale a un "Vinous (Nome)" con lo stesso voto e' lo stesso giudizio
            voti = [t for t in voti if not (t[0] == "Vinous" and any(
                u[0].startswith("Vinous (") and u[1] == t[1] for u in voti))]
            for crit, voto, scala in voti:
                uscita.append({"id": riga["id"], "fonte": NOMI_FONTE[nome], "url": riga["url"], "critico": crit,
                               "voto": voto, "scala": scala, "annata_fonte": anno, "litri_fonte": litri,
                               "corrispondenza": corr, "data_raccolta": DATA_RACCOLTA})
    uscita.sort(key=lambda r: (int(r["id"]), r["fonte"], r["critico"]))
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, CAMPI)
        w.writeheader()
        w.writerows(uscita)
    for k, n in sorted(stat.items()):
        print(k[0], k[1], n)
    print(len(uscita), "righe in", USCITA.name)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sitemap":
        scarica_sitemap()
    elif cmd == "bbr_sitemap":
        bbr_sitemap()
    elif cmd == "abbina":
        abbina()
    elif cmd == "estrai":
        estrai()
    elif cmd == "scarica" and len(sys.argv) > 2:
        scarica_schede(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)
    else:
        print(__doc__)
