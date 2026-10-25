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
- Formato (colonne `litri` e `formato_nome` di vini.csv): vedi litri_riga() e nome_formato(). Nomi: 3 L =
  "Jeroboam" (Champagne e resto del mondo) ma "Doppio Magnum" a Bordeaux; 4,5 L = "Rehoboam"; 5 L = "Rehoboam (5 L)"
  (cosi' lo chiama la carta); 6 L = "Mathusalem" ("Impériale" a Bordeaux). Il numero di `litri` e' quello certo:
  i nomi cambiano da regione a regione.
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


# ----------------------------------------------------------------------------------------------
# Formato in litri (colonne `litri` e `formato_nome` di vini.csv)
# Fonti usate e come si risolvono i disaccordi:
#   1. variante di Winerim (botella, magnum, jeroboam...): volume nominale. Ma "doble-magnum", "jeroboam" e
#      "matusalem" sono contenitori generici della carta (un "matusalem" puo' essere 5 o 6 L, un "jeroboam"
#      3 o 6 L) e "botella-pequena" e' 500 ml per Winerim anche quando la carta scrive 37,5 cl;
#   2. capacita' del prezzo (750ml, 1500ml, 375ml, 500ml): e' un menu a tendina, mai un volume libero;
#   3. scheda del vino (data/raw/winerim/vini/): stessi prezzi della lista, serve solo se la lista non ha
#      la capacita' (nei dati attuali non aggiunge nulla);
#   4. testo scritto a mano nel nome o nel sottotitolo ("Magnum 1,5 LT", "37,5 cl", "Bottiglia 1 LT", "5L"):
#      un litraggio scritto con le cifre vince sulla capacita' (es. Radikon da 1 L registrato come "magnum").
# Se il testo indica un formato diverso da quello di una riga ma un'altra riga della stessa etichetta ha
# proprio quel formato (tipico: riga 750 ml a prezzo 0 accanto al magnum), la riga tiene il suo formato.
VAR_LITRI = {  # volume nominale delle varianti di Winerim
    "botella": 0.75, "media-botella": 0.375, "magnum": 1.5, "doble-magnum": 3.0, "jeroboam": 3.0,
    "rehoboham": 4.5, "matusalem": 6.0, "salmanzar": 9.0, "baltasar": 12.0, "nabucodonosor": 15.0,
    "melchor": 18.0,
}
VARIANTI_REALI = {"botella", "magnum"}  # qui la capacita' e' un dato vero, non il segnaposto di un contenitore
PAROLE_FORMATO = [  # (regex sul testo in minuscolo, litri)
    (r"doppio magnum|double magnum", 3.0),
    (r"jeroa?boam", 3.0),
    (r"magnum", 1.5),
    (r"rehoboam", 4.5),
    (r"mathusalem|matusalem|methuselah", 6.0),
    (r"salmanazar", 9.0),
    (r"balth?azar", 12.0),
    (r"nabu?chodonosor", 15.0),
    (r"melchior", 18.0),
    (r"mezza bottiglia", 0.375),
]
RE_LITRI = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?(cl|ml|litri|lt|l)\b", re.I)
RE_LITRI_NUDO = re.compile(r"(?:^|[\s-])(0[.,]\d{1,3})\s*$")  # sottotitolo "2023 - 0,375"
BORDEAUX = {"bordeaux", "medoc", "pauillac", "margaux", "saint estephe", "saint julien", "saint emilion",
            "pomerol", "sauternes", "graves", "pessac leognan"}


def numero_pulito(x):
    return float(x.replace(",", "."))


def litri_da_testo(testo):
    """(litri scritti con le cifre, litri dalla sola parola del formato) cercati nel nome e nel sottotitolo."""
    t = testo or ""
    esplicito = None
    for m in RE_LITRI.finditer(t):
        v = numero_pulito(m.group(1))
        u = m.group(2).lower()
        v = v / 100 if u == "cl" else v / 1000 if u == "ml" else v
        if 0.1 <= v <= 30:
            esplicito = round(v, 4)
            break
    if esplicito is None:
        m = RE_LITRI_NUDO.search(t)
        if m:
            esplicito = round(numero_pulito(m.group(1)), 4)
    parola = None
    for pat, litri in PAROLE_FORMATO:
        if re.search(pat, t.lower()):
            parola = litri
            break
    return esplicito, parola


def bottiglie_del_set(w):
    """Numero di bottiglie se la voce e' una cassa/set di piu' bottiglie, altrimenti None."""
    sotto = w.get("subname") or ""
    n = sum(int(x) for x in re.findall(r"\((\d+)\s?bts?\)", sotto))
    if n > 1:
        return n
    if re.fullmatch(r"\d{4}(\+\d{4})+", sotto.strip()):
        return len(sotto.split("+"))
    return None


def capacita_litri(testo):
    m = re.match(r"(\d+)ml$", testo or "")
    return int(m.group(1)) / 1000 if m else None


def capacita_scheda(w, p):
    """Capacita' dello stesso prezzo letta dalla scheda del vino, per quando la lista non la dice."""
    f = RAW / "vini" / f"{w['id']}.json"
    if not f.exists():
        return None
    for q in json.loads(f.read_text(encoding="utf-8")).get("prices") or []:
        if q.get("id") == p.get("id"):
            return capacita_litri(q.get("capacity"))
    return None


def g(x):
    return f"{x:g}"


def litri_riga(w, p, altri):
    """Formato di una riga prezzo (p e' None per un vino senza prezzo): (litri o None, fonte, nota).
    `altri` = capacita' in litri delle altre righe prezzo dello stesso vino."""
    esplicito, parola = litri_da_testo(pulisci(w.get("name")) + " | " + pulisci(w.get("subname")))
    t = esplicito if esplicito is not None else parola
    n_set = bottiglie_del_set(w)
    if n_set:
        unit = capacita_litri(p.get("capacity")) if p else None
        return round(n_set * (unit or 0.75), 4), "set", (
            f"set di {n_set} bottiglie" + ("" if unit else ", bottiglie assunte da 750 ml"))
    if p is None:
        if t is not None:
            return t, "testo", ""
        return None, "ignoto", "formato sconosciuto: prezzo non pubblicato e nessuna indicazione nel nome"
    var = p["variant"]
    if var == "copa":
        return None, "variante", "calice: volume non indicato"
    cap, f_cap = capacita_litri(p.get("capacity")), "capacità"
    if cap is None:
        cap, f_cap = capacita_scheda(w, p), "scheda"
    nom = VAR_LITRI.get(var)
    note = ["riga a prezzo 0 (segnaposto)"] if str(p.get("price")) in ("0", "0.0") else []
    if t is not None:
        if var in VARIANTI_REALI and cap is not None and abs(t - cap) > 1e-6 and any(abs(t - a) < 1e-6 for a in altri):
            note.append(f"il testo ({g(t)} L) riguarda l'altro formato della stessa etichetta")
            return cap, f_cap, "; ".join(note)
        fonti = ["testo"]
        if cap is not None and abs(cap - t) < 1e-6:
            fonti.append(f_cap)
        if nom is not None and abs(nom - t) < 1e-6:
            fonti.append("variante")
        if cap is not None and abs(cap - t) > 1e-6:
            note.append(f"capacità {g(cap)} L ≠ testo {g(t)} L: vale il testo")
        elif nom is not None and abs(nom - t) > 1e-6:
            note.append(f"variante Winerim «{var}» ({g(nom)} L) ≠ testo {g(t)} L: vale il testo")
        return t, "+".join(fonti), "; ".join(note)
    if cap is not None:
        fonti = [f_cap]
        if nom is not None and abs(nom - cap) < 1e-6:
            fonti.append("variante")
        elif nom is not None:
            note.append(f"capacità {g(cap)} L ≠ variante «{var}» ({g(nom)} L): vale la capacità")
        return cap, "+".join(fonti), "; ".join(note)
    if nom is not None:
        return nom, "variante", "; ".join(note)
    return None, "ignoto", "; ".join(note + ["formato sconosciuto"])


def nome_formato(litri, regione, tipo_riga):
    """Nome del formato. 3 L: Jeroboam, ma Doppio Magnum a Bordeaux; 6 L: Mathusalem, Impériale a Bordeaux."""
    if tipo_riga == "calice":
        return "Calice"
    if tipo_riga == "set":
        return "Set / cassa"
    if litri is None:
        return ""
    bordeaux = norm(regione) in BORDEAUX
    nomi = {0.1875: "Piccolo (18,75 cl)", 0.375: "Mezza bottiglia (37,5 cl)", 0.5: "Bottiglia da 50 cl",
            0.75: "Bottiglia", 1.0: "Bottiglia da 1 litro", 1.5: "Magnum",
            3.0: "Doppio Magnum" if bordeaux else "Jeroboam", 4.5: "Rehoboam", 5.0: "Rehoboam (5 L)",
            6.0: "Impériale" if bordeaux else "Mathusalem", 9.0: "Salmanazar", 12.0: "Balthazar",
            15.0: "Nabuchodonosor", 18.0: "Melchior"}
    return nomi.get(round(litri, 4), f"Formato speciale ({g(litri)} L)")


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
            altri = [capacita_litri(q.get("capacity")) for q in prezzi
                     if q is not None and q is not p and q["variant"] in VARIANTI_REALI]
            litri, fonte, nota_f = litri_riga(w, p, [a for a in altri if a])
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
            tipo_riga = "calice" if p and p["variant"] == "copa" else "set" if fonte == "set" else ""
            r["litri"] = g(litri) if litri is not None else ""
            r["formato_nome"] = nome_formato(litri, w["region"], tipo_riga)
            r["nota"] = "; ".join(x for x in [r["nota"], f"formato da: {fonte}" if litri is not None else "", nota_f] if x)
            righe.append(r)
    return righe, nome_cantina


COL_VINI = ["id", "nome", "annata", "tipo", "codice_paese", "paese", "regione", "cantina", "uve",
            "formato", "variante", "litri", "formato_nome", "prezzo_euro", "in_stock", "link", "nota",
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


COL_FORMATI = ["litri", "formato_nome", "righe_vino", "prezzo_min", "prezzo_max"]


def formati(righe):
    """Riepilogo per formato: quante righe di vini.csv e prezzo minimo/massimo (le righe a prezzo 0 non contano)."""
    gruppi = defaultdict(list)
    for r in righe:
        gruppi[(r["litri"], r["formato_nome"] or "(formato sconosciuto)")].append(r)
    out = []
    for (litri, nome), rs in sorted(gruppi.items(), key=lambda x: (x[0][0] == "", float(x[0][0] or 0), x[0][1])):
        prezzi = [numero(r["prezzo_euro"]) for r in rs]
        prezzi = [x for x in prezzi if x]
        out.append({"litri": litri, "formato_nome": nome, "righe_vino": len(rs),
                    "prezzo_min": f"{min(prezzi):g}" if prezzi else "",
                    "prezzo_max": f"{max(prezzi):g}" if prezzi else ""})
    return out


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
    rf = formati(righe)
    scrivi_csv(DATA / "formati.csv", COL_FORMATI, rf)
    print(len(righe), "righe in vini.csv;", len(rc), "cantine in cantine.csv;", len(rf), "formati in formati.csv")
    controllo(vini, rc)


if __name__ == "__main__":
    main()
