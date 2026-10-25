"""Prodotti del delivery di Peck con una ricetta quasi uguale venduta da UN ALTRO produttore (Brezzo).

    python -I src/alternative_7.py

Scrive data/confronto/alternative_7.csv. NON e' un file «risultati_*»: qui il produttore dell'alternativa
NON e' quello del prodotto Peck (colonna stesso_produttore = no), quindi non va mostrato come «Dal produttore».
Serve a rispondere a «quanto costa fuori un prodotto uguale o quasi?». Il legame con chi fa davvero il
prodotto Peck (colonna produttore_peck) viene dall'etichetta del delivery, come in aziende.csv.

Peck: prezzo del delivery (data/locale/delivery_catalogo_2026-10-25.json, resta sul computer).
Brezzo: shop WooCommerce gia' scaricato (data/raw/confronto/brezzo.it/wc_all.json); il formato e' il campo
«peso» della scheda (in kg), che per i vasetti coincide con il peso scritto sul prodotto; il prezzo e' quello
del formato base. Nessuna pagina nuova e' stata scaricata.
"""

import csv
import html
import json
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
DELIVERY = RADICE / "data" / "locale" / "delivery_catalogo_2026-10-25.json"
BREZZO = RADICE / "data" / "raw" / "confronto" / "brezzo.it" / "wc_all.json"
USCITA = RADICE / "data" / "confronto" / "alternative_7.csv"
AZIENDA = "Apicoltura Brezzo S.r.l."

COLONNE = [
    "nome_peck", "cod_art_delivery", "prezzo_peck", "formato_peck", "prezzo_peck_al_kg",
    "azienda_alternativa", "nome_alternativa", "url_alternativa", "prezzo_alternativa", "formato_alternativa",
    "prezzo_alternativa_al_kg", "differenza_pct", "ricetta", "stesso_produttore", "produttore_peck", "data", "nota",
]

# cod_art delivery, id Brezzo, grammi Peck, ricetta, chi fa il prodotto Peck, nota
COPPIE = [
    ("3908", 7819, 30, "identica", "Tartuflanghe (Piobesi d'Alba)",
     "Ingredienti uguali: sale di Guérande 98%, tartufo d'estate (Tuber aestivum Vitt.) liofilizzato 1% (pari al 5% di "
     "tartufo fresco), aroma. Brezzo vende il vasetto da 90 g, Peck quello da 30 g: a parità di peso Peck costa molto "
     "di più, ma il confronto è fra un vasetto piccolo e uno tre volte più grande."),
    ("3911", 6966, 180, "molto simile", "Tartuflanghe (bollo IT 9-2631/L CE)",
     "Stessa ricetta: Parmigiano Reggiano DOP 31%, panna, latte, tartufo estivo (Peck 1%, Brezzo 2%), amido di mais, "
     "aroma (Brezzo aggiunge burro, Peck acqua). Brezzo vende il vasetto da 80 g, Peck quello da 180 g."),
    ("3606", 7969, 180, "molto simile", "Sapori di Montagna (Morbegno)",
     "Stesse proporzioni: pomodoro 70%, funghi porcini 20% (Boletus edulis e relativo gruppo), olio di oliva, sale, "
     "zucchero. Stesso formato (180 g). Peck usa olio extra vergine, Brezzo olio di oliva."),
    ("3706", 7744, 180, "simile", "Sapori di Montagna (bollo IT 9-3382/L CE)",
     "Ragù di cinghiale 180 g, ma la ricetta cambia: Peck cinghiale 30%, passata 30%, maiale 20%; Brezzo cinghiale "
     "30%, pomodoro, vino rosso, verdure (nessun maiale in elenco)."),
    ("3700", 7741, 180, "simile", "Sapori di Montagna (bollo IT 9-3382/L CE)",
     "Ragù di cervo 180 g, ma la ricetta cambia: Peck cervo 30%, passata 30%, maiale 20%; Brezzo cervo 30%, pomodoro, "
     "vino rosso, verdure (nessun maiale in elenco)."),
    ("3917", 7548, 500, "molto simile", "Pianetta di Barbieri (Voghera)",
     "Fichi canditi, zucchero, sciroppo di glucosio, aroma di senape: stessa ricetta. Peck vende il vaso da 500 g, "
     "Brezzo quello da 380 g: Peck costa meno al kg perché il vaso è più grande."),
    ("3559", 7557, 500, "molto simile", "Pianetta di Barbieri (Voghera)",
     "Pere candite, zucchero, sciroppo di glucosio, aroma di senape: stessa ricetta. Vaso da 500 g contro 380 g."),
    ("3960", 7545, 500, "molto simile", "Pianetta di Barbieri (Voghera)",
     "Ciliegie candite, zucchero, sciroppo di glucosio, aroma di senape, colorante E127: stessa ricetta. Vaso da "
     "500 g contro 380 g."),
    ("3538", 7584, 200, "molto simile", "F.lli Merano (Lucinasco)",
     "Olive Taggiasca, acqua, sale, aromi (Brezzo: timo, alloro, rosmarino). Peck 200 g contro 300 g di Brezzo."),
    ("7567", 7284, 250, "molto simile", "non identificato (l'etichetta delivery non nomina il produttore)",
     "Miele di Manuka con MGO 514+, 250 g: stesso grado e stesso formato. Peck non dice la marca né il produttore, "
     "quindi non sappiamo se sia lo stesso miele."),
    ("4039", 7266, 500, "identica", "Sapori di Norcia (Norcia)",
     "Lenticchie di Castelluccio di Norcia IGP al 100%, 500 g. Il produttore vero (Sapori di Norcia) le vende a 6,80 € "
     "(risultati_4): Brezzo, che le rivende, costa quanto Peck."),
    ("3918", 7197, 50, "molto simile", "Santamaria (Calizzano)",
     "Porcini secchi (Boletus edulis e relativo gruppo), sacchetto da 50 g. Il produttore vero (Santamaria) li vende a "
     "13,50 € (risultati_5)."),
]


def main():
    cat = {p["cod_art"]: p for p in json.load(open(DELIVERY, encoding="utf-8"))["prodotti"]}
    brezzo = {p["id"]: p for p in json.load(open(BREZZO, encoding="utf-8"))}
    righe = []
    for cod, bid, g_peck, ricetta, prod_peck, nota in COPPIE:
        pk, br = cat[cod], brezzo[bid]
        p_peck = float(pk["prezzo"])
        if pk["cod_um"] != "PZ":
            raise SystemExit(f"{cod}: prezzo al kg, non a confezione")
        kg_peck = p_peck / (g_peck / 1000)
        pr = br["prices"]
        p_alt = int(pr["price"]) / 10 ** int(pr["currency_minor_unit"])
        g_alt = round(float(br["weight"]) * 1000)
        kg_alt = p_alt / (g_alt / 1000)
        dp = (kg_peck / kg_alt - 1) * 100
        righe.append({
            "nome_peck": pk["des_art"].replace("�", "").strip(), "cod_art_delivery": cod,
            "prezzo_peck": f"{p_peck:g}", "formato_peck": f"{g_peck} g", "prezzo_peck_al_kg": f"{kg_peck:.2f}",
            "azienda_alternativa": AZIENDA, "nome_alternativa": html.unescape(br["name"]),
            "url_alternativa": br["permalink"], "prezzo_alternativa": f"{p_alt:g}", "formato_alternativa": f"{g_alt} g",
            "prezzo_alternativa_al_kg": f"{kg_alt:.2f}", "differenza_pct": f"{dp:+.1f}", "ricetta": ricetta,
            "stesso_produttore": "no", "produttore_peck": prod_peck, "data": "2026-10-25",
            "nota": nota + " Il peso del prodotto Brezzo è il campo «peso» della scheda; prezzi al kg a parità di peso.",
        })
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE)
        w.writeheader()
        w.writerows(righe)
    print(f"{len(righe)} righe -> {USCITA}")
    for r in righe:
        print(f"  {r['differenza_pct']:>7}%  {r['ricetta']:<12} {r['nome_peck'][:50]:<50} peck {r['prezzo_peck']} ({r['formato_peck']})  "
              f"alt {r['prezzo_alternativa']} ({r['formato_alternativa']})")


if __name__ == "__main__":
    main()
