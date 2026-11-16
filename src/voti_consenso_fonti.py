"""Nuove fonti di voti dei critici per i vini della carta Peck -> data/voti_extra.csv.

    python -I src/voti_consenso_fonti.py maroni_sitemap   # robots.txt + sitemap dei vini di Luca Maroni (lucamaroni.it)
    python -I src/voti_consenso_fonti.py maroni_abbina    # pre-abbinamento coi nomi negli indirizzi -> candidati.csv
    python -I src/voti_consenso_fonti.py maroni_scarica [N]  # scarica SOLO le schede candidate (pausa 2 s), tiene il punteggio
    python -I src/voti_consenso_fonti.py bd_sitemap       # robots.txt + sitemap dei vini di Bettane+Desseauve (mybettanedesseauve.fr)
    python -I src/voti_consenso_fonti.py bd_abbina        # pre-abbinamento coi nomi negli indirizzi -> candidati.csv
    python -I src/voti_consenso_fonti.py bd_scarica [N]   # scarica SOLO le schede candidate (pausa 3 s), tiene la nota su 20
    python -I src/voti_consenso_fonti.py vinf_sitemap     # robots.txt + sitemap dei prodotti di Vinfolio
    python -I src/voti_consenso_fonti.py vinf_abbina      # pre-abbinamento coi nomi negli indirizzi -> candidati.csv
    python -I src/voti_consenso_fonti.py vinf_scarica [N] # scarica SOLO le schede candidate (pausa 2 s), tiene critico, voto, data
    python -I src/voti_consenso_fonti.py ws_scarica       # Wine Spectator Top 100 2003-2020 (Zenodo 7930185, CC BY 4.0)
    python -I src/voti_consenso_fonti.py estrai           # legge tutto quello che c'e' su disco -> data/voti_extra.csv
    python -I src/voti_consenso_fonti.py verifica [N]     # N righe a caso da controllare a mano
    python -I src/voti_consenso_fonti.py riepilogo

Fonti USATE qui:
  - Bettane+Desseauve (mybettanedesseauve.fr, «Catalogue des vins notes»): 130.000 vini con la «NOTE DE L'EXPERT»
    su 20 (dalle annate recenti su 100), visibile senza abbonamento; la fonte principale per la Borgogna. Il robots.txt nomina ClaudeBot
    e lo ammette (Allow: /). Si tiene solo la nota (scala 20 o 100; il 20 nel consenso e' x5), mai commenti o note del domaine.
    Le condizioni del sito vietano la riproduzione dei contenuti: qui si tengono solo il numero e il link.
  - Vinfolio (vinfolio.com, commerciante americano di vini fini): la scheda di ogni annata porta nei suoi dati
    (__NEXT_DATA__) le recensioni dei critici con voto, scala e data (piu' una media del negozio). Il robots.txt
    nomina ClaudeBot e lo ammette (Allow: /), nessun Crawl-delay. Si tengono critico, voto, scala e data
    (mai i commenti); per ogni testata la recensione piu' recente.
  - Luca Maroni (lucamaroni.it): ogni scheda vino ha «Punteggio Dettagliato» (consistenza + equilibrio +
    integrita' = voto su 100). Il robots.txt di lucamaroni.it nomina ClaudeBot e lo ammette con Crawl-delay 2 s
    (rispettato anche qui); l'area riservata e' esclusa. Si tengono solo punteggio ed edizione dell'Annuario.
    ATTENZIONE: i punteggi Maroni sono tarati diversamente dagli altri critici (misurano la «piacevolezza»), e per
    questo nel consenso entrano ma sono segnalati.
  - Wine Spectator Top 100 2003-2020 (Zenodo «Database Wine and Scores», licenza CC BY 4.0, base dati di terzi):
    il sito di Wine Spectator vieta ClaudeBot nel suo robots.txt, qui NON si visita: si usa la copia con licenza
    aperta (solo i 100 vini di ogni anno). Si toglie con FONTI_DA_ESCLUDERE se non la si vuole.

Fonti ESAMINATE E NON USATE (motivo, e cosa si puo' fare) sono in JOURNAL.md e nel rapporto:
  Global Wine Score (dominio in vendita), CellarTracker (WAF anti-bot anche su robots.txt), Decanter/Vinous/Jancis/
  Wine Advocate/Burghound (a pagamento), Wine Spectator/Wine Enthusiast sito (robots/captcha), Hedonism (schede senza
  punteggi), siti dei produttori (nessun elenco di punteggi per annata), DoctorWine (solo 706 note, 28 vini).
  Justerini & Brooks e Farr Vintners (con punteggi dei critici per annata, robots.txt aperto) sono scaricati
  dall'altro filone di lavoro, `src/voti_enoteche.py` (secondo giro): finiscono in `data/voti_enoteche.csv`.

Regole comuni: robots.txt riletto e rispettato (anche le sezioni per ClaudeBot/anthropic-ai), niente accessi
con login, niente aggiramento di blocchi (403/429 persistenti = si ferma), grezzo in data/raw/voti/<fonte>/,
User-Agent che dice chi siamo, pausa fissa, solo nomi e numeri (mai i testi delle recensioni).
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
         "licenza_note", "voto_testo", "recensore", "nome_fonte", "data_raccolta", "data_recensione"]

LIC_MARONI = ("Dato fattuale (punteggio) letto dalla scheda pubblica di lucamaroni.it; nessun testo copiato; "
              "uso non commerciale; robots.txt consente ClaudeBot con Crawl-delay 2 s; tarato diversamente dagli altri critici")
LIC_VINF = ("Dato fattuale (nome del critico + punteggio) letto dalla scheda pubblica di vinfolio.com; "
            "nessun testo copiato; uso non commerciale; robots.txt ammette ClaudeBot (Allow: /)")
LIC_BD = ("Dato fattuale (nota dell'esperto su 20) letto dalla scheda pubblica di mybettanedesseauve.fr; nessun testo copiato; "
          "uso non commerciale; robots.txt ammette ClaudeBot (Allow: /); le condizioni del sito vietano la riproduzione dei contenuti")
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


# ---------------------------------------------------------------- abbinamento da indirizzi
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


# ---------------------------------------------------------------- Luca Maroni (lucamaroni.it)
MARONI = "lucamaroni"
MARONI_HOST = "www.lucamaroni.it"
PAUSA_MARONI = 2.0
MARONI_NOME = "Luca Maroni"
RX_MARONI_DETT = re.compile(r"Punteggio Dettagliato\s+(\d+)\s+Consistenza\s*\+\s*(\d+)\s+Equilibrio\s*\+\s*(\d+)\s+Integrit\S*\s*=\s*(\d+)")
RX_MARONI_EDIZ = re.compile(r"Edizione\s+(\d{4})")
RX_MARONI_TIT = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def maroni_sitemap():
    rob = prepara_sito(MARONI, MARONI_HOST)
    d = RAW / MARONI
    idx = d / "sitemap.xml"
    if not idx.exists():
        idx.write_bytes(prendi(f"https://{MARONI_HOST}/sitemap.xml"))
        time.sleep(PAUSA_MARONI)
    for loc in re.findall(r"<loc>([^<]*sitemap-vini-[^<]*)</loc>", idx.read_text(encoding="utf-8")):
        f = d / loc.rsplit("/", 1)[1]
        if not f.exists():
            if not rob.permesso(loc):
                print("vietato", loc)
                continue
            f.write_bytes(prendi(loc, 180))
            time.sleep(PAUSA_MARONI)
    print("maroni sitemap ok:", len(maroni_urls()), "schede vino")


def maroni_urls():
    urls = []
    for f in sorted((RAW / MARONI).glob("sitemap-vini-*.xml")):
        urls += [htmllib.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", f.read_text(encoding="utf-8"))]
    return list(dict.fromkeys(urls))


def maroni_estrai_slug(u):
    m = re.match(r"https://www\.lucamaroni\.it/vini/\d+-(.+)$", u)
    if not m:
        return None
    a = re.search(r"-((?:19|20)\d\d)$", m.group(1))
    if not a:
        return None
    return m.group(1)[: a.start()].replace("-", " "), a.group(1)


def maroni_pagina(u):
    return RAW / MARONI / "pagine" / nome_file(u)


def maroni_abbina():
    # Maroni valuta soprattutto vini italiani: si abbinano solo i vini italiani della carta (i francesi non ci sono)
    vini, prezzo = VA.leggi_vini()
    ita = [v for v in vini if v["codice_paese"] == "IT"]
    slugs = entrate_slug(maroni_urls(), maroni_estrai_slug)
    print(len(ita), "vini italiani Peck,", len(slugs), "schede Maroni con annata")
    scrivi_candidati(MARONI, abbina_slug(ita, prezzo, slugs))


def maroni_leggi(url, dati):
    """Solo titolo, punteggio (e le tre parti), edizione dell'Annuario. Niente altro testo."""
    t = dati.decode("utf-8", errors="replace")
    titolo = RX_MARONI_TIT.search(t)
    testo = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", t)
    testo = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", testo)))
    m = RX_MARONI_DETT.search(testo)
    e = RX_MARONI_EDIZ.search(testo)
    out = {"url": url, "titolo": htmllib.unescape(titolo.group(1)).strip() if titolo else "",
           "scaricata": OGGI, "edizione": e.group(1) if e else ""}
    if m:
        a, b, c, tot = (int(x) for x in m.groups())
        out.update({"punteggio": tot, "parti": [a, b, c]})
    return out


def maroni_scarica(limite=None):
    global PAUSA
    PAUSA = PAUSA_MARONI
    urls = []
    for r in leggi_candidati(MARONI):
        if r["url"] not in urls:
            urls.append(r["url"])
    scarica_pagine(MARONI, MARONI_HOST, urls, maroni_pagina, maroni_leggi, limite)


def righe_maroni():
    out = []
    cand = defaultdict(list)
    if not (RAW / MARONI / "candidati.csv").exists():
        return out
    for r in leggi_candidati(MARONI):
        cand[r["url"]].append(r)
    for url, rs in cand.items():
        f = maroni_pagina(url)
        if not f.exists():
            continue
        pag = json.loads(f.read_text(encoding="utf-8"))
        if pag.get("errore") or "punteggio" not in pag:
            continue
        anno_url = url.rsplit("-", 1)[1]
        for r in rs:
            out.append({"id": r["id"], "fonte": MARONI_NOME, "critico_o_tipo": "Luca Maroni",
                        "voto": pag["punteggio"], "scala": "100", "annata_fonte": anno_url,
                        "corrispondenza": "esatta" if r["distanza"] == "0" else "annata diversa ±2",
                        "url": url, "licenza_note": LIC_MARONI, "voto_testo": str(pag["punteggio"]),
                        "recensore": f"Annuario {pag['edizione']}" if pag.get("edizione") else "",
                        "nome_fonte": pag["titolo"], "data_raccolta": pag.get("scaricata", "")})
    return out


# ---------------------------------------------------------------- Vinfolio (vinfolio.com)
VINF = "vinfolio"
VINF_HOST = "vinfolio.com"
VINF_NOME = "Vinfolio"
PAUSA_VINF = 2.0
RX_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def vinf_sitemap():
    rob = prepara_sito(VINF, "www.vinfolio.com")
    f = RAW / VINF / "sitemap-products.xml"
    if not f.exists():
        url = f"https://{VINF_HOST}/sitemap-products.xml"
        if not rob.permesso(url):
            raise SystemExit("vietato " + url)
        f.write_bytes(prendi(url, 180))
    print("vinfolio sitemap ok:", len(vinf_urls()), "schede prodotto")


def vinf_urls():
    t = (RAW / VINF / "sitemap-products.xml").read_text(encoding="utf-8")
    return list(dict.fromkeys(htmllib.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", t)))


def vinf_estrai_slug(u):
    m = re.match(r"https://vinfolio\.com/product/[0-9a-f]+/((?:19|20)\d\d|nv)-(.+)$", u)
    if not m:
        return None
    return m.group(2).replace("-", " "), ("NV" if m.group(1) == "nv" else m.group(1))


def vinf_pagina(u):
    return RAW / VINF / "pagine" / nome_file(u)


def vinf_abbina():
    vini, prezzo = VA.leggi_vini()
    slugs = entrate_slug(vinf_urls(), vinf_estrai_slug)
    print(len(vini), "vini Peck,", len(slugs), "schede Vinfolio con annata")
    scrivi_candidati(VINF, abbina_slug(vini, prezzo, slugs))


def vinf_leggi(url, dati):
    """Dai dati della pagina (__NEXT_DATA__) si tengono SOLO: nome, media del negozio e, per ogni recensione,
    chi, voto, scala e data. Il commento (testo della recensione) non si legge."""
    t = dati.decode("utf-8", errors="replace")
    m = RX_NEXT.search(t)
    if not m:
        return {"url": url, "errore": "senza dati"}
    pp = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
    prod = pp.get("product") or {}
    revs = []
    for r in prod.get("reviews") or []:
        revs.append({"chi": (r.get("reviewer") or {}).get("name", ""), "da": r.get("scoreFrom"), "a": r.get("scoreTo"),
                     "piu": bool(r.get("scorePlus")), "scala": r.get("scoreScale"),
                     "data": (r.get("date") or "")[:7]})
    return {"url": url, "nome": prod.get("name", ""), "media_negozio": prod.get("avgCriticScore"),
            "scaricata": OGGI, "recensioni": revs}


def vinf_scarica(limite=None):
    global PAUSA
    PAUSA = PAUSA_VINF
    urls = []
    for r in leggi_candidati(VINF):
        if r["url"] not in urls:
            urls.append(r["url"])
    scarica_pagine(VINF, "www.vinfolio.com", urls, vinf_pagina, vinf_leggi, limite)


def critico_da_nome(nome):
    k = nome.lower()
    base = k.split("(")[0].strip()
    if base in PUBBLICAZIONI:
        return PUBBLICAZIONI[base][0]
    for chiave, canonico in (("jancis robinson", "Jancis Robinson"), ("neal martin", "Vinous (Neal Martin)"),
                             ("antonio galloni", "Vinous (Antonio Galloni)"), ("james suckling", "James Suckling"),
                             ("jeb dunnuck", "Jeb Dunnuck"), ("robert parker", "Robert Parker"),
                             ("allen meadows", "Burghound"), ("stephen tanzer", "Vinous (Stephen Tanzer)")):
        if chiave in k:
            return canonico
    return nome


def righe_vinfolio():
    out = []
    if not (RAW / VINF / "candidati.csv").exists():
        return out
    cand = defaultdict(list)
    for r in leggi_candidati(VINF):
        cand[r["url"]].append(r)
    for url, rs in cand.items():
        f = vinf_pagina(url)
        if not f.exists():
            continue
        pag = json.loads(f.read_text(encoding="utf-8"))
        if pag.get("errore"):
            continue
        anno_url = re.search(r"/((?:19|20)\d\d|nv)-", url).group(1).upper()
        # per ogni testata si tiene la recensione piu' recente (senza data = la meno recente)
        migliori = {}
        for rv in pag["recensioni"]:
            chi = rv["chi"]
            if "," in chi:
                rec, pub = chi.rsplit(",", 1)
            else:
                rec, pub = chi, ""
            nome = critico_canonico(pub.strip(), rec.strip()) if pub.strip() else critico_da_nome(rec.strip())
            if rv["da"] is None or rv["scala"] not in (100, 20):
                continue
            a, b = rv["da"], rv["a"]
            val = (a + b) / 2 if b is not None else float(a)
            testo = f"{a}-{b}" if b is not None else (f"{a}+" if rv["piu"] else f"{a}")
            testo += f"/{rv['scala']}"
            chiave = nome.split("(")[0].strip()
            if chiave not in migliori or rv["data"] >= migliori[chiave]["data"]:
                migliori[chiave] = dict(nome=nome, val=val, scala=str(rv["scala"]), testo=testo, rec=rec.strip(),
                                        data=rv["data"])
        for m_ in migliori.values():
            if m_["scala"] == "100" and not 50 <= m_["val"] <= 100:
                continue
            if m_["scala"] == "20" and not 10 <= m_["val"] <= 20:
                continue
            for r in rs:
                out.append({"id": r["id"], "fonte": VINF_NOME, "critico_o_tipo": m_["nome"], "voto": round(m_["val"], 2),
                            "scala": m_["scala"], "annata_fonte": anno_url,
                            "corrispondenza": "esatta" if r["distanza"] == "0" else "annata diversa ±2",
                            "url": url, "licenza_note": LIC_VINF, "voto_testo": m_["testo"], "recensore": m_["rec"],
                            "nome_fonte": pag["nome"], "data_raccolta": pag.get("scaricata", ""),
                            "data_recensione": m_["data"]})
    return out


# ---------------------------------------------------------------- Bettane+Desseauve (mybettanedesseauve.fr)
BD = "bettane"
BD_HOST = "www.mybettanedesseauve.fr"
BD_NOME = "Bettane+Desseauve"
PAUSA_BD = 3.0
RX_BD_NOTA = re.compile(r"NOTE DE L.EXPERT\s*(N/N|\d{1,3}(?:[.,]\d)?)\s*/\s*(20|100)", re.I)
RX_BD_TIT = re.compile(r"D.tail du vin\s*(?:D.tail du vin)?\s*.\s*Retour\s*(.*?)\s*NOTE DE L.EXPERT", re.I | re.S)


def bd_sitemap():
    rob = prepara_sito(BD, BD_HOST)
    d = RAW / BD
    idx = d / "wine-sitemap-index.xml"
    if not idx.exists():
        idx.write_bytes(prendi(f"https://{BD_HOST}/wine-sitemap-index.xml"))
        time.sleep(PAUSA_BD)
    for loc in re.findall(r"<loc>([^<]+)</loc>", idx.read_text(encoding="utf-8")):
        f = d / loc.rsplit("/", 1)[1]
        if not f.exists():
            if not rob.permesso(loc):
                print("vietato", loc)
                continue
            f.write_bytes(prendi(loc, 180))
            time.sleep(PAUSA_BD)
    print("bettane sitemap ok:", len(bd_urls()), "schede vino")


def bd_urls():
    urls = []
    for f in sorted((RAW / BD).glob("wine-sitemap-[0-9]*.xml")):
        urls += [htmllib.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", f.read_text(encoding="utf-8"))]
    return list(dict.fromkeys(urls))


def bd_estrai_slug(u):
    m = re.match(r"https://www\.mybettanedesseauve\.fr/vins/([^/]+)/(.+)-((?:19|20)\d\d|nv)-(\d+)/?$", u)
    if not m:
        return None
    return m.group(2).replace("-", " "), ("NV" if m.group(3) == "nv" else m.group(3))


def bd_pagina(u):
    return RAW / BD / "pagine" / nome_file(u)


def bd_abbina():
    vini, prezzo = VA.leggi_vini()
    slugs = entrate_slug(bd_urls(), bd_estrai_slug)
    print(len(vini), "vini Peck,", len(slugs), "schede B+D con annata")
    scrivi_candidati(BD, abbina_slug(vini, prezzo, slugs))


def bd_leggi(url, dati):
    """Solo titolo e nota dell'esperto (su 20). Commento, note del domaine e altri vini non si leggono."""
    t = dati.decode("utf-8", errors="replace")
    testo = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", t)
    testo = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", testo)))
    m = RX_BD_NOTA.search(testo)
    tit = RX_BD_TIT.search(testo)
    out = {"url": url, "titolo": tit.group(1).strip() if tit else "", "scaricata": OGGI}
    if m and m.group(1).upper() != "N/N":
        out["nota"] = float(m.group(1).replace(",", "."))
        out["scala"] = m.group(2)
    return out


def bd_scarica(limite=None):
    global PAUSA
    PAUSA = PAUSA_BD
    urls = []
    for r in leggi_candidati(BD):
        if r["url"] not in urls:
            urls.append(r["url"])
    scarica_pagine(BD, BD_HOST, urls, bd_pagina, bd_leggi, limite)


def righe_bettane():
    out = []
    if not (RAW / BD / "candidati.csv").exists():
        return out
    cand = defaultdict(list)
    for r in leggi_candidati(BD):
        cand[r["url"]].append(r)
    for url, rs in cand.items():
        f = bd_pagina(url)
        if not f.exists():
            continue
        pag = json.loads(f.read_text(encoding="utf-8"))
        if pag.get("errore") or "nota" not in pag:
            continue
        if not (8 <= pag["nota"] <= 20 if pag["scala"] == "20" else 50 <= pag["nota"] <= 100):
            continue
        m = re.match(r".*-((?:19|20)\d\d|nv)-\d+/?$", url)
        anno_url = m.group(1).upper()
        for r in rs:
            out.append({"id": r["id"], "fonte": BD_NOME, "critico_o_tipo": "Bettane+Desseauve", "voto": pag["nota"],
                        "scala": pag["scala"], "annata_fonte": anno_url,
                        "corrispondenza": "esatta" if r["distanza"] == "0" else "annata diversa ±2",
                        "url": url, "licenza_note": LIC_BD, "voto_testo": f"{pag['nota']:g}/{pag['scala']}", "recensore": "",
                        "nome_fonte": pag["titolo"], "data_raccolta": pag.get("scaricata", ""), "data_recensione": ""})
    return out


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
def estrai():
    vini, prezzo = VA.leggi_vini()
    righe = []
    righe += righe_maroni()
    righe += righe_vinfolio()
    righe += righe_bettane()
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
    fn = {"bd_sitemap": bd_sitemap, "bd_abbina": bd_abbina, "bd_scarica": lambda: bd_scarica(arg),
          "vinf_sitemap": vinf_sitemap, "vinf_abbina": vinf_abbina, "vinf_scarica": lambda: vinf_scarica(arg),
          "maroni_sitemap": maroni_sitemap, "maroni_abbina": maroni_abbina,
          "maroni_scarica": lambda: maroni_scarica(arg),
          "ws_scarica": ws_scarica, "estrai": estrai, "riepilogo": riepilogo,
          "verifica": lambda: verifica(arg or 30)}.get(cmd)
    if fn:
        fn()
    else:
        print(__doc__)
