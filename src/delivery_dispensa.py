"""Abbina i prodotti del catalogo delivery di Peck alla Dispensa del sito.

    python -I src/delivery_dispensa.py

Legge:  data/locale/delivery_catalogo_2026-10-25.json  (catalogo completo del servizio delivery,
        area riservata ai clienti: resta sul computer, non si pubblica)
        i 194 prodotti della Dispensa (da src/sito.py, costruisci_cibo)
Scrive: data/delivery_dispensa.csv                      (PUBBLICO: solo i prodotti abbinati e solo
                                                         quello che serve al sito)
        data/locale/delivery_non_in_dispensa.csv        (tutti gli altri, ordinati per reparto)
        data/locale/delivery_non_in_dispensa_excel.csv  (lo stesso, con BOM e punto e virgola per Excel)

Gli abbinamenti sono fatti a mano, uno per uno, e stanno in ABBINAMENTI qui sotto: nome, formato e
ingredienti sono stati controllati su ogni riga. Regola: nel dubbio NON si abbina. Il programma
stampa il confronto dei pesi cosi' si rilegge a occhio dopo ogni modifica.

corrispondenza:
    esatta                             stesso prodotto e stesso formato (nome e peso uguali)
    stesso prodotto formato diverso    stesso prodotto, ma nel delivery il formato e' un altro oppure
                                       e' venduto a peso (prezzo al kg)
"""

import csv
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
DATI = RADICE / "data"
LOCALE = DATI / "locale"
CATALOGO = LOCALE / "delivery_catalogo_2026-10-25.json"
FOTO_BASE = "https://delivery.peck.it/files/img_web/"
FOTO_LOCALE = Path("archivio") / "foto_delivery"

E = "esatta"
F = "stesso prodotto formato diverso"

# chiave Dispensa -> (cod_art delivery, corrispondenza, nota)
ABBINAMENTI = {
    # --- sughi, salse, condimenti
    "ragu-al-cinghiale-180-g": ("3706", E, ""),
    "ragu-al-cervo-180-g": ("3700", E, ""),
    "salsa-di-funghi-porcini-180-g": ("3542", E, ""),
    "salsa-di-noci-180-g": ("3541", E, ""),
    "pesto-alla-genovese-180-g": ("3601", E, ""),
    "passata-di-datterino-quorum-550g": ("7640", E, ""),
    "pomodorini-rossi-al-naturale-quorum-350g": ("7643", E, ""),
    "condimento-aromatizzato-al-tartufo-bianco-25-cl": ("3528", E, "25 cl = 250 ml"),
    "salse-piccanti-di-frutta-castagna-susina-e-pera-144-g": (
        "3961", E, "nel delivery si chiama «Tris di salse castagna, susina, pera» (3 vasetti da 48 g)"),
    "mostarda-di-frutta-candita-500-g": ("4285", E, ""),
    # --- aceti e oli
    "aceto-balsamico-di-modena-igp-25-cl": ("3509", E, "una stella (fuxia), 25 cl = 250 ml"),
    "aceto-balsamico-di-modena-igp-100-ml-fuxia": ("3509", F, "nel delivery c'è solo il formato da 250 ml"),
    "aceto-balsamico-di-modena-igp-250-ml": ("3709", E, "due stelle (blu)"),
    "olio-extra-vergine-di-oliva-monte-sul-lago": (
        "3561", F, "la scheda dello shop non dice il formato; nel delivery è da 500 ml"),
    "olio-extravergine-di-oliva-taggiasca": (
        "3578", F, "la scheda dello shop non dice il formato; nel delivery è da 500 ml"),
    "olio-extra-vergine-di-oliva-nocellara-50-cl": ("3703", E, "50 cl = 500 ml"),
    # --- sott'oli e conserve
    "capperini-di-salina-al-sale-140-g": ("3508", E, ""),
    "cucunci-di-salina-in-aceto-di-vino-200-g": ("3533", E, ""),
    "peperoncini-farciti-con-capperi-e-acciughe-200-g": ("3677", E, ""),
    "carciofini-grigliati-in-olio-extra-vergine-di-oliva-340-g": ("3580", E, ""),
    "pomodori-secchi-in-olio-extravergine-di-oliva-190-g": ("3536", E, ""),
    "funghi-porcini-in-olio-extra-vergine-di-oliva-190-g": ("3640", E, ""),
    "funghi-porcini-secchi-extra-50-g": ("3918", E, "sacchetto"),
    "giardiniera-peck-580-ml": ("5861", E, ""),
    "olive-taggiasca-snocciolate-in-olio-evo-180-g": ("3540", E, ""),
    "radicchio-rosso-tardivo-sott-olio-330-g": ("2654", E, ""),
    "peperone-crusco-20-g": ("5908", E, ""),
    "lenticchie-di-castelluccio-di-norcia-igp-500-g": ("4039", E, ""),
    # --- tartufo
    "crema-di-puro-tartufo-bianco-40-g": ("3531", E, "tubetto"),
    "burro-con-tartufo-30-g": ("3891", E, ""),
    "crema-al-parmigiano-reggiano-e-tartufo-180-g": ("3911", E, ""),
    # --- dolci
    "confettura-extra-di-lamponi-340-g": ("3793", E, "il campo grammatura del delivery dice 350 g, il nome 340 g"),
    "confettura-extra-di-fichi-340-g": ("3791", E, "il campo grammatura del delivery dice 350 g, il nome 340 g"),
    "marmellata-di-limoni-e-cedri-340-g": ("3797", E, "il campo grammatura del delivery dice 350 g, il nome 340 g"),
    "miele-di-limone-250-g": ("3575", E, ""),
    "noci-e-miele-di-acacia-230-g": ("3905", E, ""),
    "nocciole-tostate-e-miele-d-acacia-230-g": ("3769", E, ""),
    "praline-assortite-90-g": ("1488", E, "12 praline"),
    "praline-assortite-190-g": ("1552", E, "24 praline"),
    "praline-assortite-430-g": ("1553", E, "54 praline"),
    # --- frutta secca (nel delivery sfusa, a peso)
    "mandorle-salate-200-g": ("2208", F, "nel delivery è sfuso, venduto a peso («mandorle sgusciate salate»)"),
    "anacardi-salati-al-curry-200-g": ("4621", F, "nel delivery è sfuso, venduto a peso"),
    "pistacchi-tostati-e-salati-200-g": ("1227", F, "nel delivery è sfuso, venduto a peso («pistacchi tostati», con sale 2,5%)"),
    "noci-pecan-tostate-e-salate-200-g": ("1083", F, "nel delivery è sfuso, venduto a peso («noci pecan tostate», con sale 2%)"),
    # --- salumi
    "salametti-mignon-peck-550-g": ("23", E, "il campo grammatura del delivery dice 350 g, il nome 550 g"),
    "salametto-peck-350-g": ("220", F, "nel delivery è venduto a peso (pezzo da circa 450 g)"),
    "salame-di-felino-igp-peck-800-g": ("205", F, "nel delivery è il salame intero, venduto a peso"),
    "jamon-iberico-gran-riserva-joselito-affettato-70-g": ("4006", E, ""),
    "paleta-iberica-gran-riserva-joselito-affettata-70-g": ("4007", E, ""),
    # --- formaggi (nel delivery a peso)
    "parmigiano-reggiano-dop-stagionato-minimo-24-mesi-500g": ("716", F, "nel delivery è venduto a peso"),
    "parmigiano-reggiano-dop-stagionato-minimo-24-mesi-1-kg": ("716", F, "nel delivery è venduto a peso"),
    "parmigiano-reggiano-dop-stagionato-minimo-24-mesi-2-kg": ("716", F, "nel delivery è venduto a peso"),
    "pecorino-al-tartufo-stagionato-in-grotta-1-kg": ("2319", F, "nel delivery è venduto a peso"),
    "pecorino-sardo-maturo-dop-medoro-650-g": ("560", F, "nel delivery è venduto a peso"),
    "pecorino-ai-quattro-pepi-400-gr": ("4290", F, "nel delivery è venduto a peso"),
    "bagoss-di-bagolino-0-5-kg": ("547", F, "nel delivery è venduto a peso"),
    "castelmagno-dop-500-gr": ("569", F, "nel delivery è venduto a peso"),
    "montasio-dop-stagionato-1-kg": ("566", F, "nel delivery è venduto a peso"),
    # --- pesce
    "filetti-di-acciughe-del-mar-cantabrico-peck-78-g": ("6407", E, "nel delivery c'è anche il formato da 120 g"),
    "bottarga-di-muggine-grattugiata-100-g": ("4040", E, "nel delivery scritto «grattuggiata»"),
}

# Parole che Peck scrive diverse fra shop e delivery: servono solo a leggere il confronto dei pesi.
NOTE_NON_ABBINATI = {
    "6406": "altro formato (120 g) di «Filetti di acciughe del Mar Cantabrico Peck 78 g» della Dispensa",
}


def senza_accenti(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def formato_dal_nome(nome):
    """'340 G' -> (340.0, 'g'), '250 ML' -> (250.0, 'ml'), 'G. 70' -> (70.0, 'g'), '25 cl' -> (250.0, 'ml')."""
    s = senza_accenti(nome).lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|gr|g|ml|cl|l)\b", s)
    if m:
        v, u = float(m.group(1)), m.group(2)
    else:
        m = re.search(r"\b(?:g|gr)\.?\s*(\d+(?:\.\d+)?)\b", s)
        if not m:
            return None
        return float(m.group(1)), "g"
    if u in ("g", "gr"):
        return v, "g"
    if u == "kg":
        return v * 1000, "g"
    if u == "ml":
        return v, "ml"
    if u == "cl":
        return v * 10, "ml"
    return v * 1000, "ml"  # l


def testo_numero(v):
    return str(int(v)) if float(v).is_integer() else str(v).replace(".", ",")


def formato_testo(p):
    """Testo del formato venduto: '180 g', '500 ml', 'al kg'."""
    if p["cod_um"] == "KG":
        return "al kg"
    f = formato_dal_nome(p["des_art"])
    if f:
        return f"{testo_numero(f[0])} {f[1]}"
    return f"{testo_numero(p['grammatura'])} g"


def carica_dispensa():
    spec = importlib.util.spec_from_file_location("sito", RADICE / "src" / "sito.py")
    sito = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(RADICE / "src"))
    spec.loader.exec_module(sito)
    dispensa = sito.costruisci_cibo()[0]
    return {d["id"]: d for d in dispensa}


def scrivi_csv(percorso, colonne, righe, bom=True, delim=","):
    with open(percorso, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colonne, delimiter=delim, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    per_cod = {p["cod_art"]: p for p in cat["prodotti"]}
    dispensa = carica_dispensa()

    errori = [k for k in ABBINAMENTI if k not in dispensa] + \
             [c for c, _, _ in ABBINAMENTI.values() if c not in per_cod]
    if errori:
        sys.exit(f"chiavi o codici che non esistono: {errori}")

    righe = []
    usati = set()
    print("confronto dei pesi (Dispensa -> delivery):")
    for chiave, (cod, corr, nota) in ABBINAMENTI.items():
        d, p = dispensa[chiave], per_cod[cod]
        usati.add(cod)
        fd, fp = formato_dal_nome(d["nome_originale"]), formato_dal_nome(p["des_art"])
        segno = "OK " if fd and fp and fd == fp else "   "
        if corr == E and not (fd and fp and fd == fp):
            segno = "!!!"
        print(f"  {segno} {corr[:6]:6} {d['nome_originale'][:55]:55} {fd} -> {fp} [{p['grammatura']}] {p['des_art'][:45]}")
        righe.append({
            "chiave_dispensa": chiave,
            "nome_dispensa": d["nome_originale"],
            "cod_art": cod,
            "nome_delivery": p["des_art"],
            "prezzo": f"{p['prezzo']:g}",
            "unita": p["cod_um"],
            "grammatura": f"{p['grammatura']:g}",
            "formato": formato_testo(p),
            "foto_url": FOTO_BASE + p["img_web"] if p["img_web"] else "",
            "corrispondenza": corr,
            "nota": nota,
        })
    colonne = ["chiave_dispensa", "nome_dispensa", "cod_art", "nome_delivery", "prezzo", "unita",
               "grammatura", "formato", "foto_url", "corrispondenza", "nota"]
    scrivi_csv(DATI / "delivery_dispensa.csv", colonne, righe)

    # --- tutti gli altri, per reparto
    altri = []
    for p in cat["prodotti"]:
        # un prodotto delivery puo' servire a piu' voci della Dispensa (per esempio il parmigiano):
        # e' "abbinato" se compare in almeno un abbinamento
        if p["cod_art"] in usati:
            continue
        altri.append({
            "cod_art": p["cod_art"],
            "nome": p["des_art"],
            "reparto": p["reparto"] or "(senza reparto)",
            "prezzo": f"{p['prezzo']:g}",
            "unita": p["cod_um"],
            "grammatura": f"{p['grammatura']:g}",
            "formato": formato_testo(p),
            "foto_locale": str(FOTO_LOCALE / p["img_web"]) if p["img_web"] else "",
            "foto_url": FOTO_BASE + p["img_web"] if p["img_web"] else "",
            "nota": NOTE_NON_ABBINATI.get(p["cod_art"], ""),
        })
    altri.sort(key=lambda r: (r["reparto"], senza_accenti(r["nome"]).lower()))
    col2 = ["cod_art", "nome", "reparto", "prezzo", "unita", "grammatura", "formato", "foto_locale",
            "foto_url", "nota"]
    scrivi_csv(LOCALE / "delivery_non_in_dispensa.csv", col2, altri)
    scrivi_csv(LOCALE / "delivery_non_in_dispensa_excel.csv", col2, altri, delim=";")

    from collections import Counter
    print()
    print(f"abbinamenti: {len(righe)} voci della Dispensa, {len(usati)} prodotti delivery diversi")
    print("   ", dict(Counter(r["corrispondenza"] for r in righe)))
    print("   con foto:", sum(1 for r in righe if r["foto_url"]))
    print(f"delivery non abbinati: {len(altri)} su {len(cat['prodotti'])}")
    rep = Counter(r["reparto"].split(" > ")[0] for r in altri)
    for k, n in rep.most_common():
        print(f"   {n:4} {k}")


if __name__ == "__main__":
    main()
