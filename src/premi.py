"""Premi e classifiche pubbliche: abbina i vini della carta Peck agli elenchi aperti delle guide.

    python -I src/premi.py scarica [gambero|bibenda|doctorwine|decanter]  # pagine grezze in data/raw/premi/<fonte>/ (salta quelle gia' presenti)
    python -I src/premi.py abbina              # legge le pagine scaricate e scrive data/premi_vini.csv e data/premi_fonti.csv
    python -I src/premi.py verifica [N]        # N abbinamenti a caso da controllare a mano

James Suckling Top 100: l'elenco e' disegnato dal JavaScript, quindi le posizioni sono state raccolte con un browser vero
(solo posizione + cantina/vino/annata, nessun punteggio) in data/raw/premi/suckling/<ambito>_<anno>.txt.

Regole di scarico (le stesse del resto del progetto):
  - prima di ogni sito si legge il robots.txt; si rispettano anche le sezioni dedicate agli agenti AI
    (ClaudeBot, anthropic-ai, Claude-Web, Claude-User, Anthropic-Client...): se una vieta il percorso, non si scarica;
  - se il sito risponde con una sfida anti-bot (Cloudflare "Just a moment", captcha, 403) la pagina e' "bloccata":
    non si insiste, non si aggira, si annota nell'elenco degli esiti;
  - pausa di 2 secondi fra due richieste allo stesso sito, User-Agent dichiarato, nessun login, nessun paywall.

Si prendono solo i fatti dell'elenco (nome del vino, cantina, annata, premio): niente testi, niente tasting note.
L'abbinamento e' rigido come in voti_aperti.py: cantina + nome del vino + annata (vedi sotto).
"""
import csv
import html
import random
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tannico as T  # noqa: E402  (stessa normalizzazione dell'abbinamento Tannico e dei voti aperti)
import voti_aperti as VA  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
RAW = RADICE / "data" / "raw" / "premi"
VINI = RADICE / "data" / "vini.csv"
GREZZI = RAW / "premi_grezzi.csv"
USCITA = RADICE / "data" / "premi_vini.csv"
USCITA_FONTI = RADICE / "data" / "premi_fonti.csv"
DATA_RACCOLTA = "2026-10-25"

UA = "Mozilla/5.0 (compatible; peck-tracker research; non-commercial)"
PAUSA = 2.0
# nomi con cui un robots.txt puo' parlare di un agente AI: se uno di questi e' escluso dal percorso, non si scarica
AGENTI_AI = ["peck-tracker", "ClaudeBot", "Claude-Web", "Claude-User", "Claude-SearchBot", "anthropic-ai",
             "Anthropic-Client"]
SFIDA = ("Just a moment", "captcha-delivery", "cf-chl", "Attention Required", "Access Denied", "Pardon Our Interruption",
         "Please enable JS and disable any ad blocker")

_robots = {}
_ultima = {}


# ---------------------------------------------------------------- scarico
def robots_per(host, schema="https"):
    """RobotFileParser del sito (salvato in data/raw/premi/_robots/<host>.txt)."""
    if host in _robots:
        return _robots[host]
    d = RAW / "_robots"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{host}.txt"
    if not f.exists():
        try:
            rich = urllib.request.Request(f"{schema}://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(rich, timeout=30) as r:
                f.write_bytes(r.read())
        except Exception as e:
            f.write_text(f"# non scaricabile: {e}\n", encoding="utf-8")
    testo = f.read_text(encoding="utf-8", errors="replace")
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(testo.splitlines())
    _robots[host] = rp
    return rp


def permesso(url):
    """True se nessun agente AI noto (e il nostro) e' escluso dal percorso, e nemmeno '*'."""
    u = urlparse(url)
    rp = robots_per(u.netloc)
    return all(rp.can_fetch(a, url) for a in AGENTI_AI + ["*"])


def scarica_pagina(url, dest, forza=False):
    """-> 'ok' | 'gia' | '404' | 'bloccata' | 'vietata' | 'errore'. Pausa di PAUSA secondi per sito."""
    if dest.exists() and not forza:
        return "gia"
    if not permesso(url):
        return "vietata"
    host = urlparse(url).netloc
    attesa = PAUSA - (time.time() - _ultima.get(host, 0))
    if attesa > 0:
        time.sleep(attesa)
    rich = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "it,en;q=0.8"})
    try:
        with urllib.request.urlopen(rich, timeout=60) as r:
            corpo = r.read()
        stato = 200
    except urllib.error.HTTPError as e:
        stato, corpo = e.code, e.read()
    except Exception as e:
        print("  errore", url, e, file=sys.stderr)
        _ultima[host] = time.time()
        return "errore"
    _ultima[host] = time.time()
    testo = corpo[:20000].decode("utf-8", errors="replace")
    if stato in (403, 429, 503) or (any(s in testo for s in SFIDA) and len(corpo) < 20000):
        return "bloccata"
    if stato == 404:
        return "404"
    if stato != 200:
        return "errore"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(corpo)
    return "ok"


def nome_file(url):
    u = urlparse(url)
    return re.sub(r"[^a-z0-9]+", "_", (u.path + ("?" + u.query if u.query else "")).lower()).strip("_")[:150] + ".html"


def registra_esito(cartella, url, esito):
    f = cartella / "_esiti.csv"
    nuovo = not f.exists()
    with open(f, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if nuovo:
            w.writerow(["url", "esito", "data"])
        w.writerow([url, esito, DATA_RACCOLTA])


def esiti_noti(cartella):
    f = cartella / "_esiti.csv"
    if not f.exists():
        return {}
    with open(f, encoding="utf-8", newline="") as fh:
        return {r["url"]: r["esito"] for r in csv.DictReader(fh)}


def scarica_elenco(cartella, urls, max_bloccate_di_fila=10):
    """Scarica gli url (una volta sola ciascuno: i 404 e le pagine bloccate non si riprovano)."""
    cartella.mkdir(parents=True, exist_ok=True)
    noti = esiti_noti(cartella)
    di_fila = 0
    for url in urls:
        dest = cartella / nome_file(url)
        if dest.exists() or url in noti:
            continue
        esito = scarica_pagina(url, dest)
        print(f"  {esito:9} {url}", flush=True)
        registra_esito(cartella, url, esito)
        di_fila = di_fila + 1 if esito == "bloccata" else 0
        if di_fila >= max_bloccate_di_fila:
            print("  troppe sfide anti-bot di fila: mi fermo su questo sito (non si aggira)")
            break


def testo_righe(corpo):
    """HTML -> righe di testo pulite."""
    corpo = re.sub(r"<script.*?</script>|<style.*?</style>", "", corpo, flags=re.S)
    corpo = html.unescape(re.sub(r"<[^>]+>", "\n", corpo))
    return [re.sub(r"\s+", " ", r).strip() for r in corpo.split("\n") if r.strip()]


def leggi_html(f):
    return Path(f).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- Gambero Rosso: Tre Bicchieri
GR_DIR = RAW / "gambero_rosso"
GR_BASE = "https://www.gamberorosso.it"
GR_REGIONI = [("toscana", "della"), ("piemonte", "del"), ("lombardia", "della"), ("trentino", "del"),
              ("alto-adige", "dell"), ("veneto", "del"), ("friuli-venezia-giulia", "del"),
              ("sicilia", "della"), ("abruzzo", "dell"), ("umbria", "dell"), ("sardegna", "della"),
              ("puglia", "della"), ("campania", "della"), ("liguria", "della"), ("marche", "delle"),
              ("emilia-romagna", "dell"), ("valle-daosta", "della"), ("lazio", "del"), ("calabria", "della"),
              ("basilicata", "della"), ("molise", "del")]


def gr_candidati():
    """Indirizzi possibili delle pagine regionali (se non esistono rispondono 404: costo 1 richiesta)."""
    out = []
    extra = GR_DIR / "_urls_extra.txt"
    if extra.exists():
        out += [r.strip() for r in extra.read_text(encoding="utf-8").splitlines() if r.strip()]
    for r, art in GR_REGIONI:
        art_r = f"dell{r}" if art == "dell" else f"{art}-{r}"   # "dell'Umbria" -> dellumbria
        out.append(f"{GR_BASE}/notizie/vino/degustazioni/tre-bicchieri-2027-migliori-vini-{r}/")
        out.append(f"{GR_BASE}/notizie/vino/degustazioni/tre-bicchieri-2026-migliori-vini-{r}/")
        out.append(f"{GR_BASE}/vino/tre-bicchieri-2025-migliori-vini-{r}/")
        out.append(f"{GR_BASE}/vino/tre-bicchieri-2025-vini-{r}/")
        out.append(f"{GR_BASE}/notizie/notizie-vino/tre-bicchieri-2024-i-migliori-vini-{art_r}-premiati-da-gambero-rosso/")
        out.append(f"{GR_BASE}/notizie/vino/anteprima-tre-bicchieri-2023-i-migliori-vini-{art_r}/")
        out.append(f"{GR_BASE}/notizie/vino/anteprima-tre-bicchieri-2022-i-migliori-vini-{art_r}/")
    return list(dict.fromkeys(out))


def gr_scarica():
    scarica_elenco(GR_DIR, gr_candidati())
    # link a pagine di elenchi trovati dentro le pagine scaricate (1 livello)
    trovati = []
    for f in sorted(GR_DIR.glob("*.html")):
        for m in re.findall(r'href="(https://(?:www\.)?gamberorosso\.it/[^"#?]*)"', leggi_html(f)):
            if re.search(r"tre-bicchieri-20(2[2-7])|migliori-vini-[a-z-]+-202[5-7]|anteprima-tre-bicchieri", m) \
                    and "/feed" not in m and "/argomenti/" not in m:
                trovati.append(m if m.endswith("/") or "." in m.rsplit("/", 1)[-1] else m + "/")
    scarica_elenco(GR_DIR, list(dict.fromkeys(trovati)))


def anno_di(s):
    m = re.search(r"\b((?:19|20)\d\d)\b\s*$", s)
    return m.group(1) if m else ""


def gr_edizione(url, righe):
    """Anno della guida dall'indirizzo (tre-bicchieri-2027..., migliori-vini-lombardia-2027)."""
    m = re.findall(r"20[2-3]\d", urlparse(url).path)
    return m[0] if m else ""


def gr_leggi_pagina(righe):
    """Righe di testo di una pagina Gambero Rosso -> [(vino, cantina, annata)].
    L'elenco e' una sequenza alternata «Denominazione e nome del vino 2022» / «Cantina»; i vini senza annata
    (spumanti non millesimati) non hanno l'anno. Se manca la riga della cantina (due righe con anno di fila)
    la voce senza cantina si scarta: non si abbina a occhio."""
    # inizio: dopo la frase «Ecco i vini che hanno ottenuto il massimo riconoscimento...» o «I vini premiati»
    ini = None
    for i, r in enumerate(righe):
        if re.match(r"(Ecco i vini|I vini premiati|Ecco i|Tre Bicchieri 20\d\d (del|dei|della|dell|delle|di))", r):
            ini = i
            # salta le righe di presentazione che terminano con un punto
            while ini + 1 < len(righe) and (righe[ini + 1].endswith(".") or righe[ini + 1].startswith("Vini d")
                                              or re.match(r"(Ecco i|I vini premiati|Tre Bicchieri 20)", righe[ini + 1])):
                ini += 1
            ini += 1
            break
    if ini is None:
        return []
    fine = len(righe)
    for i in range(ini, len(righe)):
        if righe[i] in (">",) or righe[i].startswith(("Scopri i vini", "TI POTREBBE", "Partecipa alla", "> Partecipa",
                                                      "Al Confine")):
            fine = i
            break
    seg = righe[ini:fine]
    out = []
    k = 0
    while k < len(seg):
        r = seg[k]
        if re.search(r"\b(19|20)\d\d$", r):
            # titolo con anno; la riga dopo e' la cantina se non finisce con un anno
            if k + 1 < len(seg) and not re.search(r"\b(19|20)\d\d$", seg[k + 1]):
                out.append((re.sub(r"\s+(19|20)\d\d$", "", r), seg[k + 1], anno_di(r)))
                k += 2
            else:
                k += 1          # cantina mancante: scartato
        else:
            # titolo senza anno (non millesimato) seguito dalla cantina
            if k + 1 < len(seg) and not re.search(r"\b(19|20)\d\d$", seg[k + 1]):
                out.append((r, seg[k + 1], "NV"))
                k += 2
            else:
                k += 1
    return out


def gr_leggi():
    righe_out = []
    esiti = esiti_noti(GR_DIR)
    inv = {nome_file(u): u for u in esiti}
    for f in sorted(GR_DIR.glob("*.html")):
        url = inv.get(f.name) or ""
        if not url:
            # pagina scaricata a mano: l'indirizzo e' nel nome del file (vedi _urls_extra.txt)
            for u in (GR_DIR / "_urls_extra.txt").read_text(encoding="utf-8").splitlines() if (GR_DIR / "_urls_extra.txt").exists() else []:
                if nome_file(u.strip()) == f.name:
                    url = u.strip()
        righe = testo_righe(leggi_html(f))
        ed = gr_edizione(url, righe)
        voci = gr_leggi_pagina(righe)
        for vino, cantina, anno in voci:
            righe_out.append({"fonte": "Gambero Rosso", "premio": "Tre Bicchieri", "guida": "Gambero Rosso Vini d'Italia",
                              "edizione": ed, "vino": vino, "cantina": cantina, "annata": anno, "posizione": "",
                              "url": url, "paese": "IT", "nota": ""})
    return righe_out


# ---------------------------------------------------------------- James Suckling: Top 100 (elenchi pubblici)
SK_DIR = RAW / "suckling"
SK_FILE = {"italia": ("Top 100 Italia", "IT"), "francia": ("Top 100 Francia", "FR"), "mondo": ("Top 100 Mondo", "")}


def sk_leggi():
    """File raccolti a mano dal browser (data/raw/premi/suckling/<ambito>_<anno>.txt): prima riga = indirizzo,
    poi «posizione|CANTINA DENOMINAZIONE VINO ANNATA». Non c'e' la cantina separata: l'abbinamento usa la cantina di Peck."""
    out = []
    for f in sorted(SK_DIR.glob("*_20??.txt")):
        ambito, anno = f.stem.split("_")
        premio, paese = SK_FILE[ambito]
        righe = f.read_text(encoding="utf-8").splitlines()
        url = righe[0].strip()
        for r in righe[1:]:
            if not r.strip() or r.startswith("#"):
                continue
            pos, testo = r.split("|", 1)
            testo = testo.strip()
            a = anno_di(testo)
            out.append({"fonte": "James Suckling", "premio": premio, "guida": "James Suckling Top 100",
                        "edizione": anno, "vino": re.sub(r"\s+(19|20)\d\d$", "", testo), "cantina": "",
                        "annata": a or "NV", "posizione": pos, "url": url, "paese": paese, "nota": ""})
    return out


# ---------------------------------------------------------------- Decanter World Wine Awards: Best in Show
DC_DIR = RAW / "decanter"
DC_PAGINE = {   # edizione: (file, indirizzo)
    "2025": ("dwwa2025_best_in_show.html", "https://www.decanter.com/wine-news/decanter-world-wine-awards-2025-best-in-show-top-50-wines-559209"),
    "2024": ("dwwa2024_best_in_show.html", "https://www.decanter.com/decanter-world-wine-awards/decanter-world-wine-awards-2024-best-in-show-top-50-532258/"),
    "2023": ("dwwa2023_best_in_show.html", "https://www.decanter.com/wine-news/the-top-50-wines-of-2023-decanter-world-wine-awards-best-of-the-best-505347/"),
}
DC_PAESI = {"Argentina": "AR", "Australia": "AU", "Austria": "AT", "Chile": "CL", "China": "CN", "France": "FR",
            "Germany": "DE", "Greece": "GR", "Hungary": "HU", "Italy": "IT", "Japan": "JP", "New Zealand": "NZ",
            "Portugal": "PT", "Serbia": "RS", "Slovenia": "SI", "South Africa": "ZA", "Spain": "ES",
            "United Kingdom": "GB", "United States": "US", "USA": "US", "Switzerland": "CH", "Lebanon": "LB",
            "Israel": "IL", "Canada": "CA", "Uruguay": "UY", "Romania": "RO", "Georgia": "GE", "Bulgaria": "BG"}


def dc_scarica():
    DC_DIR.mkdir(parents=True, exist_ok=True)
    for ed, (nome, url) in DC_PAGINE.items():
        esito = scarica_pagina(url, DC_DIR / nome)
        print(f"  {esito:9} {url}")


def dc_leggi():
    out = []
    for ed, (nome, url) in DC_PAGINE.items():
        f = DC_DIR / nome
        if not f.exists():
            continue
        righe = testo_righe(leggi_html(f))
        # la lista comincia dopo il testo: dal secondo gruppo di paesi (il primo e' il menu del sito)
        ini = None
        for i, r in enumerate(righe):
            if i > 120 and r in DC_PAESI:
                ini = i
                break
        if ini is None:
            continue
        paese, prod = "", None
        for r in righe[ini:]:
            if r.startswith(("Related", "Topics", "Search all", "Explore More", "Latest")):
                break
            if r in DC_PAESI:
                paese, prod = DC_PAESI[r], None
                continue
            m = re.search(r"((?:19|20)\d\d|NV)$", r)
            if not m:
                prod = r.rstrip(", ").strip()
                continue
            anno = m.group(1)
            testo = re.sub(r"\s*((?:19|20)\d\d|NV)$", "", r).rstrip(", ")
            if prod is not None:
                cantina, vino = prod, testo.lstrip(", ")
                prod = None
            elif "," in testo:
                cantina, vino = [x.strip() for x in testo.split(",", 1)]
            else:
                continue
            out.append({"fonte": "Decanter", "premio": "Best in Show", "guida": "Decanter World Wine Awards",
                        "edizione": ed, "vino": vino, "cantina": cantina, "annata": anno, "posizione": "",
                        "url": url, "paese": paese, "nota": ""})
    return out


# ---------------------------------------------------------------- Bibenda: Cinque Grappoli (elenchi ufficiali sul sito)
BB_DIR = RAW / "bibenda"
BB_PAGINE = {"2027": 5777, "2026": 5707}     # news_bibenda_singola.php?id=...  («I migliori vini d'Italia di Bibenda»)
BB_URL = "https://www.bibenda.it/news_bibenda_singola.php?id={id}"


def bb_scarica():
    BB_DIR.mkdir(parents=True, exist_ok=True)
    for ed, id_ in BB_PAGINE.items():
        url = BB_URL.format(id=id_)
        esito = scarica_pagina(url, BB_DIR / f"n{id_}.html")
        print(f"  {esito:9} {url}")


def bb_leggi():
    out = []
    for ed, id_ in BB_PAGINE.items():
        f = BB_DIR / f"n{id_}.html"
        if not f.exists():
            continue
        righe = testo_righe(leggi_html(f))
        ini = [i for i, r in enumerate(righe) if r.startswith("CINQUE GRAPPOLI BIBENDA")]
        if not ini:
            continue
        fine = next((i for i, r in enumerate(righe) if i > ini[0] and (r.startswith(("TUTTE LE NOTIZIE", "Ultimi articoli"))
                                                                  or "RIPRODUZIONE" in r)), len(righe))
        seg = righe[ini[0] + 1:fine]

        def maiuscola(r):
            return r == r.upper() and bool(re.search(r"[A-Z]", r)) and not re.search(r"(19|20)\d\d$", r)
        cantina = None
        for k, r in enumerate(seg):
            if maiuscola(r):
                if k + 1 < len(seg) and maiuscola(seg[k + 1]):
                    cantina = None          # intestazione di regione
                else:
                    cantina = r
                continue
            if cantina is None:
                continue
            a = anno_di(r)
            out.append({"fonte": "Bibenda", "premio": "5 Grappoli", "guida": "Bibenda (Fondazione Italiana Sommelier)",
                        "edizione": ed, "vino": re.sub(r"\s+(19|20)\d\d$", "", r), "cantina": cantina,
                        "annata": a or "NV", "posizione": "", "url": BB_URL.format(id=id_), "paese": "IT", "nota": ""})
    return out


# ---------------------------------------------------------------- DoctorWine: Faccini (vini da 95/100 in su, elenchi aperti)
DW_DIR = RAW / "doctorwine"
DW_BASE = "https://www.doctorwine.wine/pot-pourri/guide-doctorwine/"
DW_GRUPPI = ["alto-adige-e-trentino", "campania-lazio-e-umbria", "lombardia-emilia-e-romagna",
             "marche-abruzzo-e-molise", "piemonte-val-daosta-e-liguria", "puglia-basilicata-e-calabria",
             "sicilia-e-sardegna", "toscana", "veneto-e-friuli-venezia-giulia"]
DW_REGIONI = {"Piemonte", "Toscana", "Sicilia", "Veneto", "Lombardia", "Trentino", "Alto Adige", "Friuli Venezia Giulia",
              "Campania", "Puglia", "Sardegna", "Umbria", "Marche", "Lazio", "Abruzzo", "Liguria", "Emilia", "Romagna",
              "Calabria", "Basilicata", "Molise", "Valle d'Aosta", "Val d'Aosta", "Trentino-Alto Adige"}


DW_NOTE = {"Faccino": "livello 95-97/100", "Doppio faccino": "livello 98/100", "Triplo faccino": "livello 99-100/100"}


def dw_candidati():
    out = []
    for y in (2027, 2026, 2025, 2024):
        for g in DW_GRUPPI:
            out.append(f"{DW_BASE}faccini-{y}-{g}/")
            out.append(f"{DW_BASE}faccini-doctorwine-{y}-{g}/")
        out.append(f"{DW_BASE}doppi-e-tripli-faccini-{y}/")
        out.append(f"{DW_BASE}doppi-e-tripli-faccini-doctorwine-{y}/")
    return out


def dw_scarica():
    scarica_elenco(DW_DIR, dw_candidati())


def dw_cantina_dopo_anno(testo):
    """«Barolo Riserva Monfortino 2020 Giacomo Conterno, Piemonte» -> (vino, cantina, annata)."""
    for m in re.finditer(r"\b((?:19|20)\d\d)\b", testo):
        resto = testo[m.end():].strip()
        if resto and not re.search(r"\d", resto):
            cant = re.sub(r",\s*([^,]+)$", lambda x: "" if x.group(1).strip() in DW_REGIONI else x.group(0), resto)
            return testo[:m.start()].strip(), cant.strip(" ,"), m.group(1)
    return None


def dw_leggi():
    out = []
    esiti = esiti_noti(DW_DIR)
    inv = {nome_file(u): u for u in esiti}
    for f in sorted(DW_DIR.glob("*.html")):
        url = inv.get(f.name, "")
        ed = re.search(r"(20[2-3]\d)", url)
        if not ed or "faccini" not in url:
            continue
        righe = testo_righe(leggi_html(f))
        punti = None
        for k, r in enumerate(righe):
            m = re.match(r"^(9[5-9]|100)/100$", r)
            if m:
                punti = int(m.group(1))
                continue
            m = re.match(r"^(9[5-9]|100)\s+[–-]\s+(.+)$", r)    # edizione 2027: «97 – Vino 2023» e la cantina a capo
            if m and k + 1 < len(righe):
                mm = re.match(r"^(.+?)\s+((?:19|20)\d\d)$", m.group(2))
                cant = righe[k + 1]
                if mm and not re.match(r"^(9[5-9]|100)\b", cant) and len(cant) < 90 and not cant.endswith(":"):
                    pt = int(m.group(1))
                    premio = "Triplo faccino" if pt >= 99 else "Doppio faccino" if pt == 98 else "Faccino"
                    out.append({"fonte": "DoctorWine", "premio": premio,
                                "guida": "DoctorWine Guida Essenziale ai Vini d'Italia", "edizione": ed.group(1),
                                "vino": mm.group(1), "cantina": cant, "annata": mm.group(2), "posizione": "",
                                "url": url, "paese": "IT", "nota": DW_NOTE[premio]})
                    continue
            m = re.match(r"^(9[5-9]|100)\s+(?:[–-]\s+)?(.+)$", r)
            if m:
                voce, pt = m.group(2), int(m.group(1))
            elif punti and re.search(r"\b(19|20)\d\d\b.*[A-Za-z]", r) and len(r) < 160:
                voce, pt = r, punti
            else:
                continue
            x = dw_cantina_dopo_anno(voce)
            if not x:
                continue
            vino, cantina, anno = x
            premio = "Triplo faccino" if pt >= 99 else "Doppio faccino" if pt == 98 else "Faccino"
            out.append({"fonte": "DoctorWine", "premio": premio, "guida": "DoctorWine Guida Essenziale ai Vini d'Italia",
                        "edizione": ed.group(1), "vino": vino, "cantina": cantina, "annata": anno, "posizione": "",
                        "url": url, "paese": "IT", "nota": DW_NOTE[premio]})
    return out


# ---------------------------------------------------------------- normalizzazione e abbinamento rigido
ABBREVIAZIONI = [(r"\bM\.\s?Cl\.?", "metodo classico"), (r"\bV\.\s?V\.?", "vecchie vigne"), (r"\bCl\.", "classico"),
                 (r"\bRis\.", "riserva"), (r"\bSup\.", "superiore"), (r"\bVign?\.", "vigna"),
                 (r"\bM\.to\b", "monferrato"), (r"\bA\.\s?A\.", "alto adige"), (r"\bOP\b", "oltrepo pavese"),
                 (r"\bSt\.-?", "saint "), (r"\bSte\.", "sainte"), (r"\bGS\b", "gran selezione")]
# classificazioni bordolesi dette per esteso da una parte sola: non cambiano il vino
CLASSIFICAZIONI = re.compile(r"\b(?:(?:premier|1er|2eme|deuxieme|3eme|troisieme|4eme|quatrieme|5eme|cinquieme)\s+)?"
                             r"(?:grand\s+)?cru\s+classe(?:\s+de\s+\w+)?\b")
# parole che, presenti da una parte sola, non cambiano il vino: comuni/denominazioni bordolesi e dintorni
IGNORABILI = set("""margaux pomerol julien estephe medoc bordeaux sauternes barsac pessac leognan emilion pauillac
saint st ste classico superiore toscana sudtirol sudtirolo igt doc docg""".split()) - {"classico", "superiore"}
# lettere sole che sono solo elisioni o iniziali di nome (d'Estournel, M. Chapoutier): le altre (Y de Yquem, G d'Estournel) contano
LETTERE_MUTE = set("a d e i l m o s u st".split())
SINONIMI = {"vigneto": "vigna", "dosage": "dosaggio", "cuvee": "cuvee", "ermitage": "hermitage", "sant": "sant"}


def prep(s):
    for rx, sost in ABBREVIAZIONI:
        s = re.sub(rx, sost, s, flags=re.I)
    s = T.norm(s)
    s = CLASSIFICAZIONI.sub(" ", s)
    toks = [SINONIMI.get(w, w) for w in s.split()]
    return " ".join(toks)


def toks(s):
    return set(T.token_vino(prep(s)))


def nucleo(nome, togli):
    """(nucleo, ignorabili) come VA.nucleo_stretto, con le parole ignorabili in piu'."""
    t = {w for w in toks(nome) - togli if w not in T.PAROLE_VUOTE and w not in LETTERE_MUTE}
    ign = {w for w in t if w in VA.SICURE or w in T.REGIONI or w in T.CANTINA_GENERICA or w in IGNORABILI}
    return t - ign, ign


def alt_cantina(c):
    """Alternative di token distintivi della cantina (parentesi = alternative)."""
    alt = [re.sub(r"\([^)]*\)", " ", c)] + re.findall(r"\(([^)]*)\)", c)
    out = []
    for a in alt:
        t = {w for w in toks(a) if w not in T.CANTINA_GENERICA} or toks(a)
        if t:
            out.append(t)
    return out


def parti_cantina_premio(c):
    """Cantina del premio, anche con piu' nomi («Poggio Landi - Podere Brizio», «Giacosa»): lista di insiemi di token."""
    pezzi = re.split(r"\s[-–—]\s|\s?/\s?|\s&\s", c)
    out = []
    for p in pezzi:
        t = {w for w in toks(p) if w not in T.CANTINA_GENERICA} or toks(p)
        if t:
            out.append(t)
    return out


def distanza(a, b):
    if a == b:
        return 0
    if a.isdigit() and b.isdigit():
        return abs(int(a) - int(b))
    return 99


def carica_vini():
    with open(VINI, encoding="utf-8-sig", newline="") as f:
        righe = list(csv.DictReader(f))
    vini, prezzi = {}, defaultdict(list)
    for r in righe:
        if r["variante"] == "calice":
            continue
        vini.setdefault(r["id"], r)
        try:
            prezzi[r["id"]].append(float(r["prezzo_euro"]))
        except ValueError:
            pass
    for r in righe:                      # vini presenti solo al calice
        vini.setdefault(r["id"], r)
    return list(vini.values()), {k: min(p) for k, p in prezzi.items() if p}


MAX_DISTANZA = 2


def prepara_premi(premi):
    for p in premi:
        p["_tv"] = toks(p["vino"]) if not p["cantina"] else None
        p["_parti"] = parti_cantina_premio(p["cantina"]) if p["cantina"] else []
        p["_indice"] = set()
        if p["cantina"]:
            for t in p["_parti"]:
                p["_indice"] |= t
        else:
            p["_indice"] = toks(p["vino"])
    idx = defaultdict(list)
    for p in premi:
        for w in p["_indice"]:
            idx[w].append(p)
    return idx


def stesso_vino_premio(v, tc_alt, p):
    """Cantina + nome del vino devono coincidere (parola per parola, salvo denominazioni presenti da una parte sola)."""
    tn = toks(v["nome"])
    if p["cantina"]:
        # cantina del premio (spesso abbreviata) contenuta nella cantina o nel nome del vino Peck
        ok = False
        tv = toks(p["vino"])
        for ct in p["_parti"]:
            if any(ct <= a for a in tc_alt):
                ok, ct_ok = True, ct
                break
            # cantina abbreviata che sta solo nel nome del vino Peck: non deve essere una parola del vino
            # premiato (Marchesi di Barolo / «Barolo Cannubi» di un'altra cantina)
            if ct <= tn and not (ct & tv):
                ok, ct_ok = True, ct
                break
        if not ok:
            return False
        togli = set().union(*tc_alt) | ct_ok
        n_p, i_p = nucleo(v["nome"], togli)
        n_f, i_f = nucleo(p["vino"], togli)
    else:
        # nessuna cantina separata (Suckling): una cantina Peck deve stare nel testo del premio
        tt = p["_tv"]
        buone = [a for a in tc_alt if a <= tt]
        if not buone:
            return False
        togli = set().union(*tc_alt)
        n_p, i_p = nucleo(v["nome"], togli)
        n_f, i_f = nucleo(p["vino"], togli)
    if n_p != n_f:
        return False
    return i_p <= i_f or i_f <= i_p


def colore_ok(v, p):
    """Bianco/rosso: «Blanc/Bianco» nel premio contro un vino Peck rosso (o il contrario) non si abbina."""
    testo = prep(p["vino"] + " " + p["cantina"])
    bianco_p = bool(re.search(r"\b(blanc|bianco|blancs|blanche)\b", testo))
    rosso_p = bool(re.search(r"\b(rouge|rosso|noir|noirs)\b", testo))
    t = v["tipo"]
    if bianco_p and t in ("rosso", "rosato"):
        return False
    if rosso_p and t in ("bianco", "spumante", "dolce"):
        return False
    return True


def abbina_premi(vini, premi):
    idx = prepara_premi(premi)
    out = []
    for v in vini:
        tc_alt = alt_cantina(v["cantina"])
        if not tc_alt:
            continue
        cand = {}
        for a in tc_alt:
            for w in a:
                for p in idx.get(w, ()):
                    cand[id(p)] = p
        for w in toks(v["nome"]):                       # cantine abbreviate: anche le parole del nome
            for p in idx.get(w, ()):
                if p["cantina"]:
                    cand[id(p)] = p
        a_peck = v["annata"] or "NV"
        for p in cand.values():
            if p["paese"] and v["codice_paese"] and p["paese"] != v["codice_paese"]:
                continue
            if not stesso_vino_premio(v, tc_alt, p) or not colore_ok(v, p):
                continue
            d = distanza(a_peck, p["annata"])
            if d > MAX_DISTANZA:
                continue
            out.append({"id": v["id"], "premio": p["premio"], "guida": p["guida"], "edizione": p["edizione"],
                        "annata_premiata": p["annata"], "posizione": p["posizione"], "url_fonte": p["url"],
                        "corrispondenza": "esatta" if d == 0 else "annata diversa ±2",
                        "nota": (p["nota"] + "; " if p["nota"] else "") +
                                (f"premiata l'annata {p['annata']}, la carta Peck ha {a_peck}" if d else ""),
                        "_peck": f"{v['cantina']} | {v['nome']} | {v['annata']}",
                        "_premio": f"{p['cantina']} | {p['vino']} | {p['annata']}", "_fonte": p["fonte"]})
    # doppioni (stesso vino, stesso premio/edizione/annata/posizione)
    visti, uniche = set(), []
    for r in out:
        k = (r["id"], r["premio"], r["edizione"], r["annata_premiata"], r["posizione"])
        if k not in visti:
            visti.add(k)
            uniche.append(r)
    return uniche


CAMPI = ["id", "premio", "guida", "edizione", "annata_premiata", "posizione", "url_fonte", "corrispondenza", "nota"]


def tutte_le_voci():
    premi = []
    premi += gr_leggi()
    premi += sk_leggi()
    premi += dc_leggi()
    premi += bb_leggi()
    premi += dw_leggi()
    return premi


def abbina():
    vini, prezzo = carica_vini()
    premi = tutte_le_voci()
    print(len(vini), "vini Peck;", len(premi), "voci di premio")
    righe = abbina_premi(vini, premi)
    righe.sort(key=lambda r: (int(r["id"]), r["guida"], r["premio"], -int(r["edizione"] or 0)))
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, CAMPI, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)
    (RAW / "_premi_controllo.tsv").write_text(
        "\n".join(f"{r['id']}\t{r['_fonte']}\t{r['premio']}\t{r['corrispondenza']}\t{r['_peck']}\t{r['_premio']}"
                  for r in righe), encoding="utf-8")
    scrivi_fonti(premi, righe)
    ids = {r["id"] for r in righe}
    sotto = [i for i in ids if prezzo.get(i, 9999) < 200]
    print(f"righe {len(righe)}; vini con almeno un premio {len(ids)}; sotto 200 euro {len(sotto)} "
          f"(su {sum(1 for p in prezzo.values() if p < 200)} vini sotto 200)")
    print(Counter((r["guida"], r["premio"], r["corrispondenza"]) for r in righe).most_common())


FONTI = [   # (fonte, cosa e', url, termini, stato)
    ("Gambero Rosso", "Tre Bicchieri, guida Vini d'Italia: pagine regionali con i vini premiati (denominazione, nome, annata, cantina)",
     "https://www.gamberorosso.it/notizie/vino/degustazioni/",
     "robots.txt: nessun divieto per gli agenti AI (solo * e Googlebot); testi (c) Gambero Rosso: si tengono solo i fatti dell'elenco",
     "gambero"),
    ("Bibenda", "5 Grappoli, guida Bibenda (Fondazione Italiana Sommelier): elenchi ufficiali «I migliori vini d'Italia», per regione e cantina",
     "https://www.bibenda.it/news_bibenda_singola.php?id=5777",
     "robots.txt vuoto (tutto consentito); testi (c) FIS: si tengono solo vino, cantina, annata. Edizione 2025: solo PDF a due colonne sfalsate, non usato; la «guida web» richiede login, non usata",
     "bibenda"),
    ("DoctorWine", "Faccini (95-97/100), doppi (98) e tripli faccini (99-100), Guida Essenziale ai Vini d'Italia: elenchi aperti per gruppi di regioni",
     "https://www.doctorwine.wine/category/pot-pourri/guide-doctorwine/",
     "robots.txt: nessun divieto per gli agenti AI; si tiene solo il livello del faccino (non il punteggio esatto) e non si copiano i testi",
     "doctorwine"),
    ("James Suckling", "Top 100 Wines of Italy / France / World: posizione in classifica (elenco pubblico, senza punteggi ne' note)",
     "https://www.jamessuckling.com/top-100",
     "robots.txt: tutto consentito; termini del sito: uso personale e non commerciale. L'elenco e' disegnato dal JavaScript: letto da un browser vero (nessun login), solo posizione, cantina+vino+annata; punteggi e note a pagamento non copiati",
     "suckling"),
    ("Decanter", "Decanter World Wine Awards, Best in Show (Top 50 di ogni anno)",
     "https://www.decanter.com/wine-news/decanter-world-wine-awards-2025-best-in-show-top-50-wines-559209",
     "robots.txt: nessun divieto per ClaudeBot (vietati altri robot AI per nome); termini Future plc non letti per intero: solo fatti dell'elenco",
     "decanter"),
    ("Wine Spectator", "Top 100 annuale", "https://www.winespectator.com", "robots.txt vieta ClaudeBot, Anthropic-Client e quasi ogni robot AI: NON scaricato", None),
    ("Wine Enthusiast", "Top 100 annuale", "https://www.winemag.com", "protezione anti-bot (captcha DataDome): NON aggirata, nessun elenco scaricato (resta solo il dataset aperto gia' in voti_aperti.csv)", None),
    ("Slow Wine (Slow Food)", "Chiocciola / Vino Slow", "https://www.slowfood.it", "403 gia' su robots.txt (anti-bot): NON scaricato", None),
    ("Falstaff", "Falstaff Wine Guide Italia / Top", "https://www.falstaff.com", "403 con sfida anti-bot sulle pagine dei vini: NON aggirata", None),
    ("La Revue du vin de France", "Meilleurs vins / Top", "https://www.larvf.com", "sito non raggiungibile dal nostro user agent; robots.txt vieta /vins/: NON scaricato", None),
    ("Vitae (AIS)", "Quattro Viti, Gemme, Tastevin", "https://aisitalia.it", "robots.txt aperto ma l'elenco dei vini sta solo nella guida/app (codice AIS-Key): nessun elenco pubblico trovato", None),
    ("Veronelli", "Super Tre Stelle / Tre Stelle Oro", "https://www.ilveronelli.it", "nessun elenco aperto trovato sul sito (solo comunicati dei produttori)", None),
    ("Bettane+Desseauve (La Selection)", "Selezione 2026 per regione (Bon vin / Tres bon vin / Vin de reference)", "https://selectionbd.bettanedesseauve.com",
     "robots.txt assente (404); elenchi in PDF per regione di vini proposti dai produttori: non usati", None),
]


STATI_NON_USATE = {"Wine Spectator": "NON scaricata: il robots.txt vieta ClaudeBot e Anthropic-Client",
                   "Wine Enthusiast": "NON scaricata: protezione anti-bot (captcha), non aggirata",
                   "Slow Wine (Slow Food)": "NON scaricata: 403 anti-bot gia' sul robots.txt",
                   "Falstaff": "NON scaricata: 403 con sfida anti-bot, non aggirata",
                   "La Revue du vin de France": "NON scaricata: sito chiuso al nostro user agent",
                   "Vitae (AIS)": "nessun elenco pubblico dei vini (solo guida e app)",
                   "Veronelli": "nessun elenco pubblico trovato",
                   "Bettane+Desseauve (La Selection)": "non provata: elenchi a livelli (Bon vin / Tres bon vin / Vin de reference) in PDF per regione, pochi vini da collezione"}


def scrivi_fonti(premi, righe):
    pm = defaultdict(list)
    for p in premi:
        pm[p["fonte"]].append(p)
    mappa = {"gambero": "Gambero Rosso", "bibenda": "Bibenda", "doctorwine": "DoctorWine", "suckling": "James Suckling",
             "decanter": "Decanter"}
    per_fonte = defaultdict(list)
    for r in righe:
        per_fonte[r["_fonte"]].append(r)
    with open(USCITA_FONTI, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fonte", "cosa_e", "url", "termini_e_licenza", "stato", "anni_coperti", "voci_lette",
                    "righe_abbinate", "vini_con_premio"])
        for nome, cosa, url, termini, chiave in FONTI:
            voci = pm.get(mappa.get(chiave, nome), []) if chiave else []
            righe_f = per_fonte.get(mappa.get(chiave, nome), []) if chiave else []
            anni = sorted({p["edizione"] for p in voci if p["edizione"]})
            if chiave and voci:
                stato = "usata"
                if chiave == "gambero":
                    stato = "usata in parte (le altre pagine: sfida anti-bot Cloudflare, non aggirata)"
            elif chiave == "gambero":
                stato = "BLOCCATA (sfida anti-bot Cloudflare sulle pagine; nessun dato)"
            else:
                stato = STATI_NON_USATE.get(nome, "non usata")
            w.writerow([nome, cosa, url, termini, stato, " ".join(anni), len(voci), len(righe_f),
                        len({r["id"] for r in righe_f})])


def verifica(n=30):
    f = RAW / "_premi_controllo.tsv"
    righe = [r.split("\t") for r in f.read_text(encoding="utf-8").splitlines()]
    random.seed(5)
    for r in random.sample(righe, min(n, len(righe))):
        print(f"[{r[1][:6]}|{r[3]}] {r[2]}\n    PECK : {r[4]}\n    PREMIO: {r[5]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scarica":
        fonte = sys.argv[2] if len(sys.argv) > 2 else "tutte"
        if fonte in ("tutte", "gambero"):
            gr_scarica()
        if fonte in ("tutte", "decanter"):
            dc_scarica()
        if fonte in ("tutte", "bibenda"):
            bb_scarica()
        if fonte in ("tutte", "doctorwine"):
            dw_scarica()
    elif cmd == "abbina":
        abbina()
    elif cmd == "verifica":
        verifica(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    else:
        print(__doc__)
