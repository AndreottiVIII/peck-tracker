"""Passo 2: abbina i bolli CE di Peck agli stabilimenti riconosciuti.

Fonte: elenchi ufficiali degli stabilimenti riconosciuti ai sensi del Reg. CE 853/2004, nella
versione pubblicata dalla Commissione europea (TRACES/IMSOC, pubblica, senza login), perche' il
servizio del Ministero della Salute (salute.gov.it, SINTESIS) era "non disponibile" al momento
del lavoro. I file vanno in data/raw/sintesis/ (non pubblicata).

Uso:
  python -I src/bolli.py scarica      # scarica le sezioni "food" di IT e ES
  python -I src/bolli.py cerca        # abbina i codici di data/altre_origini.csv
"""
import csv, json, re, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "sintesis"
BASE = "https://webgate.ec.europa.eu/tracesnt/directory/listing/establishment/publication/"
SEZIONI_FOOD = ["TREATED_STOMACHS_BLADDERS_AND_INTESTINES_CASING_ONLY", "COLLAGEN",
    "EGGS_AND_EGG_PRODUCTS_EU", "RENDERED_ANIMAL_FATS_AND_GREAVES_EU", "FISHERY_PRODUCTS_EU",
    "FROGS_LEGS_AND_SNAILS_EU", "GELATINE_EU", "GENERAL_ACTIVITY_ESTABLISHMENT",
    "MEAT_OF_FARMED_GAME_EU", "LIVE_BIVALVE_MOLLUSCS_EU", "MINCED_MEAT_EU", "RAW_MILK_EU",
    "MEAT_FROM_POULTRY_AND_LAGOMORPHS_EU", "MEAT_OF_DOMESTIC_UNGULATES_EU", "MEAT_PRODUCTS_EU",
    "SPROUTS", "WILD_GAME_MEAT_EU"]


def scarica(paesi=("IT", "ES")):
    RAW.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    s.get(BASE + "index", timeout=60)
    for p in paesi:
        for sez in SEZIONI_FOOD:
            f = RAW / f"traces_{p}_{sez}.json"
            if f.exists():
                continue
            tutti, offset = [], 0
            while True:
                r = s.get(f"{BASE}establishments/{p}/{sez}",
                          params={"sort": "name.value", "max": 1000, "offset": offset}, timeout=300)
                r.raise_for_status()
                pezzo = r.json()
                tutti += pezzo
                print(p, sez, offset, len(pezzo))
                if len(pezzo) < 1000:
                    break
                offset += len(pezzo)
                time.sleep(1)
            f.write_text(json.dumps(tutti, ensure_ascii=False), encoding="utf-8")
            time.sleep(1)


def chiave(code):
    """Forma compatta per il confronto.

    'IT 1150 L CE', 'IT 1150 L UE', 'CE IT 1150 L', 'CEIT 1150 L' -> '1150L'.
    Toglie CE/UE/EC, la sigla del paese, spazi, trattini, barre e punti.
    """
    c = code.upper()
    c = re.sub(r"^\s*(CE|UE|EC)\s*", "", c)
    c = re.sub(r"\s*(CE|UE|EC)\s*$", "", c)
    c = re.sub(r"^\s*(IT|ES)\s+(?=\S)", "", c)
    c = re.sub(r"^\s*(IT|ES)(?=\d)", "", c)
    return re.sub(r"[^A-Z0-9]", "", c)


def carica():
    voci = []
    for f in sorted(RAW.glob("traces_*_*.json")):
        for e in json.loads(f.read_text(encoding="utf-8")):
            a = e.get("address") or {}
            cr = a.get("cityReference") or {}
            voci.append({
                "approval": e.get("approvalNumber", ""),
                "nome": e.get("operatorName", ""),
                "via": (a.get("street") or {}).get("value", ""),
                "cap": cr.get("postalCode", ""),
                "comune": cr.get("name", ""),
                "sezione": f.stem.split("_", 2)[2],
                "paese": f.stem.split("_")[1],
            })
    return voci


def cerca():
    voci = carica()
    indice = {}
    for v in voci:
        indice.setdefault((v["paese"], chiave(v["approval"])), []).append(v)
    with open(ROOT / "data" / "altre_origini.csv", encoding="utf-8-sig") as fh:
        righe = [r for r in csv.DictReader(fh) if r["tipo"] == "bollo"]
    for r in righe:
        k = chiave(r["valore"])
        hit = indice.get((r["valore"][:2].upper(), k), [])
        hit += [v for v in indice.get((r["valore"][:2].upper(), k + "S"), [])]
        print(f"== {r['valore']} -> {k}: {len(hit)} risultati")
        for v in hit:
            print("   ", v["approval"], "|", v["nome"], "|", v["via"], v["cap"], v["comune"], "|", v["sezione"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cerca"
    {"scarica": scarica, "cerca": cerca}[cmd]()
