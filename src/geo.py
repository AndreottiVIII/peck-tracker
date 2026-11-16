"""Passo 3: coordinate dei luoghi di produzione, per la mappa dei fornitori di Peck.

Geocodifica con OpenStreetMap Nominatim (https://operations.osmfoundation.org/policies/nominatim/):
  - al massimo 1 richiesta al secondo (qui 1,2 s), User-Agent descrittivo con contatto;
  - ogni risposta (anche "nessun risultato") e' salvata in data/raw/geo/ e non si chiede due volte.

Scrive:
  data/geo.csv              un punto per ogni riga di data/aziende.csv con un luogo noto
  data/geo_regioni_vini.csv un punto per regione vinicola (centro della regione), non per cantina

Uso:  python -I src/geo.py
Precisione: via (strada/civico trovato), comune (solo il centro del comune), regione (centro regione).
Per ogni indirizzo si prova: via+civico -> via senza civico -> testo libero -> centro del comune.
Un risultato e' scartato se il paese o (per l'Italia) la provincia non coincidono con quelli attesi.
"""
import csv, hashlib, json, re, sys, time, unicodedata
from collections import OrderedDict, defaultdict
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import bolli  # noqa: E402  (elenchi TRACES gia' scaricati in data/raw/sintesis/)

CACHE = ROOT / "data" / "raw" / "geo"
URL = "https://nominatim.openstreetmap.org/search"
UA = "peck-tracker (github.com/AndreottiVIII/peck-tracker)"
PAUSA = 1.2
_ultima = [0.0]
_sess = requests.Session()
_sess.headers.update({"User-Agent": UA, "Accept-Language": "it,en"})

ISO = {"Italia": "it", "Spagna": "es", "Germania": "de", "Francia": "fr", "Stati Uniti": "us",
       "Portogallo": "pt", "Austria": "at", "Slovenia": "si", "Australia": "au",
       "Nuova Zelanda": "nz", "Argentina": "ar", "Israele": "il", "Cile": "cl", "Libano": "lb",
       "Romania": "ro", "Cina": "cn", "Grecia": "gr", "Sudafrica": "za", "Ungheria": "hu"}
NOME_EN = {"Italia": "Italy", "Spagna": "Spain", "Germania": "Germany", "Francia": "France",
           "Stati Uniti": "United States"}
# province cambiate nel tempo: (sigla in Peck, sigla OSM oggi)
PROV_EQUIV = {("CA", "SU"), ("VS", "SU"), ("CI", "SU"), ("OT", "SS"), ("OG", "NU")}


def chiedi(**params):
    """Una richiesta a Nominatim, con cache su disco e pausa tra le richieste vere."""
    params.update({"format": "jsonv2", "addressdetails": 1, "limit": 1})
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))["risposta"]
    CACHE.mkdir(parents=True, exist_ok=True)
    attesa = PAUSA - (time.time() - _ultima[0])
    if attesa > 0:
        time.sleep(attesa)
    for tentativo in range(4):
        r = _sess.get(URL, params=params, timeout=60)
        _ultima[0] = time.time()
        if r.status_code == 200:
            break
        time.sleep(10 * (tentativo + 1))
    r.raise_for_status()
    ris = r.json()
    f.write_text(json.dumps({"richiesta": params, "risposta": ris}, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return ris


def _n(t):
    t = unicodedata.normalize("NFD", t.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in t if not unicodedata.combining(c)))


def comune_coincide(h, comune):
    """Il posto trovato sta davvero nel comune cercato? (evita una 'Via Arese' in un altro comune)"""
    a = h.get("address", {})
    c = _n(comune)
    nomi = [_n(a[k]) for k in ("city", "town", "village", "municipality", "hamlet", "suburb",
                               "city_district", "borough", "state") if a.get(k)]
    return not nomi or any(c in n or n in c for n in nomi if n)


def valida(res, paese_iso, prov, comune=""):
    """Prima risposta valida (paese e provincia coerenti) o None."""
    for h in res:
        a = h.get("address", {})
        if paese_iso and a.get("country_code") != paese_iso:
            continue
        if paese_iso == "it" and prov:
            lvl6 = a.get("ISO3166-2-lvl6", "")
            if lvl6 and lvl6[-2:] != prov and (prov, lvl6[-2:]) not in PROV_EQUIV:
                continue
        if comune and not comune_coincide(h, comune):
            continue
        return h
    return None


STRADE = {"road", "residential", "pedestrian", "tertiary", "secondary", "primary", "unclassified",
          "service", "track", "path", "living_street", "trunk", "motorway"}


def e_via(h):
    a = h.get("address", {})
    return h.get("category") in ("highway", "building") or h.get("type") in STRADE | {"house"} \
        or ("road" in a and h.get("category") != "boundary")


def pulisci_via(v):
    v = re.sub(r"^\s*C/\s*", "Calle ", v)
    v = re.sub(r"\b(snc|sns)\b\.?", "", v, flags=re.I)
    return re.sub(r"\s+", " ", v).strip(" ,")


def geocodifica(via, cap, comune, prov, paese):
    """Ritorna (lat, lon, precisione, provincia_osm, nota) o None."""
    iso = ISO.get(paese, "")
    nome_paese = NOME_EN.get(paese, paese)
    via = pulisci_via(via or "")
    senza_civico = re.sub(r"\s+\d+\s*[A-Za-z]?(/\d+)?\s*$", "", via).strip()
    tentativi = []
    if via:
        tentativi.append(("s", dict(street=via, city=comune, country=nome_paese)))
        if senza_civico and senza_civico != via:
            tentativi.append(("s", dict(street=senza_civico, city=comune, country=nome_paese)))
        tentativi.append(("s", dict(street=senza_civico or via, city=comune, postalcode=cap,
                                    country=nome_paese)) if cap else None)
        tentativi.append(("q", dict(q=f"{via}, {comune}" + (f", {prov}" if len(prov or '') == 2 else "")
                                    + f", {nome_paese}")))
    tentativi.append(("c", dict(city=comune, country=nome_paese)))
    if cap and iso != "it":
        tentativi.append(("c", dict(city=comune, postalcode=cap, country=nome_paese)))
    tentativi.append(("c", dict(q=f"{comune}, {prov + ', ' if len(prov or '') == 2 else ''}{nome_paese}")))
    for tipo, p in [t for t in tentativi if t]:
        if iso:
            p = dict(p, countrycodes=iso)
        h = valida(chiedi(**p), iso, prov if len(prov or "") == 2 else "",
                   comune if tipo != "c" and iso == "it" else "")
        if not h:
            continue
        a = h.get("address", {})
        lvl6 = a.get("ISO3166-2-lvl6", "")
        prov_osm = lvl6[-2:] if lvl6.startswith("IT-") else ""
        if tipo != "c" and e_via(h):
            return float(h["lat"]), float(h["lon"]), "via", prov_osm, ""
        if tipo != "c":
            continue  # trovato solo un posto generico per una query "con via": provo la successiva
        return float(h["lat"]), float(h["lon"]), "comune", prov_osm, ""
    return None


# ---------------------------------------------------------------- luoghi

COMUNE_CORRETTO = {  # nome scritto da Peck/fonti -> nome vero (con motivo)
    "San Casciano V.P": ("San Casciano in Val di Pesa", None),
    "Borgo San Dalmazzzo": ("Borgo San Dalmazzo", None),
    "Legnano": ("Legnago", None),  # Stringhetto e' di Legnago (VR); Legnano e' in provincia di Milano
    "Borgomanaro": ("Borgomanero", "NO"),  # Peck/fonte scrive IM: Borgomanero e' in provincia di Novara
    "Sorbara": ("Sorbara, Bomporto", "MO"),
    "Robbio Lomellina": ("Robbio", None),
}
# righe senza comune o con comune sbagliato nella chiave: chiave -> (via, cap, comune, prov, paese)
MANUALI = {
    "Regione Prati e Pescine": ("Regione Prati e Pescine", "", "Arma di Taggia", "IM", "Italia"),
    "via Arma di Taggia, Regione Prati e Pescine, Argine sinistro":
        ("Regione Prati e Pescine", "18018", "Arma di Taggia", "IM", "Italia"),
    "Colli Verdi (PV)": ("", "", "Colli Verdi", "PV", "Italia"),
    "Castellina in Chianti (SI)": ("", "", "Castellina in Chianti", "SI", "Italia"),
    "Oliveto di Olivastri, Chiusavecchia (IM)": ("Oliveto di Olivastri", "18027", "Chiusavecchia", "IM", "Italia"),
    "Via Alfieri 16, loc. Oriolo, Voghera (PV)": ("Via Alfieri 16", "", "Voghera", "PV", "Italia"),
    "Str. Vicinale Maccia d'Agliastru 21 Località Prato Comunale, Sassari":
        ("Strada Vicinale Maccia d'Agliastru 21", "07100", "Sassari", "SS", "Italia"),
    "via Maestri del Lavoro 9, Legnano (VR)": ("via Maestri del Lavoro 9", "", "Legnago", "VR", "Italia"),
    "Via Pellegrini 4, Borgomanaro (IM)": ("Via Pellegrini 4", "", "Borgomanero", "NO", "Italia"),
}
PAESE_DI = {"Hamburg": "Germania", "Altheim": "Germania", "Guijuelo": "Spagna"}
# produttori nominati senza indirizzo in Peck: sede nota (solo comune), chiave -> (comune, prov, paese)
SEDI_PRODUTTORI = {
    "BERLUCCHI": ("Corte Franca", "BS", "Italia"),
    "FRESCOBALDI": ("Firenze", "FI", "Italia"),
    "BANFI": ("Montalcino", "SI", "Italia"),
    "BELLAVISTA": ("Erbusco", "BS", "Italia"),
    "DAMILANO": ("Barolo", "CN", "Italia"),
    "DOM PERIGNON": ("Épernay", "", "Francia"),
    "FERRARI": ("Trento", "TN", "Italia"),
    "KRUG": ("Reims", "", "Francia"),
    "RUINART": ("Reims", "", "Francia"),
    "Tenuta San Guido": ("Castagneto Carducci", "LI", "Italia"),
}
# bolli senza elenco TRACES ma con luogo scritto nella nota di aziende.csv
BOLLI_ALIAS = {"IT X2MBD CE": "IT X2M8D CE"}  # probabile refuso: stesso stabilimento di Colla
BOLLI_NOTA = {"IT 00ATA00023D": ("Via Guasti 34", "", "Mombaruzzo", "AT", "Italia",
                                 "nota di aziende.csv (Berta, Casalotto di Mombaruzzo)")}


def parse_chiave(ch, indirizzi):
    """chiave di indirizzo -> (via, cap, comune, prov, paese)."""
    if ch in MANUALI:
        return MANUALI[ch]
    m = re.match(r"^(.*), ([^,]+?)(?: \(([^)]+)\))?$", ch)
    via, comune, prov = m.group(1), m.group(2), (m.group(3) or "")
    cap, paese = "", PAESE_DI.get(comune, "Italia")
    for r in indirizzi:
        if r["comune"].strip().lower() == comune.lower() and \
                r["indirizzo"].strip().lower() == via.lower():
            cap = r["cap"].strip()
            paese = r["paese"].strip() or paese
    if len(prov) > 2 and prov in ("Firenze",):
        prov = "FI"
    if prov == "Salamanca":
        prov = ""
    return via, cap, comune, prov, paese


# ---------------------------------------------------------------- categorie

REGOLE = [  # (categoria, parole chiave) in ordine di priorita'
    ("vino e spumanti", r"CHAMPAGNE|FRANCIACORTA|PROSECCO|SPUMANTE|BAROLO|BRUNELLO|CHIANTI RUFINA|"
                        r"METODO CLASSICO|TRENTO|MOSCATO 2025|CANELLI|POMINO|GUIDALBERTO|LUCENTE|LUNELLI|"
                        r"MONTEPULCIANO|DOCG 20"),
    ("distillati e amari", r"\bGIN\b|GRAPPA|AMARO"),
    ("dolci da forno", r"PANETTONE|PANDORO|VENEZIANA|BISCOTT|AMARETTI|KRUMIRI|BACI DI DAMA|PANFORTE|"
                       r"TORRON|TARALLI"),
    ("cioccolato e canditi", r"SALAMETTO AL CIOCCOLATO|CIOCCOLAT|PRALINE|GIANDUIOTTI|TARTUFINI NERI|"
                             r"TAVOLETTA|MONETA|MARRONCINI|MARRONS|RONDELLE"),
    ("confetture, miele e dolci", r"CONFETTURA|MARMELLATA|MIELE|ZABAIONE|CREMA AL(LA)? (PISTACCHIO|"
                                  r"MANDORLA|NOCCIOLA)|CREMA CIOCC|GELATINE|CARAMELLE|AMARENA|MOSTARDA|"
                                  r"FICO TARTUFATO|FILETTI DI ARANCIA|FRUTTA DISIDRATATA|SALSE PICCANTI"),
    ("frutta secca", r"MANDORLE|NOCCIOLE|NOCI |PISTACCHI|ANACARDI|NOCI$"),
    ("salumi", r"PROSCIUTTO|SALAME|SALAMETT|COPPA|BRESAOLA|MORTADELLA|COTECHINO|ZAMPONE|JAM|PALETA|"
               r"PALETA"),
    ("formaggi", r"PARMIGIANO|PECORINO|TOMETTA|CASTELMAGNO|MONTASIO|BAGOSS|BURRO"),
    ("pesce e conserve di mare", r"SALMONE|TONNO|ACCIUGHE|GRANCHIO|BOTTARGA|SGOMBRO|VENTRESCA"),
    ("olio e aceto", r"OLIO EXTRA|ACETO|CONDIMENTO"),
    ("pasta, riso e legumi", r"SPAGHETTI|PENNE|BUCATINI|PACCHERI|FUSILLONI|LINGUINE|RIGATONI|TAGLIATELLE|"
                             r"TAGLIOLINI|RISO|LENTICCHIE|ZUPPA DI LEGUMI|GRANOLA"),
    ("conserve e sott'olio", r"CARCIOFINI|FUNGHI|POMODOR|PASSATA|GIARDINIERA|CIPOLLINE|CAPPERINI|CUCUNCI|"
                              r"OLIVE|PEPERON|RADICCHIO|BROCCOLI|CAPONATA|ACQUASALE|MARRONI|CREMA AL PARM|"
                              r"CREMA DI PURO|SALSA|PESTO|GENOVESE|RAG|ZAFFERANO|CAFF|T[EÈÉ�] "),
]


def categorie_di(prodotti):
    cats = []
    for p in prodotti:
        up = p.upper()
        trovata = "altro"
        for cat, rx in REGOLE:
            if re.search(rx, up):
                trovata = cat
                break
        if trovata not in cats:
            cats.append(trovata)
    return "; ".join(cats)


# ---------------------------------------------------------------- main

def leggi(nome):
    with open(ROOT / "data" / nome, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def scrivi(nome, campi, righe):
    with open(ROOT / "data" / nome, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campi)
        w.writeheader()
        w.writerows(righe)


def luogo_riga(r, indirizzi, traces):
    """-> (via, cap, comune, prov, paese, fonte_indirizzo) oppure None."""
    tipo, ch = r["tipo_chiave"], r["chiave"]
    if tipo == "indirizzo":
        return parse_chiave(ch, indirizzi) + ("indirizzo scritto da Peck",)
    if tipo == "produttore":
        if ch in SEDI_PRODUTTORI:
            c, p, pa = SEDI_PRODUTTORI[ch]
            return ("", "", c, p, pa, "sede nota del produttore (non scritta da Peck)")
        return None
    if tipo == "bollo_ce":
        chv = BOLLI_ALIAS.get(ch, ch)
        paese_sigla = re.sub(r"^\s*(CE|UE|EC)\s*", "", chv.upper())[:2]
        hit = [v for v in traces.get((paese_sigla, bolli.chiave(chv)), [])]
        if hit:
            v = hit[0]
            via = re.sub(r"\s+", " ", v["via"]).strip()
            com = re.sub(r"\s*\(.*\)\s*$", "", v["comune"]).strip().title()
            com = re.sub(r"\b([DL])'", lambda m: m.group(1).lower() + "'", com)
            return (via, v["cap"], com, "", "Italia" if v["paese"] == "IT" else "Spagna",
                    "elenco UE TRACES" + (" (codice probabile)" if chv != ch else ""))
        for k, (via, cap, com, p, pa, f) in BOLLI_NOTA.items():
            if k in ch:
                return (via, cap, com, p, pa, f)
    return None


def main():
    az, indirizzi, elementi = leggi("aziende.csv"), leggi("indirizzi.csv"), leggi("elementi.csv")
    traces = defaultdict(list)
    for v in bolli.carica():
        traces[(v["paese"], bolli.chiave(v["approval"]))].append(v)

    out, mancanti = [], []
    for r in az:
        lg = luogo_riga(r, indirizzi, traces)
        prodotti = [p.strip() for p in r["prodotti_peck"].split(";") if p.strip()]
        if not lg:
            mancanti.append((r["chiave"], "nessun luogo noto"))
            continue
        via, cap, comune, prov, paese, fonte = lg
        nota = ""
        if comune in COMUNE_CORRETTO:
            nuovo, pnew = COMUNE_CORRETTO[comune]
            nota = f"comune scritto '{comune}', usato '{nuovo}'"
            comune = nuovo
            if pnew:
                prov = pnew
        g = geocodifica(via, cap, comune.split(",")[0] if comune.startswith("Sorbara") else comune,
                        prov, paese)
        if not g:
            mancanti.append((r["chiave"], "Nominatim non trova nulla"))
            continue
        lat, lon, prec, prov_osm, _ = g
        usato = ", ".join(x for x in [via, f"{cap} {comune}".strip(), prov, paese] if x)
        out.append(OrderedDict(
            chiave=r["chiave"], azienda=r["ragione_sociale"] or r["marchio"] or "(non identificata)",
            indirizzo_usato=usato + (f" [{nota}]" if nota else ""), comune=comune,
            provincia=prov or prov_osm, paese=paese, lat=f"{lat:.5f}", lon=f"{lon:.5f}",
            precisione=prec, n_prodotti_peck=len(prodotti), categorie=categorie_di(prodotti),
            tipo_chiave=r["tipo_chiave"], fonte_indirizzo=fonte))
    scrivi("geo.csv", list(out[0].keys()), out)
    print(f"geo.csv: {len(out)} righe;", {p: sum(1 for o in out if o['precisione'] == p)
                                          for p in ("via", "comune")})
    for m in mancanti:
        print("  senza punto:", m)
    regioni_vini()


# ---------------------------------------------------------------- regioni dei vini

REGIONE_ALIAS = {  # nome nella carta -> (testo per Nominatim, nome regione da mostrare)
    "Galizia": "Galicia", "Castiglia e Leon": "Castilla y León", "Catalogna": "Catalunya",
    "Aragona": "Aragón", "Tierra de Madrid": "Comunidad de Madrid", "Isole Canarie": "Canarias",
    "Tierra de Galicia": "Galicia", "Tierra de Castilla y León": "Castilla y León",
    "Estiria": "Steiermark", "Azzorre": "Açores", "Valle de Napa": "Napa Valley",
    "Valle de Maipo": "Maipo Valley", "Terre Siciliane": "Sicilia", "delle Venezie": "Veneto",
    "Sta. Rita Hills": "Santa Rita Hills", "Andalusia": "Andalucía", "Wagram": "Wagram",
    "Alpi Retiche": "Valtellina", "Costa d'Amalfi": "Costiera Amalfitana",
}
# Nominatim sbaglia nomi ambigui (es. "Champagne" finisce in Charente, "Valle de Napa" in Kansas):
# per questi si usa un centro approssimativo scelto a mano (lat, lon)
MANUALI_REGIONI = {
    "Champagne": (49.05, 3.95), "Loire": (47.4, 0.7), "Alsace": (48.3, 7.4), "Mosel": (49.95, 7.05),
    "Sud-Ouest": (43.7, 0.5), "Bordeaux Supérieur": (44.85, -0.35), "Venezia Giulia": (45.8, 13.6),
    "Collio": (45.95, 13.55), "Coteaux du Loir": (47.7, 0.5), "Dry Creek Valley": (38.65, -122.95),
    "Sta. Rita Hills": (34.65, -120.25), "Valle de Napa": (38.5, -122.35), "Patagonia": (-39.0, -67.5),
    "Côtes du Rhône": (44.3, 4.8), "Saint-Julien": (45.19, -0.74), "Pessac-Léognan": (44.72, -0.65),
    "Oltrepò Pavese": (44.98, 9.10), "Pomerol": (44.93, -0.20), "Pouilly-Fumé": (47.28, 2.95), "Beaujolais": (46.05, 4.60),
}
FONDI = {  # denominazioni che si contano sotto la regione o la citta' che le contiene
    "Vin Santo": "Toscana", "Trebbiano d'Abruzzo": "Abruzzo", "Cerasuolo d'Abruzzo": "Abruzzo",
    "Colli Aprutini": "Abruzzo", "Fiano de Avellino": "Avellino", "Greco di Tufo": "Avellino",
    "Colli di Luni": "Luni", "Buttafuoco dell'Oltrepo Pavese": "Oltrepò Pavese",
    "Colli Tortonesi": "Tortona", "Soave Classico": "Soave", "Bardolino Superiore": "Bardolino",
    "Terre Siciliane": "Sicilia", "delle Venezie": "Veneto", "Tierra de Galicia": "Galizia",
    "Tierra de Castilla y Leon": "Castiglia e Leon", "Tierra de Castilla y León": "Castiglia e Leon",
}
BBOX = {  # (ovest, nord, est, sud): limita la ricerca al paese, cosi' "Toscana" non finisce in Francia
    "Italia": (6.6, 47.2, 18.6, 35.4), "Francia": (-5.3, 51.2, 9.7, 41.3),
    "Spagna": (-18.3, 43.9, 4.4, 27.5), "Germania": (5.8, 55.1, 15.1, 47.2),
    "Stati Uniti": (-125.0, 49.5, -66.0, 24.0), "Portogallo": (-31.5, 42.2, -6.0, 32.3),
    "Austria": (9.5, 49.1, 17.2, 46.3),
}
GENERICI = {"Vin de France", "Wein aus Deutschland", "Vino d'Italia"}


def norm_regione(n):
    n = n.strip()
    n = re.sub(r"\s+(1er|Premier|Grand)\s+Cru.*$", "", n)
    n = re.sub(r"\s+Premier Cru$", "", n)
    n = re.sub(r"^(Champagne) Grand Cru '.*'$", r"\1", n)
    n = n.strip()
    return FONDI.get(n, n)


def regioni_vini():
    cant = leggi("cantine.csv")
    acc = OrderedDict()
    scartate = 0
    for c in cant:
        paesi = [p.strip() for p in c["paese"].split(";")]
        regs = [norm_regione(x) for x in c["regioni"].split(";") if x.strip()]
        regs = [x for x in regs if x not in GENERICI]
        if not regs:
            scartate += 1
            continue
        try:
            et = int(c["n_etichette"] or 0)
        except ValueError:
            et = 0
        for i, rg in enumerate(regs):
            paese = paesi[i] if len(paesi) == len(regs) else paesi[0]
            a = acc.setdefault((paese, rg), [0, 0.0])
            a[0] += 1
            a[1] += et / len(regs)
    righe = []
    for (paese, rg), (n, et) in acc.items():
        testo = REGIONE_ALIAS.get(rg, rg)
        iso = ISO.get(paese, "")
        h, da = None, "nominatim"
        if rg in MANUALI_REGIONI:
            (lat, lon), da = MANUALI_REGIONI[rg], "manuale (centro approssimativo)"
        else:
            extra = {"countrycodes": iso} if iso else {}
            if paese in BBOX:
                w, nn, e, so = BBOX[paese]
                extra.update(viewbox=f"{w},{nn},{e},{so}", bounded=1)
            for q in (f"{testo}, {NOME_EN.get(paese, paese)}", testo):
                h = valida(chiedi(q=q, **extra), iso, "")
                if h:
                    break
            if not h:
                print("  regione non trovata (lasciata fuori):", paese, rg, f"[{n} cantine]")
                continue
            lat, lon = float(h["lat"]), float(h["lon"])
        righe.append(OrderedDict(paese=paese, regione=rg, lat=f"{lat:.4f}", lon=f"{lon:.4f}",
                                 n_cantine=n, n_etichette=round(et, 1), coordinate_da=da))
    scrivi("geo_regioni_vini.csv", ["paese", "regione", "lat", "lon", "n_cantine", "n_etichette",
                                    "coordinate_da"], righe)
    print(f"geo_regioni_vini.csv: {len(righe)} regioni; cantine senza regione usabile: {scartate}")


if __name__ == "__main__":
    main()
