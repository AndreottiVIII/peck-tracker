"""Voti da dataset aperti: abbina i vini della carta Peck ai voti di due raccolte con licenza libera.

    python -I src/voti_aperti.py scarica      # scarica i dati grezzi in data/raw/voti/ (salta quelli gia' presenti)
    python -I src/voti_aperti.py abbina       # scrive data/voti_aperti.csv
    python -I src/voti_aperti.py verifica [N] [fonte] [livelli,separati,da,virgola]  # N abbinamenti a caso da controllare

Fonti:
  - Wine Enthusiast "Wine Reviews" (winemag-data-130k-v2, 129.971 recensioni 2017 coi punti 80-100).
    Raccolta di Zack Thoutt su Kaggle, licenza CC BY-NC-SA 4.0 (non commerciale, stessa licenza,
    citare la fonte). Copia usata: GitHub jgobi/wine-reviews (3 file). Si tiene SOLO il punteggio
    e il nome del degustatore: le descrizioni (testo di Wine Enthusiast) non si leggono ne' si copiano.
  - X-Wines (de Azambuja, Morais, Filipe, 2023; Big Data Cogn. Comput. 7(1), 20), licenza CC0,
    100.646 vini e 21 milioni di voti a stelle (1-5) di utenti, 2012-2021. Si fa la media per vino
    e annata, solo con almeno 10 voti.

L'abbinamento riusa la normalizzazione di src/tannico.py (cantina + nome + annata) ed e' prudente:
un vino con la cantina o il nome diversi non si abbina. Paese diverso = nessun abbinamento.
"""
import csv
import io
import random
import re
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tannico as T  # noqa: E402  (stessa normalizzazione dell'abbinamento Tannico)

RADICE = Path(__file__).resolve().parent.parent
RAW = RADICE / "data" / "raw" / "voti"
VINI = RADICE / "data" / "vini.csv"
USCITA = RADICE / "data" / "voti_aperti.csv"
USCITA_DUBBI = RADICE / "data" / "voti_aperti_da_controllare.csv"  # abbinamenti incerti: NON si usano sul sito

WE_DIR = RAW / "wine_enthusiast"
WE_URL = "https://raw.githubusercontent.com/jgobi/wine-reviews/HEAD/winemag-data-130k-v2-p{n}.csv"
WE_LICENZA = "CC BY-NC-SA 4.0 (Wine Enthusiast via Kaggle, Z. Thoutt)"

XW_DIR = RAW / "xwines"
XW_VINI = XW_DIR / "XWines_Full_100K_wines.csv"
XW_ZIP = XW_DIR / "XWines_Full_21M_ratings.zip"
XW_AGG = XW_DIR / "ratings_per_vintage.csv"
XW_LICENZA = "CC0 (X-Wines, de Azambuja et al. 2023)"
XW_MIN_VOTI = 10

# Google Drive (cartella ufficiale di X-Wines): servono i due file sotto. Su Drive i file grandi
# chiedono una conferma che urllib non gestisce: si usa il pacchetto gdown, se c'e'.
XW_DRIVE = {XW_VINI.name: "1uEEipmKNxdiKUAhjH-K14JOSQ2BLRFss",
            XW_ZIP.name: "1tI-3XOoD4w_hYMGgj6OXU3EUI8xMQgj2"}

PAESI_WE = {"France": "FR", "Italy": "IT", "Spain": "ES", "US": "US", "Portugal": "PT", "Germany": "DE",
            "Austria": "AT", "Australia": "AU", "New Zealand": "NZ", "Argentina": "AR", "Chile": "CL",
            "South Africa": "ZA", "Israel": "IL", "Slovenia": "SI", "Greece": "GR", "Hungary": "HU",
            "Switzerland": "CH", "Lebanon": "LB"}
MAX_DISTANZA_ANNATA = 3   # oltre, il voto di un'altra annata non si usa
SOGLIA_DA_CONTROLLARE = 0.6

# Parole che si possono ignorare quando stanno SOLO da una parte (denominazioni larghe, vitigni, descrizioni).
# Tutto il resto del nome (cru, vigne, cuvee, numeri, "late bottled", "barrel sample"...) deve coincidere.
# I nomi di cru borgognoni (chambertin, montrachet, charlemagne, echezeaux...) NON sono qui apposta.
SICURE = set("""champagne franciacorta trento langhe bolgheri toscana barbaresco asti alba montalcino montepulciano
pessac leognan graves saint emilion pauillac sauternes barsac vouvray alsace saumur champigny jura cotes
douro rioja ribera duero rias baixas marlborough otago central willamette valley marche veneto maremma
etna port madeira vin santo classe sparkling red white single vineyard selection estate
chardonnay sauvignon merlot nebbiolo barbera malbec godello albarino gialla pinot nero cabernet syrah
sangiovese grenache tempranillo riesling""".split())

CAMPI = ["id", "fonte", "critico/rivista", "voto", "scala", "annata_fonte", "corrispondenza",
         "punteggio_abbinamento", "licenza"]


# ---------------------------------------------------------------- scarico
def scarica():
    WE_DIR.mkdir(parents=True, exist_ok=True)
    XW_DIR.mkdir(parents=True, exist_ok=True)
    for n in (1, 2, 3):
        f = WE_DIR / f"p{n}.csv"
        if f.exists():
            continue
        print("scarico", f.name)
        rich = urllib.request.Request(WE_URL.format(n=n), headers={"User-Agent": T.UA})
        with urllib.request.urlopen(rich, timeout=120) as r:
            f.write_bytes(r.read())
    if XW_AGG.exists() and XW_VINI.exists():
        return
    try:
        import gdown
    except ImportError:
        raise SystemExit("per X-Wines serve gdown (pip install gdown), oppure scarica a mano da "
                         "https://drive.google.com/drive/folders/1LqguJNV-aKh1PuWMVx5ELA61LPfGfuu_ "
                         "i file " + ", ".join(XW_DRIVE) + " in " + str(XW_DIR))
    for nome, id_ in XW_DRIVE.items():
        dest = XW_DIR / nome
        if dest.exists() or (nome == XW_ZIP.name and XW_AGG.exists()):
            continue
        print("scarico", nome)
        gdown.download(id=id_, output=str(dest), quiet=True)
    aggrega_xwines()


def aggrega_xwines():
    """21 milioni di voti -> media e numero per (vino, annata). Tiene solo i numeri."""
    if XW_AGG.exists():
        return
    somma = defaultdict(lambda: [0.0, 0])
    with zipfile.ZipFile(XW_ZIP) as z, z.open("XWines_Full_21M_ratings.csv") as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline="")):
            s = somma[(r["WineID"], r["Vintage"])]
            s[0] += float(r["Rating"])
            s[1] += 1
    with open(XW_AGG, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["WineID", "Vintage", "mean", "count"])
        for (wid, vint), (s, n) in somma.items():
            w.writerow([wid, vint, round(s / n, 4), n])
    print("aggregati", len(somma), "vino/annata")


# ---------------------------------------------------------------- candidati
class Cand:
    """Un vino di una fonte, con gli attributi che T.confronta si aspetta (come T.Prodotto)."""

    def __init__(self, cantina, vino, anno, paese, voti):
        self.casa = cantina
        self.vino = vino
        self.anno = anno           # '' se manca; 'NV' per i senza annata
        self.paese = paese
        self.voti = voti           # lista di (critico, voto, scala, extra)
        self.t_vino = T.tokens(vino)
        self.t_casa = T.tokens(cantina)
        self.t_casa_dist = {w for w in self.t_casa if w not in T.CANTINA_GENERICA}
        t = self.t_casa_dist or self.t_casa
        self.gruppi = [t] if t else []
        self.formato = 750


def anno_da_titolo(s):
    m = re.search(r"\b((?:19|20)\d\d)\b", s)
    return m.group(1) if m else ("NV" if re.search(r"\bN\.?V\.?\b", s) else "")


def carica_we():
    """Wine Enthusiast: una Cand per (cantina, titolo, annata); i voti dei diversi degustatori si raccolgono."""
    gruppi = {}
    for n in (1, 2, 3):
        with open(WE_DIR / f"p{n}.csv", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    punti = int(r["points"])
                except ValueError:
                    continue
                cantina, titolo = r["winery"].strip(), r["title"].strip()
                if not cantina:
                    continue
                anno = anno_da_titolo(titolo)
                # nome del vino: il titolo senza cantina e senza annata (la denominazione tra parentesi resta)
                vino = titolo
                if titolo.lower().startswith(cantina.lower()):
                    vino = titolo[len(cantina):]
                vino = re.sub(r"\b((?:19|20)\d\d|NV)\b", " ", vino)
                paese = PAESI_WE.get(r["country"], "")
                chiave = (cantina, vino.strip(), anno, paese)
                g = gruppi.setdefault(chiave, [])
                g.append((r["taster_name"].strip() or "Wine Enthusiast", punti))
    cands = []
    for (cantina, vino, anno, paese), lst in gruppi.items():
        per = defaultdict(list)
        for nome, p in lst:
            per[nome].append(p)
        voti = [(nome, round(sum(v) / len(v), 1) if len(v) > 1 else v[0], "100", "") for nome, v in per.items()]
        cands.append(Cand(cantina, vino, anno, paese, voti))
    return cands


def carica_xwines():
    agg = defaultdict(dict)
    with open(XW_AGG, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if int(r["count"]) >= XW_MIN_VOTI:
                agg[r["WineID"]][r["Vintage"]] = (float(r["mean"]), int(r["count"]))
    cands = []
    with open(XW_VINI, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            vint = agg.get(r["WineID"])
            if not vint:
                continue
            for anno, (media, n) in vint.items():
                a = "NV" if anno in ("N.V.", "NV") else anno
                voti = [(f"Utenti X-Wines (n={n})", round(media, 2), "5", "")]
                cands.append(Cand(r["WineryName"], r["WineName"], a, r["Code"], voti))
    return cands


# ---------------------------------------------------------------- abbinamento
def indicizza(cands):
    idx = defaultdict(list)
    for c in cands:
        for w in c.t_casa_dist or c.t_casa:
            idx[w].append(c)
    return idx


def nucleo_stretto(nome, cantine_tok):
    """Parole del nome che identificano davvero il vino, e parole ignorabili (denominazioni, vitigni)."""
    t = {w for w in T.tokens(nome) - cantine_tok if len(w) > 1 and w not in T.PAROLE_VUOTE}
    ign = {w for w in t if w in SICURE or w in T.REGIONI or w in T.CANTINA_GENERICA}
    return t - ign, ign


def stesso_vino(v, c, tc_alt):
    """Controllo rigido dopo T.confronta: il nome (tolta la cantina) deve coincidere parola per parola,
    salvo denominazioni/vitigni presenti solo da una parte. Evita Charmes-Chambertin / Chambertin,
    Echezeaux / Romanee-Conti, Vintage Port / Late Bottled Vintage, cuvee diverse della stessa cantina."""
    togli = set().union(*tc_alt) | c.t_casa
    np_, ip = nucleo_stretto(v["nome"], togli)
    nf, i_f = nucleo_stretto(c.vino, togli)
    if np_ != nf:
        return False
    return ip <= i_f or i_f <= ip


def distanza(a, b):
    if a == b:
        return 0
    if a.isdigit() and b.isdigit():
        return abs(int(a) - int(b))
    return 99


def abbina_fonte(vini, cands, fonte, licenza, voto_fmt):
    idx = indicizza(cands)
    # parole generiche: come in T.frequenze_generiche (token presenti in molte cantine)
    cant = defaultdict(set)
    for c in cands:
        for w in c.t_vino:
            cant[w].add(c.casa)
    generici = {w for w, s in cant.items() if len(s) >= 12 and w not in T.IMPORTANTI}
    uscita = []
    for v in vini:
        tc_alt = T.tok_cantina(v["cantina"])
        cand = {}
        for a in tc_alt:
            for w in a:
                for c in idx.get(w, ()):
                    cand[id(c)] = c
        a_peck = v["annata"] or "NV"
        trovati = []
        for c in cand.values():
            if c.paese and v["codice_paese"] and c.paese != v["codice_paese"]:
                continue
            r = T.confronta(v, tc_alt, c, generici)
            if not r or not stesso_vino(v, c, tc_alt):
                continue
            liv, jac, cant_esatta = r
            d = distanza(a_peck, c.anno)
            if d > MAX_DISTANZA_ANNATA:
                continue
            trovati.append((liv, jac, cant_esatta, d, c))
        if not trovati:
            continue
        # miglior candidato: nome uguale + cantina esatta, poi stessa annata, poi somiglianza
        trovati.sort(key=lambda x: (x[0] == "uguale" and x[2], x[0] == "uguale", x[3] == 0, x[1], -x[3]),
                     reverse=True)
        liv, jac, cant_esatta, d, c = trovati[0]
        # se due candidati pari merito hanno nomi diversi e la stessa annata, e' ambiguo: niente
        pari = [t for t in trovati[1:] if t[0] == liv and t[2] == cant_esatta and t[3] == d
                and abs(t[1] - jac) < 1e-9 and T.tokens(t[4].vino) != T.tokens(c.vino)]
        if pari:
            continue
        punteggio = round(100 * (jac if liv == "simile" else 1.0) * (1 if cant_esatta else 0.8)
                          * (1 if d == 0 else 0.85))
        if liv == "uguale" and cant_esatta and d == 0:
            corr = "esatta"
        elif liv == "uguale" and cant_esatta:
            corr = "annata diversa"
        elif liv == "simile" and jac < SOGLIA_DA_CONTROLLARE:
            continue
        else:
            corr = "da controllare"
        for critico, voto, scala, _ in c.voti:
            uscita.append({"id": v["id"], "fonte": fonte, "critico/rivista": critico,
                           "voto": voto_fmt(voto), "scala": scala, "annata_fonte": c.anno,
                           "corrispondenza": corr, "punteggio_abbinamento": punteggio,
                           "licenza": licenza,
                           # colonne di servizio (non scritte nel csv): per il controllo a mano
                           "_nome_fonte": f"{c.casa} | {c.vino} | {c.anno}"})
    return uscita


def leggi_vini():
    with open(VINI, encoding="utf-8-sig", newline="") as f:
        righe = list(csv.DictReader(f))
    vini = {}
    prezzi = defaultdict(list)
    for r in righe:
        if r["variante"] == "calice":
            continue
        vini.setdefault(r["id"], r)
        try:
            prezzi[r["id"]].append(float(r["prezzo_euro"]))
        except ValueError:
            pass
    return list(vini.values()), {k: min(p) for k, p in prezzi.items() if p}


def abbina():
    vini, prezzo = leggi_vini()
    print(len(vini), "vini Peck")
    tutte = []
    print("Wine Enthusiast...")
    we = carica_we()
    print(" ", len(we), "vini/annate")
    tutte += abbina_fonte(vini, we, "Wine Enthusiast", WE_LICENZA, lambda x: int(round(x)))
    print("X-Wines...")
    aggrega_xwines()
    xw = carica_xwines()
    print(" ", len(xw), "vini/annate con almeno", XW_MIN_VOTI, "voti")
    tutte += abbina_fonte(vini, xw, "X-Wines", XW_LICENZA, lambda x: f"{x:.2f}")
    # i "da controllare" (cantina non identica: Latour / Latour a Pomerol, Leflaive / Olivier Leflaive...)
    # sbagliano una volta su due: stanno in un file a parte, il file principale ha solo esatta e annata diversa
    for dest, righe in ((USCITA, [r for r in tutte if r["corrispondenza"] != "da controllare"]),
                        (USCITA_DUBBI, [r for r in tutte if r["corrispondenza"] == "da controllare"])):
        with open(dest, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, CAMPI, extrasaction="ignore")
            w.writeheader()
            w.writerows(righe)
    (RAW / "_nomi_fonte.tmp").write_text(
        "\n".join(f"{r['id']}\t{r['fonte']}\t{r['_nome_fonte']}" for r in tutte), encoding="utf-8")
    # riepilogo
    for fonte in ("Wine Enthusiast", "X-Wines"):
        for livelli in (("esatta",), ("esatta", "annata diversa"), ("esatta", "annata diversa", "da controllare")):
            ids = {r["id"] for r in tutte if r["fonte"] == fonte and r["corrispondenza"] in livelli}
            sotto = [i for i in ids if prezzo.get(i, 9999) < 200]
            print(f"{fonte:16} {'+'.join(livelli):38} vini {len(ids):4}  sotto 200 euro {len(sotto):4}")
    ids = {r["id"] for r in tutte if r["corrispondenza"] in ("esatta", "annata diversa")}
    print("unione (esatta+annata diversa):", len(ids), "sotto 200:", sum(1 for i in ids if prezzo.get(i, 9999) < 200),
          "su", sum(1 for p in prezzo.values() if p < 200), "vini sotto 200")


def verifica(n=30, fonte=None, livelli=("esatta", "annata diversa", "da controllare")):
    vini = {v["id"]: v for v in leggi_vini()[0]}
    righe = []
    for f_ in (USCITA, USCITA_DUBBI):
        righe += list(csv.DictReader(open(f_, encoding="utf-8-sig", newline="")))
    nomi = {}
    for riga in (RAW / "_nomi_fonte.tmp").read_text(encoding="utf-8").splitlines():
        i, f, n_ = riga.split("\t")
        nomi[(i, f)] = n_
    uniche = {(r["id"], r["fonte"]): r for r in righe
              if (not fonte or r["fonte"].startswith(fonte)) and r["corrispondenza"] in livelli}
    random.seed(11)
    for chiave in random.sample(sorted(uniche), min(n, len(uniche))):
        r = uniche[chiave]
        v = vini[r["id"]]
        cantina_f, vino_f, _ = nomi[chiave].split(" | ")
        togli = T.tokens(v["cantina"]) | T.tokens(cantina_f)
        vp, vf = T.tokens(v["nome"]) - togli, T.tokens(vino_f) - togli
        diff = f"  DIFF solo-Peck={sorted(vp - vf)} solo-fonte={sorted(vf - vp)}" if vp != vf else ""
        print(f"[{r['fonte'][:5]}|{r['corrispondenza']}|{r['punteggio_abbinamento']}] "
              f"PECK: {v['cantina']} | {v['nome']} | {v['annata']}   <->   {nomi[chiave]}   voto {r['voto']}{diff}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scarica":
        scarica()
    elif cmd == "abbina":
        abbina()
    elif cmd == "verifica":
        verifica(int(sys.argv[2]) if len(sys.argv) > 2 else 30,
                 sys.argv[3] if len(sys.argv) > 3 else None,
                 tuple(sys.argv[4].split(",")) if len(sys.argv) > 4 else ("esatta", "annata diversa", "da controllare"))
    else:
        print(__doc__)
