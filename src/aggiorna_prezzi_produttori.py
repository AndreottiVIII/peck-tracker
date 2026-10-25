"""Aggiorna i prezzi dei produttori nei confronti Peck / produttore (data/confronto/risultati_*.csv).

    python -I src/aggiorna_prezzi_produttori.py [--pausa 2] [--solo-controllo] [--limite N] [--max-minuti N]

Per ogni riga dei file `data/confronto/risultati_*.csv` che ha un `url_produttore` e una somiglianza
«stesso prodotto» o «molto simile» legge di nuovo il prezzo corrente dalla pagina del prodotto e aggiorna
sul posto `prezzo_produttore`, `prezzo_produttore_al_kg`, `differenza_pct` e `data`. Ogni variazione di prezzo
e' registrata in `data/confronto/storico_prezzi.csv` (data, url, prezzo_vecchio, prezzo_nuovo).

Come si legge il prezzo (si prova nell'ordine, con un solo tentativo per metodo):
  1. Shopify (l'indirizzo contiene /products/<handle>): <indirizzo>.json, poi <indirizzo>.js;
  2. WooCommerce (indirizzo con /prodotto/, /product/, /negozio/...): API pubblica dello store,
     /wp-json/wc/store/v1/products?slug=<slug>;
  3. altrimenti la pagina del prodotto, dal JSON-LD (Offer) o dai meta product:price:amount.

Regole (le stesse del resto del progetto):
  - robots.txt riletto per ogni sito a ogni avvio. Si rispetta il gruppo `*` (o quello di `peck-tracker`) e anche
    le sezioni dedicate agli agenti AI di Anthropic (ClaudeBot, Claude-Web, Claude-User, Claude-SearchBot,
    anthropic-ai): se vietano la pagina, il sito si salta, senza cambiare User-Agent. Crawl-delay rispettato.
    robots.txt non raggiungibile (errore del server) = il sito si salta.
  - fornofollador.it e casaiuorio.it si saltano sempre (vietano gli agenti AI; il confronto resta «non verificato»).
  - 2 secondi di pausa fra una richiesta e l'altra, un solo sito alla volta, niente login, niente aggiramento
    di blocchi: 403/429 persistenti = quel sito si salta fino alla prossima volta.
  - Un sito che non risponde non ferma il programma: la riga resta com'e' (con la sua vecchia data).
  - Se il prodotto ha piu' varianti (formati) si sceglie quella con lo stesso formato della riga, o quella che
    aveva gia' il prezzo scritto; nel dubbio la riga non si tocca. Una variazione oltre il -50%/+100% non si
    applica (si segnala e basta: puo' essere un errore di lettura).
  - I prezzi di Peck (delivery) richiedono un login: non si toccano mai.
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

RADICE = Path(__file__).resolve().parent.parent
CARTELLA = RADICE / "data" / "confronto"
STORICO = CARTELLA / "storico_prezzi.csv"
COLONNE_STORICO = ["data", "url", "prezzo_vecchio", "prezzo_nuovo"]

UA = "Mozilla/5.0 (compatible; peck-tracker research; non-commercial)"
TOKEN_NOSTRO = "peck-tracker"
AGENTI_AI = ["claudebot", "claude-web", "claude-user", "claude-searchbot", "anthropic-ai", "anthropic"]
SEMPRE_SALTATI = ("fornofollador.it", "casaiuorio.it")
LIVELLI = ("stesso prodotto", "molto simile")
MIN_RAPPORTO, MAX_RAPPORTO = 0.5, 2.0      # variazioni oltre queste non si applicano
TIMEOUT = 30
RITARDO_MASSIMO = 60                        # un Crawl-delay piu' lungo = il sito si salta


# ---------------------------------------------------------------- robots.txt
def schema_regex(schema):
    """Percorso di robots.txt (con * e $) -> espressione regolare."""
    fine = schema.endswith("$")
    corpo = schema[:-1] if fine else schema
    r = "".join(".*" if c == "*" else re.escape(c) for c in corpo)
    return re.compile(r + ("$" if fine else ""))


class Robots:
    """Gruppi di un robots.txt. `ok` e' False se il file non si e' potuto leggere (si salta il sito)."""

    def __init__(self, testo="", ok=True):
        self.ok = ok
        self.gruppi = []   # [(set di agenti in minuscolo, [(permesso, regex)], ritardo o None)]
        agenti, regole, ritardo, in_regole = set(), [], None, False
        gruppi_grezzi = []
        for riga in testo.splitlines():
            riga = riga.split("#", 1)[0].strip()
            if ":" not in riga:
                continue
            k, v = (x.strip() for x in riga.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if in_regole:   # un nuovo gruppo comincia dopo le regole del precedente
                    gruppi_grezzi.append((agenti, regole, ritardo))
                    agenti, regole, ritardo, in_regole = set(), [], None, False
                agenti.add(v.lower())
            elif k in ("allow", "disallow"):
                in_regole = True
                if v:   # "Disallow:" vuoto = tutto permesso
                    regole.append((k == "allow", schema_regex(v), len(v)))
            elif k == "crawl-delay":
                in_regole = True
                try:
                    ritardo = float(v)
                except ValueError:
                    pass
        if agenti:
            gruppi_grezzi.append((agenti, regole, ritardo))
        self.gruppi = gruppi_grezzi

    def _gruppi(self, agente):
        return [g for g in self.gruppi if agente in g[0]]

    @staticmethod
    def _decide(gruppi, percorso):
        """True se permesso: vince la regola piu' lunga che corrisponde, a parita' vince 'allow'."""
        migliore = None
        for _, regole, _ in gruppi:
            for permesso, rx, lunghezza in regole:
                if rx.match(percorso):
                    if migliore is None or lunghezza > migliore[1] or (lunghezza == migliore[1] and permesso):
                        migliore = (permesso, lunghezza)
        return True if migliore is None else migliore[0]

    def permesso(self, percorso):
        """(permesso, motivo del divieto). Gruppo di peck-tracker se c'e', altrimenti `*`; in piu' le sezioni
        degli agenti AI di Anthropic: se una vieta la pagina, non si scarica."""
        if not self.ok:
            return False, "robots.txt non raggiungibile"
        generico = self._gruppi(TOKEN_NOSTRO) or self._gruppi("*")
        if not self._decide(generico, percorso):
            return False, "vietato da robots.txt"
        for a in AGENTI_AI:
            g = self._gruppi(a)
            if g and not self._decide(g, percorso):
                return False, f"robots.txt vieta {a}"
        return True, ""

    def ritardo(self):
        r = [g[2] for g in (self._gruppi(TOKEN_NOSTRO) or self._gruppi("*")) if g[2]]
        for a in AGENTI_AI:
            r += [g[2] for g in self._gruppi(a) if g[2]]
        return max(r) if r else 0.0


# ---------------------------------------------------------------- rete
class Rete:
    """Una richiesta alla volta, con pausa; ricorda i siti che bloccano."""

    def __init__(self, pausa):
        self.pausa = pausa
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9",
                               "Accept": "application/json, text/html;q=0.9, */*;q=0.5"})
        self.ultima = 0.0
        self.robots = {}      # host -> Robots
        self.ritardi = {}     # host -> secondi
        self.bloccati = {}    # host -> motivo
        self.ultima_host = {}

    def _aspetta(self, host):
        ora = time.time()
        attesa = max(self.pausa - (ora - self.ultima),
                     max(self.pausa, self.ritardi.get(host, 0)) - (ora - self.ultima_host.get(host, 0)))
        if attesa > 0:
            time.sleep(attesa)

    def get(self, url, host=None):
        """(risposta o None, errore). Un solo riprova, solo per 5xx e problemi di rete."""
        host = host or urllib.parse.urlsplit(url).netloc
        errore = ""
        for tentativo in (1, 2):
            self._aspetta(host)
            try:
                r = self.s.get(url, timeout=TIMEOUT)
            except requests.RequestException as e:
                self.ultima = self.ultima_host[host] = time.time()
                errore = type(e).__name__
                time.sleep(5)
                continue
            self.ultima = self.ultima_host[host] = time.time()
            if r.status_code == 429:
                if tentativo == 1:
                    print(f"  429 da {host}: aspetto 60 s", flush=True)
                    time.sleep(60)
                    errore = "HTTP 429"
                    continue
                self.bloccati[host] = "429 persistente"
                return None, "HTTP 429"
            if r.status_code in (401, 403):
                self.bloccati[host] = f"HTTP {r.status_code}"
                return None, f"HTTP {r.status_code}"
            if r.status_code >= 500:
                errore = f"HTTP {r.status_code}"
                time.sleep(10)
                continue
            return r, ""
        return None, errore

    def regole(self, schema, host):
        if host in self.robots:
            return self.robots[host]
        r, err = self.get(f"{schema}://{host}/robots.txt", host)
        if r is None:
            rob = Robots(ok=False)
        elif r.status_code == 200:
            rob = Robots(r.content.decode("utf-8", errors="replace"))
        elif r.status_code < 500:   # 404 e simili: nessuna regola
            rob = Robots("")
        else:
            rob = Robots(ok=False)
        self.robots[host] = rob
        self.ritardi[host] = rob.ritardo()
        return rob


# ---------------------------------------------------------------- numeri e formati
def prezzo_da(x):
    """Prezzo come numero (euro) da '12,30', '1.234,50', '12.3', 12.3; None se non si capisce."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    t = re.sub(r"[^0-9,.\-]", "", str(x))
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


RE_QUANTITA = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?(kg|gr|g|ml|cl|lt|l)\b", re.I)


def quantita(testo):
    """(valore in g o ml, 'g'|'ml') della prima quantita' scritta nel testo, oppure None."""
    for m in RE_QUANTITA.finditer(testo or ""):
        v = float(m.group(1).replace(",", "."))
        u = m.group(2).lower()
        if u == "kg":
            return v * 1000, "g"
        if u in ("g", "gr"):
            return v, "g"
        if u == "l" or u == "lt":
            return v * 1000, "ml"
        if u == "cl":
            return v * 10, "ml"
        return v, "ml"
    return None


def stessa_quantita(a, b):
    return bool(a and b and a[1] == b[1] and abs(a[0] - b[0]) <= 0.02 * max(a[0], b[0]))


def testo_prezzo(x):
    """Come i file scrivono i numeri: str(round(x, 2)) -> '17.0', '56.67'."""
    return str(round(x, 2))


# ---------------------------------------------------------------- lettura del prezzo
def candidato(prezzo, titolo="", grammi=None, disponibile=None):
    return {"prezzo": prezzo, "titolo": titolo or "", "grammi": grammi, "disponibile": disponibile}


def da_shopify(rete, url_pagina, host, schema, rob):
    """Varianti dal JSON di Shopify. (candidati, errore)."""
    p = urllib.parse.urlsplit(url_pagina)
    m = re.match(r"^(.*?/products/[^/?#]+?)(?:\.js|\.json)?/?$", p.path)
    if not m:
        return None, "indirizzo non Shopify"
    base = f"{schema}://{host}{m.group(1)}"
    err = "nessun JSON"
    for suffisso in (".json", ".js"):
        perc = m.group(1) + suffisso
        ok, motivo = rob.permesso(perc)
        if not ok:
            err = motivo
            continue
        r, e = rete.get(base + suffisso, host)
        if host in rete.bloccati:
            return None, rete.bloccati[host]
        if r is None or r.status_code != 200:
            err = e or f"HTTP {r.status_code if r is not None else '?'}"
            continue
        try:
            j = r.json()
        except ValueError:
            err = "risposta non JSON"
            continue
        prod = j.get("product", j)
        out = []
        for v in prod.get("variants") or []:
            prezzo = prezzo_da(v.get("price"))
            if prezzo is None:
                continue
            if suffisso == ".js":   # in .js il prezzo e' in centesimi
                prezzo = prezzo / 100
            grammi = v.get("grams") or (v.get("weight") if suffisso == ".js" else None)
            out.append(candidato(prezzo, " ".join(str(v.get(k) or "") for k in ("title", "option1", "option2")),
                                 float(grammi) if grammi else None, v.get("available")))
        if out:
            return out, ""
        err = "nessuna variante"
    return None, err


def da_woocommerce(rete, url_pagina, host, schema, rob):
    p = urllib.parse.urlsplit(url_pagina)
    slug = urllib.parse.unquote([x for x in p.path.split("/") if x][-1]) if p.path.strip("/") else ""
    if not slug:
        return None, "nessuno slug"
    perc = "/wp-json/wc/store/v1/products"
    ok, motivo = rob.permesso(perc + "?slug=" + slug)
    if not ok:
        return None, motivo
    r, e = rete.get(f"{schema}://{host}{perc}?slug={urllib.parse.quote(slug)}", host)
    if host in rete.bloccati:
        return None, rete.bloccati[host]
    if r is None or r.status_code != 200:
        return None, e or f"HTTP {r.status_code if r is not None else '?'}"
    try:
        j = r.json()
    except ValueError:
        return None, "risposta non JSON"
    if not isinstance(j, list) or not j:
        return None, "prodotto non trovato nell'API"
    out = []
    for it in j:
        pr = it.get("prices") or {}
        if pr.get("currency_code") and pr["currency_code"] != "EUR":
            continue
        minore = int(pr.get("currency_minor_unit", 2) or 0)
        titolo = it.get("name") or ""
        rng = pr.get("price_range")
        if rng:   # prodotto con varianti: il prezzo dipende dalla variante
            for chiave in ("min_amount", "max_amount"):
                if rng.get(chiave):
                    out.append(candidato(int(rng[chiave]) / 10 ** minore, titolo, None, it.get("is_in_stock")))
            continue
        if pr.get("price"):
            out.append(candidato(int(pr["price"]) / 10 ** minore, titolo, None, it.get("is_in_stock")))
    return (out, "") if out else (None, "nessun prezzo nell'API")


def nodi_prodotto(dati):
    """Nodi Product (e ProductGroup) di un JSON-LD, anche dentro @graph o liste."""
    if isinstance(dati, list):
        for x in dati:
            yield from nodi_prodotto(x)
    elif isinstance(dati, dict):
        tipo = dati.get("@type")
        tipi = tipo if isinstance(tipo, list) else [tipo]
        if any(t in ("Product", "ProductGroup", "IndividualProduct") for t in tipi if isinstance(t, str)):
            yield dati
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in dati:
                yield from nodi_prodotto(dati[k])


def offerte_di(prod):
    """Offerte (anche delle varianti) di un nodo Product -> [candidato]."""
    out = []
    titolo = prod.get("name") or ""
    off = prod.get("offers")
    offs = off if isinstance(off, list) else [off] if off else []
    for o in offs:
        if not isinstance(o, dict):
            continue
        valuta = o.get("priceCurrency")
        if valuta and valuta != "EUR":
            continue
        disp = o.get("availability")
        disp = None if disp is None else str(disp).endswith(("InStock", "LimitedAvailability", "PreOrder"))
        nome = o.get("name") or titolo
        if o.get("@type") == "AggregateOffer" or "lowPrice" in o:
            for k in ("lowPrice", "highPrice"):
                p = prezzo_da(o.get(k))
                if p is not None:
                    out.append(candidato(p, nome, None, disp))
            sub = o.get("offers")
            if sub:
                out += offerte_di({"name": nome, "offers": sub})
            continue
        p = prezzo_da(o.get("price"))
        if p is None:
            ps = o.get("priceSpecification")
            ps = ps[0] if isinstance(ps, list) and ps else ps
            p = prezzo_da(ps.get("price")) if isinstance(ps, dict) else None
        if p is not None:
            out.append(candidato(p, nome, None, disp))
    for v in prod.get("hasVariant") or []:
        if isinstance(v, dict):
            out += offerte_di(v)
    return out


def da_pagina(rete, url_pagina, host, schema, rob):
    p = urllib.parse.urlsplit(url_pagina)
    perc = p.path + (("?" + p.query) if p.query else "")
    ok, motivo = rob.permesso(perc)
    if not ok:
        return None, motivo
    r, e = rete.get(url_pagina, host)
    if host in rete.bloccati:
        return None, rete.bloccati[host]
    if r is None or r.status_code != 200:
        return None, e or f"HTTP {r.status_code if r is not None else '?'}"
    soup = BeautifulSoup(r.content, "html.parser")
    out = []
    for sc in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        try:
            dati = json.loads(sc.string or sc.get_text() or "", strict=False)
        except ValueError:
            continue
        for prod in nodi_prodotto(dati):
            out += offerte_di(prod)
    if not out:
        for chiave in ("product:price:amount", "og:price:amount"):
            m = soup.find("meta", attrs={"property": chiave}) or soup.find("meta", attrs={"name": chiave})
            if m and prezzo_da(m.get("content")) is not None:
                valuta = soup.find("meta", attrs={"property": chiave.replace("amount", "currency")})
                if not valuta or valuta.get("content", "EUR") == "EUR":
                    out.append(candidato(prezzo_da(m["content"])))
                    break
    return (out, "") if out else (None, "nessun prezzo nella pagina")


def leggi_prezzi(rete, url):
    """(candidati, metodo, errore) per un indirizzo di prodotto."""
    p = urllib.parse.urlsplit(url)
    host, schema = p.netloc, p.scheme or "https"
    if any(host == d or host.endswith("." + d) for d in SEMPRE_SALTATI):
        return None, "", "sito saltato (vieta gli agenti AI)"
    if host in rete.bloccati:
        return None, "", "sito saltato: " + rete.bloccati[host]
    rob = rete.regole(schema, host)
    if host in rete.bloccati:
        return None, "", "sito saltato: " + rete.bloccati[host]
    if not rob.ok:
        return None, "", "robots.txt non raggiungibile: sito saltato"
    if rob.ritardo() > RITARDO_MASSIMO:
        return None, "", f"Crawl-delay {rob.ritardo():g} s: sito saltato"
    # prima di tutto: la pagina stessa dev'essere permessa, altrimenti niente (nemmeno le API)
    perc = p.path + (("?" + p.query) if p.query else "")
    ok, motivo = rob.permesso(perc)
    if not ok:
        return None, "", "sito saltato: " + motivo
    metodi = []
    if "/products/" in p.path:
        metodi.append(("shopify", da_shopify))
    if re.search(r"/(prodotto|product|prodotti|products|negozio|shop|store)/", p.path):
        metodi.append(("woocommerce", da_woocommerce))
    metodi.append(("json-ld", da_pagina))
    errori = []
    for nome, f in metodi:
        cand, err = f(rete, url, host, schema, rob)
        if cand:
            return cand, nome, ""
        errori.append(f"{nome}: {err}")
        if host in rete.bloccati:
            break
    return None, "", "; ".join(errori)


def scegli(cands, vecchio, formato):
    """Il candidato giusto fra le varianti: (prezzo, disponibile) oppure (None, motivo)."""
    prezzi = {round(c["prezzo"], 2) for c in cands}
    if len(prezzi) == 1:
        return cands[0]["prezzo"], cands[0]["disponibile"], ""
    target = quantita(formato)
    if target:
        giusti = [c for c in cands
                  if (c["grammi"] and target[1] == "g" and stessa_quantita((c["grammi"], "g"), target))
                  or stessa_quantita(quantita(c["titolo"]), target)]
        if giusti and len({round(c["prezzo"], 2) for c in giusti}) == 1:
            return giusti[0]["prezzo"], giusti[0]["disponibile"], ""
    for c in cands:   # la variante che aveva gia' il prezzo scritto nel file
        if vecchio is not None and abs(c["prezzo"] - vecchio) < 0.005:
            return c["prezzo"], c["disponibile"], ""
    return None, None, f"{len(prezzi)} varianti con prezzi diversi e formato non riconosciuto"


# ---------------------------------------------------------------- file
def leggi_righe(percorso):
    with open(percorso, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def scrivi_righe(percorso, righe):
    with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(righe)


def numero(x):
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def raccogli(file_csv):
    """Righe da aggiornare: [(file, indice riga, dict)] e le intestazioni per file."""
    tabelle, lavoro = {}, []
    for f in file_csv:
        righe = leggi_righe(f)
        if not righe:
            continue
        tabelle[f] = righe
        col = righe[0]
        for i, r in enumerate(righe[1:], 1):
            d = dict(zip(col, r))
            if d.get("url_produttore", "").startswith("http") and d.get("somiglianza") in LIVELLI \
                    and numero(d.get("prezzo_produttore")):
                lavoro.append((f, i, d))
    return tabelle, lavoro


def aggiorna_riga(riga, col, nuovo, oggi):
    """Scrive prezzo, prezzo al kg, differenza e data in una riga (lista). Restituisce True se il prezzo e' cambiato."""
    d = dict(zip(col, riga))
    vecchio = numero(d["prezzo_produttore"])
    cambiato = round(nuovo, 2) != round(vecchio, 2)
    if cambiato:
        riga[col.index("prezzo_produttore")] = testo_prezzo(nuovo)
        al_kg_v = numero(d.get("prezzo_produttore_al_kg"))
        al_kg_n = None
        if al_kg_v:
            al_kg_n = round(nuovo * al_kg_v / vecchio, 2)
            riga[col.index("prezzo_produttore_al_kg")] = testo_prezzo(al_kg_n)
        peck_kg = numero(d.get("prezzo_peck_al_kg"))
        diff_v = numero(d.get("differenza_pct"))
        if peck_kg and al_kg_n:
            riga[col.index("differenza_pct")] = str(round((peck_kg / al_kg_n - 1) * 100, 1))
        elif diff_v is not None and d.get("differenza_pct") != "":
            riga[col.index("differenza_pct")] = str(round(((1 + diff_v / 100) * vecchio / nuovo - 1) * 100, 1))
    riga[col.index("data")] = oggi
    return cambiato


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--solo-controllo", action="store_true", help="legge i prezzi ma non scrive niente")
    ap.add_argument("--limite", type=int, default=None, help="solo i primi N indirizzi (per prove)")
    ap.add_argument("--max-minuti", type=float, default=None)
    ap.add_argument("--data", default=None, help="data da scrivere (default: oggi)")
    a = ap.parse_args()
    oggi = a.data or date.today().isoformat()
    scadenza = time.time() + a.max_minuti * 60 if a.max_minuti else None

    file_csv = sorted(CARTELLA.glob("risultati_*.csv"))
    if not file_csv:
        print("nessun file data/confronto/risultati_*.csv: niente da fare")
        return
    tabelle, lavoro = raccogli(file_csv)
    per_url = {}
    for f, i, d in lavoro:
        per_url.setdefault(d["url_produttore"], []).append((f, i, d))
    urls = list(per_url)
    if a.limite:
        urls = urls[:a.limite]
    print(f"{len(lavoro)} righe con prezzo del produttore, {len(urls)} indirizzi da rileggere", flush=True)

    rete = Rete(a.pausa)
    storico, conta, motivi = [], {"letti": 0, "cambiati": 0, "invariati": 0, "saltati": 0}, []
    for n, url in enumerate(urls, 1):
        if scadenza and time.time() > scadenza:
            print("tempo finito: gli altri indirizzi alla prossima volta", flush=True)
            break
        righe_url = per_url[url]
        vecchio = numero(righe_url[0][2]["prezzo_produttore"])
        try:
            cands, metodo, errore = leggi_prezzi(rete, url)
        except Exception as e:   # un sito che si comporta male non deve fermare gli altri
            cands, metodo, errore = None, "", f"errore inatteso: {type(e).__name__}: {e}"
        if not cands:
            conta["saltati"] += 1
            motivi.append((url, errore))
            print(f"  [{n}/{len(urls)}] NON LETTO {url}: {errore}", flush=True)
            continue
        prezzo, disponibile, perche = scegli(cands, vecchio, righe_url[0][2].get("formato_produttore", ""))
        if prezzo is None:
            conta["saltati"] += 1
            motivi.append((url, perche))
            print(f"  [{n}/{len(urls)}] AMBIGUO {url}: {perche}", flush=True)
            continue
        if vecchio and not (MIN_RAPPORTO <= prezzo / vecchio <= MAX_RAPPORTO):
            conta["saltati"] += 1
            motivi.append((url, f"variazione sospetta {vecchio:g} -> {prezzo:g}"))
            print(f"  [{n}/{len(urls)}] SOSPETTO {url}: {vecchio:g} -> {prezzo:g}, non applicato", flush=True)
            continue
        conta["letti"] += 1
        cambiato = False
        for f, i, d in righe_url:
            riga = tabelle[f][i]
            if aggiorna_riga(riga, tabelle[f][0], prezzo, oggi):
                cambiato = True
        if cambiato:
            conta["cambiati"] += 1
            storico.append([oggi, url, testo_prezzo(vecchio), testo_prezzo(prezzo)])
            print(f"  [{n}/{len(urls)}] CAMBIATO {url}: {vecchio:g} -> {prezzo:g} ({metodo})", flush=True)
        else:
            conta["invariati"] += 1

    print(f"letti {conta['letti']} (cambiati {conta['cambiati']}, invariati {conta['invariati']}), "
          f"non letti o saltati {conta['saltati']}, su {len(urls)} indirizzi")
    if a.solo_controllo:
        print("--solo-controllo: nessun file scritto")
        return
    for f, righe in tabelle.items():
        scrivi_righe(f, righe)
    if not STORICO.exists():
        scrivi_righe(STORICO, [COLONNE_STORICO])
    if storico:
        with open(STORICO, "a", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(storico)
        print(len(storico), "variazioni aggiunte a", STORICO.name)


if __name__ == "__main__":
    main()
