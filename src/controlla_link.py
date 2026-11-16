"""Controlla che i link usati dal sito si aprano ancora.

Uso (dalla cartella peck-tracker, Python 3.12):

    python -I src/controlla_link.py                 # aziende.csv + un campione di 40 link dei vini
    python -I src/controlla_link.py --vini-tutti    # tutti i 3.071 link dei vini (circa un'ora)
    python -I src/controlla_link.py --solo-aziende  # niente vini

Legge:  data/aziende.csv (colonne sito, link_shop, fonte) e data/vini.csv (colonna link);
        data/link_verifica_manuale.csv (facoltativo: esiti decisi a mano per i link su cui un robot
        sbaglia, per esempio un sito che chiude la connessione ai programmi ma si apre nel browser).
Scrive: data/link_controllati.csv con una riga per ogni (link, campo, chiave):
        url, campo, chiave, status, url_finale, esito, nota

Come controlla: una richiesta GET con l'User-Agent di un browser, segue i reindirizzamenti,
15 secondi di attesa massima, un secondo tentativo se fallisce, 1 secondo di pausa fra due
richieste allo stesso sito. Non scarica piu' di 300 KB per pagina.

Esiti:
  ok                    la pagina si apre (risposta 2xx)
  rotto                 404, 410, 5xx o la pagina porta alla home di un altro sito/di un altro dominio
  bloccato              il sito risponde 401/403/429 o con una pagina anti-robot: un robot non
                        puo' dire se il link e' buono, va guardato a mano
  dominio_parcheggiato  la pagina e' un dominio in vendita / parcheggiato
  errore                nessuna risposta (nome del sito che non si trova, connessione rifiutata,
                        tempo scaduto...): in `status` c'e' il tipo di errore

Il sito (src/sito.py) non mostra mai il bottone di un link marcato `rotto` o `dominio_parcheggiato`
in questo file. Per `errore` serve un secondo controllo (da questo computer alcuni nomi di siti
non si risolvono: provare da un altro programma, per esempio il browser).
"""

import argparse
import csv
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

RADICE = Path(__file__).resolve().parent.parent
DATI = RADICE / "data"
USCITA = DATI / "link_controllati.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEAD = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.5"}
TIMEOUT = 15
PAUSA_STESSO_SITO = 1.0
MAX_BYTE = 300_000

SITI_PARCHEGGIO = ("sedoparking.com", "sedo.com", "hugedomains.com", "dan.com", "afternic.com",
                   "parkingcrew.net", "bodis.com", "above.com", "undeveloped.com",
                   "godaddy.com/forsale", "domainmarket.com", "squadhelp.com", "namecheap.com/domains")
FRASI_PARCHEGGIO = (
    "this domain is for sale", "this domain may be for sale", "domain is for sale", "buy this domain",
    "the domain name is for sale", "domain for sale", "questo dominio e' in vendita",
    "questo dominio è in vendita", "dominio in vendita", "acquista questo dominio",
    "this domain is parked", "domain parked", "dominio parcheggiato", "sito in costruzione",
    "parked free", "inquire about this domain", "make an offer on this domain",
)
FRASI_ANTIROBOT = ("just a moment", "attention required", "checking your browser", "cf-browser-verification",
                   "enable javascript and cookies", "access denied", "verify you are human",
                   "captcha", "px-captcha", "request unsuccessful", "incapsula")

_ultima_richiesta = {}
_blocco = threading.Lock()
_blocchi_sito = {}


def attendi_sito(host):
    """Garantisce 1 secondo fra due richieste allo stesso sito (anche con piu' thread)."""
    with _blocco:
        lk = _blocchi_sito.setdefault(host, threading.Lock())
    with lk:
        pausa = PAUSA_STESSO_SITO - (time.time() - _ultima_richiesta.get(host, 0))
        if pausa > 0:
            time.sleep(pausa)
        _ultima_richiesta[host] = time.time()


def senza_www(h):
    return h[4:] if h.startswith("www.") else h


def controlla(url):
    """Ritorna (status, url_finale, esito, nota)."""
    host = urlparse(url).netloc.lower()
    ultimo_errore, nota = "", ""
    for tentativo in (1, 2):
        attendi_sito(host)
        try:
            with requests.get(url, headers=HEAD, timeout=TIMEOUT, allow_redirects=True, stream=True) as r:
                corpo = b""
                for blocco in r.iter_content(65536):
                    corpo += blocco
                    if len(corpo) >= MAX_BYTE:
                        break
                testo = corpo.decode(r.encoding or "utf-8", errors="replace").lower()
                finale = r.url
                s = r.status_code
        except requests.exceptions.SSLError as e:
            ultimo_errore = "SSL"
            nota = str(e)[:120]
            continue
        except requests.exceptions.ConnectionError as e:
            msg = str(e)
            ultimo_errore = "DNS" if ("getaddrinfo" in msg or "Name or service" in msg
                                      or "NameResolution" in msg) else "connessione"
            nota = msg[:120]
            continue
        except requests.exceptions.Timeout:
            ultimo_errore, nota = "timeout", ""
            continue
        except requests.RequestException as e:
            ultimo_errore, nota = type(e).__name__, str(e)[:120]
            continue

        fin = urlparse(finale)
        # dominio in vendita / parcheggiato
        if any(p in (fin.netloc + fin.path).lower() or p in fin.netloc.lower() for p in SITI_PARCHEGGIO):
            return s, finale, "dominio_parcheggiato", "porta a un servizio che vende domini"
        if s < 400 and len(corpo) < 60_000 and any(f in testo for f in FRASI_PARCHEGGIO):
            return s, finale, "dominio_parcheggiato", "la pagina dice che il dominio e' in vendita/parcheggiato"
        if s in (401, 403, 429):
            return s, finale, "bloccato", "il sito rifiuta i robot (da guardare a mano)"
        if s == 503 and any(f in testo for f in FRASI_ANTIROBOT):
            return s, finale, "bloccato", "pagina anti-robot"
        if s < 300 and len(corpo) < 20_000 and any(f in testo for f in FRASI_ANTIROBOT):
            return s, finale, "bloccato", "pagina anti-robot"
        if s < 300:
            m = re.search(r"<title[^>]*>(.*?)</title>", testo, re.S)
            titolo = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            if re.search(r"404|not found|non trovata|non esiste|page introuvable|nicht gefunden|"
                         r"pagina non disponibile|errore 404", titolo):
                return s, finale, "rotto", "risposta 200 ma il titolo dice: " + titolo[:80]
        if s >= 400:
            if tentativo == 1 and s >= 500:
                ultimo_errore = str(s)
                continue
            return s, finale, "rotto", ""
        # reindirizzato su un sito diverso (cambio di dominio) -> lo segnaliamo ma e' ok
        nota = ""
        if senza_www(fin.netloc.lower()) != senza_www(host):
            nota = "reindirizzato su un altro sito: " + fin.netloc
        # il link portava a una pagina interna ma e' finito sulla home: spesso una pagina sparita
        orig = urlparse(url)
        if len(orig.path.strip("/")) > 0 and fin.path.strip("/") == "" and not fin.query \
                and ".".join(fin.netloc.lower().split(".")[-2:]) == ".".join(host.split(".")[-2:])                 and finale.rstrip("/") != url.rstrip("/"):
            return s, finale, "rotto", "reindirizzato alla home: la pagina non c'e' piu'"
        return s, finale, "ok", nota
    return ultimo_errore, "", "errore", nota


def raccogli(vini_tutti, solo_aziende, campione, seme):
    """Lista di (url, campo, chiave)."""
    righe = []
    with open(DATI / "aziende.csv", encoding="utf-8-sig", newline="") as f:
        for a in csv.DictReader(f):
            for campo in ("sito", "link_shop", "fonte"):
                u = (a.get(campo) or "").strip()
                if u.startswith("http"):
                    righe.append((u, campo, f"{a['tipo_chiave']}: {a['chiave']}"))
    if not solo_aziende:
        with open(DATI / "vini.csv", encoding="utf-8-sig", newline="") as f:
            visti, vini = set(), []
            for r in csv.DictReader(f):
                if r["id"] not in visti:
                    visti.add(r["id"])
                    vini.append((r["link"], "vino_link", f"{r['id']}: {r['cantina']} {r['nome']}"))
        if not vini_tutti:
            random.Random(seme).shuffle(vini)
            vini = vini[:campione]
        righe += vini
    return righe


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--vini-tutti", action="store_true")
    ap.add_argument("--solo-aziende", action="store_true")
    ap.add_argument("--campione-vini", type=int, default=40)
    ap.add_argument("--thread", type=int, default=6)
    ap.add_argument("--seme", type=int, default=1)
    a = ap.parse_args()

    righe = raccogli(a.vini_tutti, a.solo_aziende, a.campione_vini, a.seme)
    urls = list(dict.fromkeys(u for u, _, _ in righe))
    print(f"{len(righe)} link da controllare ({len(urls)} indirizzi diversi)", flush=True)

    risultati = {}

    def lavora(u):
        risultati[u] = controlla(u)
        return u

    with ThreadPoolExecutor(max_workers=a.thread) as ex:
        for i, _ in enumerate(ex.map(lavora, urls), 1):
            if i % 25 == 0:
                print(f"  {i}/{len(urls)}", flush=True)

    # controlli fatti a mano (per esempio con un altro programma o con il browser), per i link su cui
    # questo programma sbaglia: data/link_verifica_manuale.csv (url, esito, nota)
    manuali = {}
    f_man = DATI / "link_verifica_manuale.csv"
    if f_man.exists():
        with open(f_man, encoding="utf-8-sig", newline="") as f:
            manuali = {r["url"]: r for r in csv.DictReader(f)}
        for u, r in manuali.items():
            if u in risultati:
                s, fin, esito, nota = risultati[u]
                risultati[u] = (s, fin, r["esito"], "verifica a mano: " + r["nota"] + (
                    f" (il programma aveva scritto: {esito})" if esito != r["esito"] else ""))

    conteggio = {}
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "campo", "chiave", "status", "url_finale", "esito", "nota"])
        for u, campo, chiave in righe:
            s, fin, esito, nota = risultati[u]
            w.writerow([u, campo, chiave, s, fin, esito, nota])
            conteggio[(campo, esito)] = conteggio.get((campo, esito), 0) + 1
    print("\nrisultato per campo e esito:")
    for (campo, esito), n in sorted(conteggio.items()):
        print(f"  {campo:10} {esito:22} {n}")
    print("scritto", USCITA)


if __name__ == "__main__":
    main()
