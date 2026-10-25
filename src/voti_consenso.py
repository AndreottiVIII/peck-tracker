"""Consenso dei critici per ogni vino della carta Peck -> data/voti_consenso.csv.

    python -I src/voti_consenso.py            # scrive data/voti_consenso.csv e stampa il riepilogo
    python -I src/voti_consenso.py verifica   # 15 vini a caso con il conto fatto a mano da controllare

Fonti lette (tutte gia' abbinate in modo rigido ai vini Peck dagli altri programmi):
  data/tannico_voti.csv    voti dei critici riportati da Tannico (testo «Robert Parker 95/100; Bibenda 5 grappoli»)
  data/voti_aperti.csv     Wine Enthusiast (punti 100, un degustatore) e X-Wines (UTENTI, stelle 1-5)
  data/voti_enoteche.csv   critici riportati da Millesima, Callmewine, Zachys, Xtrawine, BBR e gli altri negozi
  data/voti_extra.csv      Luca Maroni, Wine Spectator Top 100 (src/voti_consenso_fonti.py)

Regole (decise una volta, qui sotto, e scritte anche in JOURNAL.md):
  * Un «critico» e' una TESTATA, non una persona: Wine Advocate (Parker, Perrotti-Brown, Kelley, Larner...), Vinous
    (Galloni, Martin, Tanzer, Raynolds...), Wine Enthusiast (tutti i degustatori), Weinwisser (Gabriel, Kunz).
    Se due negozi riportano lo stesso critico per lo stesso vino, il critico conta UNA volta (media dei suoi valori).
  * Scala: si usano solo i voti su 100 e quelli su 20 (x5, come richiesto: 17/20 = 85). La conversione e' ruvida e
    penalizza i critici a 20 punti (Jancis Robinson, Weinwisser, Vinum, Bettane+Desseauve): per questo ogni riga ha
    anche `n_critici_su20` e `media_solo_100` (media dei soli critici nativi su 100), e i voti convertiti sono
    segnati nell'elenco `critici` con «(da 17/20, x5)».
    Grappoli, bicchieri, viti, stelle, chiocciole NON hanno una conversione documentata: restano fuori dalla media e
    sono elencati a parte in `altri_giudizi`. Il punteggio di Tannico (negozio) e' una colonna a parte, non un critico.
  * Annata: si usano i voti della stessa annata del vino Peck. Solo se il vino NON ha nessun voto di critico della stessa
    annata, si ricade sui voti di un'annata diversa entro 2 anni (per ogni critico la piu' vicina; a pari distanza la media)
    e la riga e' segnata `solo_annata_diversa = si`.
  * Gli utenti (X-Wines: stelle 1-5, minimo 10 voti) hanno colonne proprie e non entrano mai nella media dei critici.
"""
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
D = RADICE / "data"
USCITA = D / "voti_consenso.csv"
MAX_DISTANZA = 2

# quali righe delle fonti sono di utenti (non critici)
FONTI_UTENTI = {"X-Wines"}

# nome del critico nelle fonti -> testata (chiave del conteggio). Il confronto e' su stringhe minuscole senza accenti.
TESTATE = [
    (r"robert parker|wine advocate|perrotti|william kelley|monica larner|lisa perrotti", "Robert Parker (Wine Advocate)"),
    (r"vinous|galloni|neal martin|tanzer|josh raynolds|eric guido|d.agata|greinacher|rebecca gibb|joaqu", "Vinous"),
    (r"james suckling|^suckling", "James Suckling"),
    (r"wine ?spectator|molesworth", "Wine Spectator"),
    (r"inside burgundy|jasper morris", "Jasper Morris (Inside Burgundy)"),
    (r"wine enthusiast|kerin o|roger voss|michael schachner|virginie boone|paul gregutt|anne krebiehl|jim gordon|"
     r"lauren buzzeo|joe czerwinski|matt kettmann|sean sullivan|susan kostrzewa|alexander peartree|mike desimone|"
     r"jeff jenssen|anna lee", "Wine Enthusiast"),
    (r"jancis ?robinson|julia harding|walter speller|richard hemming|james lawther|tom(?:as)? parker|matthew hayes|"
     r"tim jackson|alistair cooper|ferran centelles", "Jancis Robinson (JancisRobinson.com)"),
    (r"decanter", "Decanter"),
    (r"burghound|allen meadows", "Burghound"),
    (r"jeb ?dunnuck", "Jeb Dunnuck"),
    (r"jeff leve|wine cellar insider", "Jeff Leve (The Wine Cellar Insider)"),
    (r"jane anson|inside bordeaux", "Jane Anson"),
    (r"quarin", "Jean-Marc Quarin"),
    (r"revue du vin|^rvf|la rvf", "Revue du Vin de France"),
    (r"bettane", "Bettane+Desseauve"),
    (r"weinwisser|rene gabriel|andre kunz", "Weinwisser (R. Gabriel / A. Kunz)"),
    (r"^vinum", "Vinum"),
    (r"falstaff", "Falstaff"),
    (r"wine independent", "The Wine Independent"),
    (r"cho lee", "Jeannie Cho Lee"),
    (r"figaro", "Le Figaro Vin"),
    (r"larsson", "Andreas Larsson"),
    (r"gilman", "John Gilman"),
    (r"yves beck", "Yves Beck"),
    (r"veronelli", "Veronelli"),
    (r"maroni", "Luca Maroni"),
    (r"terre de vin", "Terre de Vins"),
    (r"vertdevin", "Vertdevin"),
    (r"tim atkin", "Tim Atkin"),
    (r"halliday", "James Halliday"),
]
TESTATE = [(re.compile(p), n) for p, n in TESTATE]
# «critici» che sono in realta' il negozio stesso (nota o punteggio del venditore): non entrano nella media
NON_CRITICI = re.compile(r"^fine\+rare|ivor davies|^tannico|^millesima|^callmewine|^zachys|^vinatis")
# testate la cui scala non e' a punti (o e' un riconoscimento): finiscono in `altri_giudizi`
SCALE_NON_PUNTI = {"grappoli", "bicchieri", "viti", "stelle", "chiocciole"}


def senza_accenti(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace("’", "'")


def testata(critico, fonte=""):
    if fonte == "Wine Enthusiast":
        return "Wine Enthusiast"
    k = senza_accenti(critico)
    for rx, nome in TESTATE:
        if rx.search(k):
            return nome
    return critico.strip()


def leggi_csv(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def distanza(a_peck, a_fonte):
    a_peck, a_fonte = (a_peck or "NV"), (a_fonte or "NV")
    if a_peck == a_fonte:
        return 0
    if a_peck.isdigit() and a_fonte.isdigit():
        return abs(int(a_peck) - int(a_fonte))
    return 99


def a100(voto, scala):
    """Voto su 100 (float) o None se la scala non si converte. Il 20 -> x5."""
    v = num(voto)
    if v is None:
        return None
    if scala == "100":
        return v if 50 <= v <= 100 else None
    if scala == "20":
        return v * 5 if 10 <= v <= 20 else None
    return None


# ---------------------------------------------------------------- raccolta
def raccogli(annata_peck):
    """Una lista di osservazioni: dict(id, fonte, testata, critico, valore100, scala_orig, voto_orig, annata, dist, utenti, ...)"""
    obs = []

    # Tannico: «Robert Parker 95/100; James Suckling 97/100; Bibenda 5 grappoli»
    for r in leggi_csv(D / "tannico_voti.csv"):
        i = r["id"]
        ann = r["annata_tannico"]
        for pezzo in (r.get("voti_critici") or "").split(";"):
            pezzo = pezzo.strip()
            if not pezzo:
                continue
            m = re.match(r"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*/\s*(\d+)$", pezzo)
            if m:
                nome, v, sc = m.group(1), m.group(2), m.group(3)
                obs.append(dict(id=i, fonte="Tannico", critico=nome, voto=v, scala=sc, annata=ann))
                continue
            m = re.match(r"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*(grappol\w+|bicchier\w+|vit\w+|stell\w+|chiocciol\w+)$", pezzo)
            if m:
                scala = next(v for k, v in (("grappol", "grappoli"), ("bicchier", "bicchieri"), ("vit", "viti"),
                                            ("stell", "stelle"), ("chiocciol", "chiocciole")) if m.group(3).startswith(k))
                obs.append(dict(id=i, fonte="Tannico", critico=m.group(1), voto=m.group(2), scala=scala, annata=ann))

    for r in leggi_csv(D / "voti_aperti.csv"):
        obs.append(dict(id=r["id"], fonte=r["fonte"], critico=r["critico/rivista"], voto=r["voto"], scala=r["scala"],
                        annata=r["annata_fonte"]))
    for r in leggi_csv(D / "voti_enoteche.csv"):
        obs.append(dict(id=r["id"], fonte=r["fonte"], critico=r["critico"], voto=r["voto"], scala=r["scala"],
                        annata=r["annata_fonte"]))
    for r in leggi_csv(D / "voti_extra.csv"):
        obs.append(dict(id=r["id"], fonte=r["fonte"], critico=r["critico_o_tipo"], voto=r["voto"], scala=r["scala"],
                        annata=r["annata_fonte"]))
    for o in obs:
        o["utenti"] = o["fonte"] in FONTI_UTENTI
        o["dist"] = distanza(annata_peck.get(o["id"]), o["annata"])
    return obs


# ---------------------------------------------------------------- consenso di un vino
def fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def consenso_vino(osservazioni):
    """osservazioni di UN vino -> (riga critici, riga utenti, altri giudizi)"""
    osservazioni = [o for o in osservazioni if not NON_CRITICI.search(senza_accenti(o["critico"]))]
    crit = [o for o in osservazioni if not o["utenti"] and o["scala"] in ("100", "20") and o["dist"] <= MAX_DISTANZA
            and a100(o["voto"], o["scala"]) is not None]
    altri = [o for o in osservazioni if not o["utenti"] and o["scala"] in SCALE_NON_PUNTI and o["dist"] <= MAX_DISTANZA]
    stessa = [o for o in crit if o["dist"] == 0]
    solo_diversa = not stessa
    usate = stessa if stessa else crit
    per = defaultdict(list)
    for o in usate:
        per[testata(o["critico"], o["fonte"])].append(o)
    voci = []
    for nome, lst in per.items():
        if solo_diversa:                    # per ogni testata: l'annata piu' vicina (a pari distanza, la media)
            dmin = min(o["dist"] for o in lst)
            lst = [o for o in lst if o["dist"] == dmin]
        valori = [a100(o["voto"], o["scala"]) for o in lst]
        v = sum(valori) / len(valori)
        da20 = all(o["scala"] == "20" for o in lst)
        annate = sorted({o["annata"] for o in lst})
        voci.append(dict(nome=nome, valore=v, da20=da20, annate=annate, fonti=sorted({o["fonte"] for o in lst}),
                         originali=[f"{o['voto']}/{o['scala']}" for o in lst]))
    voci.sort(key=lambda x: -x["valore"])
    return voci, solo_diversa, altri


def riga_utenti(osservazioni, annata_peck_v):
    ut = [o for o in osservazioni if o["utenti"] and o["dist"] <= MAX_DISTANZA and num(o["voto"]) is not None]
    if not ut:
        return None
    dmin = min(o["dist"] for o in ut)
    ut = [o for o in ut if o["dist"] == dmin]
    medie, n = [], 0
    for o in ut:
        medie.append(num(o["voto"]))
        m = re.search(r"n=(\d+)", o["critico"])
        n += int(m.group(1)) if m else 0
    return dict(media=sum(medie) / len(medie), n=n, annata=",".join(sorted({o["annata"] for o in ut})),
                diversa=dmin > 0, fonte=ut[0]["fonte"])


def main():
    vini = {}
    prezzo = defaultdict(list)
    for r in leggi_csv(D / "vini.csv"):
        if r["variante"] == "calice":
            continue
        vini.setdefault(r["id"], r)
        p = num(r["prezzo_euro"])
        if p is not None:
            prezzo[r["id"]].append(p)
    prezzo = {k: min(v) for k, v in prezzo.items()}
    annata_peck = {i: (r["annata"] or "NV") for i, r in vini.items()}   # senza annata = NV
    obs = raccogli(annata_peck)
    per_vino = defaultdict(list)
    for o in obs:
        if o["id"] in vini:
            per_vino[o["id"]].append(o)
    tann = {r["id"]: r for r in leggi_csv(D / "tannico_voti.csv")}

    campi = ["id", "n_critici", "media", "mediana", "min", "max", "critici", "annata_base", "annate_usate",
             "solo_annata_diversa", "n_critici_su20", "media_solo_100", "fonti", "altri_giudizi",
             "utenti_media_su5", "utenti_n_voti", "utenti_annata", "utenti_annata_diversa",
             "punteggio_tannico", "punteggio_tannico_annata"]
    righe = []
    for i in sorted(per_vino, key=int):
        voci, diversa, altri = consenso_vino(per_vino[i])
        ut = riga_utenti(per_vino[i], annata_peck[i])
        t = tann.get(i, {})
        if not voci and not ut and not (altri) and not t.get("punteggio_tannico"):
            continue
        vals = [x["valore"] for x in voci]
        r = {"id": i, "n_critici": len(voci)}
        if vals:
            r.update(media=fmt(round(sum(vals) / len(vals), 1)), mediana=fmt(statistics.median(vals)),
                     min=fmt(min(vals)), max=fmt(max(vals)))
            r["critici"] = "; ".join(
                f"{x['nome']} {fmt(x['valore'])}" + (f" (da {' / '.join(x['originali'])}, x5)" if x["da20"] else "")
                for x in voci)
            nativi = [x["valore"] for x in voci if not x["da20"]]
            r["n_critici_su20"] = sum(1 for x in voci if x["da20"])
            if nativi:
                r["media_solo_100"] = fmt(round(sum(nativi) / len(nativi), 1))
            r["annata_base"] = annata_peck[i]
            r["annate_usate"] = ",".join(sorted({a for x in voci for a in x["annate"]}))
            r["solo_annata_diversa"] = "si" if diversa else "no"
            r["fonti"] = ", ".join(sorted({f for x in voci for f in x["fonti"]}))
        else:
            r.update(annata_base=annata_peck[i], solo_annata_diversa="")
        if altri:
            vistiA = {}
            for o in altri:
                vistiA[(testata(o["critico"], o["fonte"]), o["voto"], o["scala"], o["annata"])] = o
            r["altri_giudizi"] = "; ".join(f"{k[0]} {k[1]} {k[2]}" + ("" if k[3] == annata_peck[i] else f" ({k[3]})")
                                           for k in sorted(vistiA))
        if ut:
            r.update(utenti_media_su5=f"{ut['media']:.2f}", utenti_n_voti=ut["n"], utenti_annata=ut["annata"],
                     utenti_annata_diversa="si" if ut["diversa"] else "no")
        if t.get("punteggio_tannico"):
            r["punteggio_tannico"] = t["punteggio_tannico"]
            r["punteggio_tannico_annata"] = t["annata_tannico"]
        righe.append(r)
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, campi)
        w.writeheader()
        w.writerows(righe)
    riepilogo(righe, vini, prezzo)


def riepilogo(righe, vini, prezzo):
    con = [r for r in righe if r["n_critici"]]
    stessa = [r for r in con if r["solo_annata_diversa"] == "no"]
    diversa = [r for r in con if r["solo_annata_diversa"] == "si"]
    tot = len(vini)
    sotto = {i for i in vini if prezzo.get(i, 9999) < 100}
    sotto200 = {i for i in vini if prezzo.get(i, 9999) < 200}
    borg = {i for i, v in vini.items() if v["regione"] == "Bourgogne"}
    print(f"vini Peck (senza calici): {tot}")
    print(f"vini con consenso dei critici: {len(con)}  (stessa annata {len(stessa)}, solo annata diversa +/-2 {len(diversa)})")
    for etichetta, ins in (("sotto 100 euro", sotto), ("sotto 200 euro", sotto200), ("Bourgogne", borg)):
        ids_c = {r["id"] for r in con}
        ids_s = {r["id"] for r in stessa}
        print(f"  {etichetta:15} {len(ins):4} vini: con consenso {len(ids_c & ins):4} ({100*len(ids_c & ins)/len(ins):.0f}%), "
              f"stessa annata {len(ids_s & ins):4} ({100*len(ids_s & ins)/len(ins):.0f}%)")
    by_n = Counter(min(r["n_critici"], 5) for r in con)
    print("  per numero di critici (5 = 5 o piu'):", dict(sorted(by_n.items())))
    ut = [r for r in righe if r.get("utenti_media_su5")]
    print(f"vini con media degli utenti X-Wines: {len(ut)}")
    solo_ut = [r for r in righe if not r["n_critici"] and r.get("utenti_media_su5")]
    print(f"  di cui senza nessun critico: {len(solo_ut)}")
    qualcosa = {r["id"] for r in righe}
    print(f"vini con qualunque voto (critici, utenti, altri giudizi, Tannico): {len(qualcosa)}")
    print("regioni (con consenso / vini):")
    for reg, n in Counter(v["regione"] for v in vini.values()).most_common(8):
        c = sum(1 for r in con if vini[r["id"]]["regione"] == reg)
        print(f"  {reg:22} {c:4} / {n:4}")


def verifica(n=15):
    import random
    righe = {r["id"]: r for r in leggi_csv(USCITA)}
    vini = {r["id"]: r for r in leggi_csv(D / "vini.csv")}
    random.seed(5)
    for i in random.sample(sorted(k for k, r in righe.items() if r["n_critici"] != "0"), n):
        r, v = righe[i], vini[i]
        print(f"[{i}] {v['cantina']} | {v['nome']} | {v['annata']}  -> n={r['n_critici']} media={r['media']} "
              f"mediana={r['mediana']} ({r['min']}-{r['max']}) {r['solo_annata_diversa']=}\n     {r['critici']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verifica":
        verifica()
    else:
        main()
