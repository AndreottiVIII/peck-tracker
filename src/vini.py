"""Scarica la carta dei vini dell'Enoteca Peck (Winerim) e scrive data/vini.csv e data/cantine.csv.

Uso:  python -I src/vini.py [--pausa SECONDI] [--forza]

- La carta e' incorporata in https://peck.it/enoteca/ da https://web.winerim.com/enotecapeck ;
  i dati vengono da un'API JSON pubblica, senza autenticazione.
- Una richiesta alla volta, con pausa fra l'una e l'altra (default 2 secondi).
- Le pagine gia' scaricate in data/raw/winerim/ vengono saltate (--forza per riscaricarle).
- Non salviamo foto ne' testi descrittivi: solo i dati strutturati (attributi di degustazione da 0 a 5,
  gradazione, temperatura di servizio, finestra di maturita', abbinamenti).
- Con --dettagli scarica anche la scheda di ogni vino (una richiesta al secondo) in
  data/raw/winerim/vini/<id>.json: servono per i dati strutturati sopra. I testi lunghi che ci sono
  nelle schede (note di degustazione, storia della cantina) restano in data/raw/ (non pubblicata) e
  NON vanno copiati nel sito ne' nei CSV.
"""
import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests

ID = "4065fdbc-fb41-47d4-878a-6c98f5828c46"
API = f"https://app.winerim.com/api/v1/restaurant/{ID}"
LIMITE = 100
DATA = Path(__file__).resolve().parent.parent / "data"
RAW = DATA / "raw" / "winerim"
HEAD = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Origin": "https://web.winerim.com",
    "Referer": "https://web.winerim.com/",
    "Accept-Language": "it-IT,it;q=0.9",
}

TIPI = {  # tipo spagnolo di Winerim -> italiano
    "tinto": "rosso", "blanco": "bianco", "espumoso": "spumante", "postre": "dolce",
    "fortificado": "liquoroso/fortificato", "rosado": "rosato",
}
PAESI = {  # codice ISO -> nome italiano (solo quelli che compaiono nella carta)
    "IT": "Italia", "FR": "Francia", "ES": "Spagna", "DE": "Germania", "AT": "Austria",
    "PT": "Portogallo", "US": "Stati Uniti", "AU": "Australia", "NZ": "Nuova Zelanda",
    "AR": "Argentina", "CL": "Cile", "ZA": "Sudafrica", "GB": "Regno Unito", "CH": "Svizzera",
    "HU": "Ungheria", "GR": "Grecia", "SI": "Slovenia", "HR": "Croazia", "LB": "Libano",
    "GE": "Georgia", "BR": "Brasile", "UY": "Uruguay", "CA": "Canada", "LU": "Lussemburgo",
    "IL": "Israele", "RO": "Romania", "BG": "Bulgaria", "MD": "Moldavia", "CZ": "Cechia",
    "SK": "Slovacchia", "MX": "Messico", "CN": "Cina", "JP": "Giappone", "TR": "Turchia",
}


def scarica(forza, pausa):
    """Scarica tutte le pagine dell'elenco vini; restituisce la lista dei file."""
    RAW.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(HEAD)
    ultima = 0.0
    file, pagina, pagine = [], 1, None
    while pagine is None or pagina <= pagine:
        f = RAW / f"vini_p{pagina:03d}.json"
        if not f.exists() or forza:
            attesa = pausa - (time.time() - ultima)
            if attesa > 0:
                time.sleep(attesa)
            r = s.get(f"{API}/wines", params={"page": pagina, "limit": LIMITE}, timeout=60)
            ultima = time.time()
            r.raise_for_status()
            f.write_bytes(r.content)
            print("scaricata pagina", pagina, flush=True)
        if pagine is None:
            d = json.loads(f.read_text(encoding="utf-8"))
            pagine = -(-d["count"] // LIMITE)
        file.append(f)
        pagina += 1
    # i filtri (conteggi del sito) servono solo per il controllo dei totali
    f = RAW / "filtri.json"
    if not f.exists() or forza:
        time.sleep(pausa)
        r = s.get(f"{API}/filters", timeout=60)
        r.raise_for_status()
        f.write_bytes(r.content)
    return file


def scarica_dettagli(vini, pausa):
    """Scarica la scheda di ogni vino in data/raw/winerim/vini/<id>.json (salta quelle gia' scaricate)."""
    cartella = RAW / "vini"
    cartella.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    sess.headers.update(HEAD)
    ultima, nuovi, errori = 0.0, 0, []
    for i, w in enumerate(vini, 1):
        f = cartella / f"{w['id']}.json"
        if f.exists():
            continue
        for tentativo in (1, 2):
            attesa = pausa - (time.time() - ultima)
            if attesa > 0:
                time.sleep(attesa)
            try:
                r = sess.get(f"{API}/wines/{w['id']}/{w['slugname']}", timeout=60)
                ultima = time.time()
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    f.write_bytes(r.content)
                    nuovi += 1
                    break
                errore = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                ultima = time.time()
                errore = type(e).__name__
            if tentativo == 2:
                errori.append((w["id"], errore))
        if nuovi and nuovi % 100 == 0:
            print(f"  schede scaricate: {nuovi} (vino {i}/{len(vini)})", flush=True)
    print(f"schede dei vini: {nuovi} nuove, {len(errori)} con errore", errori[:10], flush=True)


# Abbinamenti: i nomi di Winerim sono in spagnolo, li mettiamo in italiano.
ABBINAMENTI = {
    "carne-ternera": "manzo e vitello", "carne-ternera-lechal": "vitello da latte",
    "carne-cordero": "agnello", "carne-caza": "selvaggina", "carne-aves": "pollame",
    "carne-cerdo": "maiale", "carne-adobada": "carne marinata", "carne-conejo": "coniglio",
    "carne-pato": "anatra", "carne-embutidos": "salumi", "carne-jamon": "prosciutto",
    "queso-curado": "formaggi stagionati", "queso-azul": "formaggi erborinati",
    "queso-tierno-y-cremoso": "formaggi freschi e cremosi", "queso": "formaggi",
    "vegetariana": "piatti vegetariani", "champiñones": "funghi", "arroz": "riso", "pasta": "pasta",
    "pescado-azul": "pesce azzurro", "pescado-blanco": "pesce bianco", "marisco": "crostacei e molluschi",
    "fruta": "frutta", "aperitivos": "aperitivo", "postre": "dessert", "postres": "dessert",
    "ensalada": "insalate", "verduras": "verdure", "huevos": "uova", "sushi": "sushi",
    "queso-de-cabra": "formaggi di capra", "picante": "piatti piccanti", "postres-dulces": "dessert",
    "cocido": "stufati", "foie": "foie gras", "chocolate": "cioccolato", "frutos-secos": "frutta secca",
}


def abbinamento_it(nome):
    return ABBINAMENTI.get(nome, nome)


def dettaglio(wid):
    """Campi strutturali della scheda scaricata (o {} se manca). Nessun testo descrittivo."""
    f = RAW / "vini" / f"{wid}.json"
    if not f.exists():
        return {}
    j = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    alc = (j.get("wineDetails") or {}).get("alcohol")
    if isinstance(alc, (int, float)) and alc > 0:
        out["gradazione"] = f"{alc / 10:g}"   # Winerim lo scrive in decimi: 135 = 13,5%
    t = (j.get("wineDetails") or {}).get("serviceTemperature")
    if t:
        out["temperatura_servizio"] = str(t)
    fin = j.get("drinkingWindow") or {}
    for chiave, sotto, col in (("drinkingWindow", "start", "bere_da"), ("drinkingWindow", "end", "bere_fino_a"),
                               ("primeWindow", "start", "picco_da"), ("primeWindow", "end", "picco_a")):
        v = (fin.get(chiave) or {}).get(sotto)
        if v:
            out[col] = str(v)
    ab = [abbinamento_it(p["name"]) for p in (j.get("pairings") or []) if p.get("name")]
    if ab:
        out["abbinamenti"] = "; ".join(dict.fromkeys(ab))
    return out


VARIANTI = {  # formato di Winerim -> italiano
    "botella": "bottiglia", "media-botella": "mezza bottiglia", "botella-pequena": "bottiglia piccola",
    "magnum": "magnum", "doble-magnum": "doppio magnum", "jeroboam": "jeroboam",
    "rehoboham": "rehoboam", "matusalem": "matusalemme", "salmanzar": "salmanazar",
    "baltasar": "baldassarre", "nabucodonosor": "nabucodonosor", "melchor": "melchiorre",
    "copa": "calice",
}


def norm(s):
    """Chiave per riconoscere lo stesso nome scritto con maiuscole, spazi, accenti o punteggiatura diversi."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def pulisci(s):
    return re.sub(r"\s+", " ", s or "").strip()


def uve(lista):
    """Le uve sono una lista di nomi; in qualche vino (43) e' una lista dentro la lista."""
    out = []
    for g in lista or []:
        out.extend(uve(g) if isinstance(g, list) else [pulisci(g)])
    return out


def leggi():
    """Tutti i vini scaricati, senza doppioni."""
    vini, visti = [], set()
    for f in sorted(RAW.glob("vini_p*.json")):
        for w in json.loads(f.read_text(encoding="utf-8"))["results"]:
            if w["id"] not in visti:
                visti.add(w["id"])
                vini.append(w)
    return vini


def scrivi_csv(percorso, colonne, righe):
    with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colonne)
        w.writeheader()
        w.writerows(righe)


def numero(x):
    """Prezzo come numero: '80' o '1.250,50' non compaiono, ma restiamo prudenti."""
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def costruisci(vini):
    # nomi delle cantine: raggruppati per chiave normalizzata, vince la scrittura piu' frequente
    scritture = defaultdict(lambda: defaultdict(int))
    for w in vini:
        scritture[norm(w["winery"])][pulisci(w["winery"])] += 1
    nome_cantina = {k: max(v.items(), key=lambda x: (x[1], x[0]))[0] for k, v in scritture.items()}

    righe = []
    for w in vini:
        paese = w["country"] or ""
        cant = nome_cantina[norm(w["winery"])]
        base = {
            "id": w["id"], "nome": pulisci(w["name"]), "annata": w["vintage"] or "",
            "tipo": TIPI.get(w["type"], w["type"] or ""),
            "codice_paese": paese, "paese": PAESI.get(paese, paese),
            "regione": pulisci(w["region"]), "cantina": cant,
            "uve": "; ".join(uve(w["grapes"])),
            "link": f"https://web.winerim.com/enotecapeck/wines/{w['id']}/{w['slugname']}",
        }
        ta = w.get("tastingAttributes") or {}
        for k, col in ATTRIBUTI.items():
            base[col] = "" if ta.get(k) is None else ta[k]
        for col in COL_VINI[COL_VINI.index("gradazione"):]:
            base.setdefault(col, "")
        base.update(dettaglio(w["id"]))
        prezzi = w["prices"] or [None]  # un vino senza prezzo resta con una riga
        for p in prezzi:
            r = dict(base)
            if p is None:
                r.update(formato="", variante="", prezzo_euro="", in_stock="no", nota="senza prezzo nella carta")
            else:
                stock = p.get("stock") or 0
                r.update(
                    formato=p.get("capacity") or "",
                    variante=VARIANTI.get(p["variant"], p["variant"]),
                    prezzo_euro=p["price"],
                    in_stock="si" if (stock > 0 and not w["soldout"]) else "no",
                    nota="prezzo al calice" if p["variant"] == "copa" else "",
                )
            righe.append(r)
    return righe, nome_cantina


COL_VINI = ["id", "nome", "annata", "tipo", "codice_paese", "paese", "regione", "cantina", "uve",
            "formato", "variante", "prezzo_euro", "in_stock", "link", "nota",
            "intensita", "freschezza", "dolcezza", "tannicita", "fruttato", "affinamento",
            "gradazione", "temperatura_servizio", "bere_da", "bere_fino_a", "picco_da", "picco_a",
            "abbinamenti"]
# attributi di degustazione di Winerim (0-5) -> colonna italiana
ATTRIBUTI = {"power": "intensita", "acidity": "freschezza", "sweetness": "dolcezza",
             "tannin": "tannicita", "fruity": "fruttato", "aging": "affinamento"}
COL_CANTINE = ["cantina", "paese", "regioni", "n_etichette", "n_rossi", "n_bianchi", "n_spumanti",
               "n_dolci", "n_rosati", "n_liquorosi", "prezzo_min", "prezzo_max", "nota"]


def cantine(vini, nome_cantina):
    gruppi = defaultdict(list)
    for w in vini:
        gruppi[nome_cantina[norm(w["winery"])]].append(w)
    righe = []
    for nome, ws in sorted(gruppi.items(), key=lambda x: (-len(x[1]), x[0])):
        varianti = sorted({pulisci(w["winery"]) for w in ws} - {nome})
        prezzi = [numero(p["price"]) for w in ws for p in w["prices"]]
        prezzi = [x for x in prezzi if x]
        t = defaultdict(int)
        for w in ws:
            t[w["type"]] += 1
        righe.append({
            "cantina": nome,
            "paese": "; ".join(sorted({PAESI.get(w["country"], w["country"]) for w in ws})),
            "regioni": "; ".join(sorted({pulisci(w["region"]) for w in ws})),
            "n_etichette": len(ws),
            "n_rossi": t["tinto"], "n_bianchi": t["blanco"], "n_spumanti": t["espumoso"],
            "n_dolci": t["postre"], "n_rosati": t["rosado"], "n_liquorosi": t["fortificado"],
            "prezzo_min": f"{min(prezzi):g}" if prezzi else "",
            "prezzo_max": f"{max(prezzi):g}" if prezzi else "",
            "nota": ("scritture unite: " + " | ".join(varianti)) if varianti else "",
        })
    return righe


def controllo(vini, righe_c):
    """Confronta i totali con i numeri dell'intestazione del sito (file filtri.json)."""
    f = json.loads((RAW / "filtri.json").read_text(encoding="utf-8"))
    print("\nTOTALI (carta scaricata  |  intestazione del sito)")
    print("vini nell'elenco:", len(vini))
    print("cantine:", len(righe_c), "|", len(f["wineries"]))
    print("paesi:", len({w["country"] for w in vini}), "|", len(f["countries"]))
    print("regioni:", len({pulisci(w["region"]) for w in vini}), "|", len(f["regions"]))
    c = defaultdict(int)
    for w in vini:
        c[w["type"]] += 1
    for t in f["types"]:
        print(f"{TIPI.get(t['name'], t['name'])}: {c[t['name']]} | {t['count']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--forza", action="store_true")
    ap.add_argument("--dettagli", action="store_true",
                    help="scarica anche la scheda di ogni vino (1 richiesta al secondo, circa un'ora)")
    ap.add_argument("--pausa-dettagli", type=float, default=1.0)
    a = ap.parse_args()
    scarica(a.forza, a.pausa)
    vini = leggi()
    if a.dettagli:
        scarica_dettagli(vini, a.pausa_dettagli)
    righe, nome_cantina = costruisci(vini)
    scrivi_csv(DATA / "vini.csv", COL_VINI, righe)
    rc = cantine(vini, nome_cantina)
    scrivi_csv(DATA / "cantine.csv", COL_CANTINE, rc)
    print(len(righe), "righe in vini.csv;", len(rc), "cantine in cantine.csv")
    controllo(vini, rc)


if __name__ == "__main__":
    main()
