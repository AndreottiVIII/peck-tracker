"""Confronti prezzi del terzo giro (delivery di Peck x cataloghi dei produttori gia' scaricati).

    python -I src/risultati_7.py

Scrive data/confronto/risultati_7.csv (colonne di ISTRUZIONI.md + cod_art_delivery e nome_delivery).

Come si e' lavorato (25 ottobre 2026): per ognuno dei 503 prodotti del catalogo delivery
(data/locale/delivery_catalogo_2026-10-25.json, che resta sul computer) si sono letti il nome, gli
ingredienti e la frase «Prodotto in / Prodotto da» dell'etichetta, e si sono collegati ai produttori di
data/aziende.csv e data/confronto/aziende_secondo_giro.csv per indirizzo o bollo CE. Poi si sono cercati
nei cataloghi gia' scaricati (data/raw/confronto/<dominio>/) i prodotti dello stesso produttore.
Le righe gia' presenti in risultati_1..6.csv NON si ripetono. I prezzi dei produttori sono quelli dei
cataloghi scaricati, non sono stati scaricati altri siti. Il prezzo Peck e' quello del delivery.

Le righe sono scritte a mano (e' quello che si poteva provare), i numeri sono calcolati qui sotto.
"""

import csv
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "data" / "confronto" / "risultati_7.csv"

COLONNE = [
    "nome_peck", "chiave_dispensa", "prezzo_peck", "formato_peck", "prezzo_peck_al_kg", "azienda",
    "nome_produttore", "url_produttore", "prezzo_produttore", "formato_produttore",
    "prezzo_produttore_al_kg", "differenza_pct", "somiglianza", "ingredienti_confrontati", "data", "nota",
    "cod_art_delivery", "nome_delivery",
]
DATA = "2026-10-25"


def riga(*, nome, cod, nome_delivery, p_peck, f_peck, kg_peck, azienda, nome_prod, url, p_prod, f_prod, kg_prod,
         sim, ingr, nota, chiave=""):
    dp = (kg_peck / kg_prod - 1) * 100
    return {
        "nome_peck": nome, "chiave_dispensa": chiave, "prezzo_peck": f"{p_peck:g}", "formato_peck": f_peck,
        "prezzo_peck_al_kg": f"{kg_peck:.2f}", "azienda": azienda, "nome_produttore": nome_prod,
        "url_produttore": url, "prezzo_produttore": f"{p_prod:g}", "formato_produttore": f_prod,
        "prezzo_produttore_al_kg": f"{kg_prod:.2f}", "differenza_pct": f"{dp:+.1f}",
        "somiglianza": sim, "ingredienti_confrontati": ingr, "data": DATA, "nota": nota,
        "cod_art_delivery": cod, "nome_delivery": nome_delivery,
    }


def righe():
    out = []

    # --- Orcio Peck «Fruttato intenso» (Coratina) x Frantoio Muraglia (stesso fornitore dell'orcio «Fruttato medio»)
    muraglia = "Muraglia Savino & C. Società Agricola Semplice"
    out.append(riga(
        nome="ORCIO PECK - OLIO EXTRA VERGINE DI OLIVA FRUTTATO INTENSO 500 ML", cod="3839",
        nome_delivery="ORCIO PECK - OLIO EXTRA VERGINE DI OLIVA FRUTTATO INTENSO 500 ML",
        p_peck=45, f_peck="500 ml", kg_peck=90.0, azienda=muraglia,
        nome_prod="Orcio in ceramica arcobaleno, Fruttato Intenso (Coratina)",
        url="https://www.frantoiomuraglia.it/prodotto/orcio-ceramica-arcobaleno/",
        p_prod=38, f_prod="500 ml", kg_prod=76.0, sim="molto simile", ingr="si",
        nota=("Prezzi e «al kg» sono al litro (ml, non peso). Peck: 45 € dal delivery del 25 ottobre 2026 "
              "(cod. 3839; 100% olio EVO monocultivar Coratina, «Prodotto italiano»); non è nello shop online. "
              "Muraglia: 38 € per l'orcio Arcobaleno nella variante Fruttato Intenso (la pagina ha due varianti, "
              "Medio e Intenso, allo stesso prezzo); la scheda della bottiglia «Essenza Fruttato Intenso» dice "
              "monocultivar Coratina. Stesso olio descritto allo stesso modo e stesso formato, ma non possiamo "
              "provare che l'orcio Peck sia il disegno Arcobaleno (Muraglia ne vende molti: gli orci d'autore «Il "
              "Re» e «Il Bacio», anche loro Fruttato Intenso, costano 47 €), quindi non «stesso prodotto». "
              "Il legame Peck-Muraglia viene dall'indirizzo dell'etichetta del novembre 2025 (vedi risultati_6).")))
    out.append(riga(
        nome="ORCIO PECK - OLIO EXTRA VERGINE DI OLIVA FRUTTATO INTENSO 500 ML", cod="3839",
        nome_delivery="ORCIO PECK - OLIO EXTRA VERGINE DI OLIVA FRUTTATO INTENSO 500 ML",
        p_peck=45, f_peck="500 ml", kg_peck=90.0, azienda=muraglia,
        nome_prod="Essenza Fruttato Intenso 500 ml (bottiglia, Coratina)",
        url="https://www.frantoiomuraglia.it/prodotto/fruttato-intenso-500ml/",
        p_prod=19.5, f_prod="500 ml", kg_prod=39.0, sim="simile", ingr="si",
        nota=("Prezzi al litro. Stessa monocultivar Coratina di Muraglia in bottiglia di vetro, senza orcio in "
              "ceramica: la differenza con l'orcio Peck è in buona parte il contenitore.")))

    # --- Jamón «a coltello» (bollo di Joselito) x Joselito Gran Reserva affettato
    out.append(riga(
        nome="JAMON IBERICO DE BELLOTA A COLTELLO", cod="116",
        nome_delivery="JAMON IBERICO DE BELLOTA A COLTELLO",
        p_peck=390, f_peck="al kg (tagliato a coltello)", kg_peck=390.0,
        azienda="Cárnicas Joselito, S.A.",
        nome_prod="Jamón Joselito Gran Reserva Loncheado 70 g",
        url="https://joselito.com/products/jamon-gran-reserva-loncheado",
        p_prod=29.5, f_prod="70 g", kg_prod=421.43, sim="simile", ingr="no",
        nota=("Prezzo Peck dal delivery (cod. 116): 390 € al kg, prosciutto venduto al kg, tagliato a coltello; ingredienti "
              "«carne di suino, sale marino», etichetta con il bollo ES 10.20191/SA CE, che è lo stabilimento di "
              "Joselito a Guijuelo (lo stesso dei quattro prodotti Joselito di risultati_2). Il nome Peck non cita "
              "Joselito né «Gran Reserva». Joselito vende il Gran Reserva (48 mesi di stagionatura) affettato in "
              "blister da 70 g a 29,5 € (421,43 € al kg; la pagina dice «contattare per acquistare» e il prodotto "
              "risulta non disponibile online). Non è lo stesso prodotto: tagliato a coltello contro blister, e non "
              "sappiamo se il prosciutto di Peck sia il Gran Reserva. Lo mettiamo perché è l'unico prezzo Joselito "
              "al kg che si può confrontare. Per il blister Gran Reserva da 70 g Peck chiede 514,29 € al kg (+22%, "
              "risultati_2).")))

    # --- Creme di tartufo (Tartuflanghe, tubetto 30 g)
    tl = "Tartuflanghe S.r.l."
    out.append(riga(
        nome="CREMA DI PURO TARTUFO D'ESTATE 90 G", cod="3630",
        nome_delivery="CREMA DI PURO TARTUFO D'ESTATE 90 G",
        p_peck=40, f_peck="90 g", kg_peck=444.44, azienda=tl,
        nome_prod="PURE' DI TARTUFO D'ESTATE 95% (Tuber aestivum Vitt.), tubetto 30 g",
        url="https://shop.tartuflanghe.com/products/copia-del-pure-di-tartufo-destate-99-tuber-aestivum-vitt-30g",
        p_prod=17.6, f_prod="30 g (dall'indirizzo della pagina «…-30g»)", kg_prod=586.67, sim="simile", ingr="no",
        nota=("Peck: 40 € dal delivery (cod. 3630, vasetto da 90 g; tartufo d'estate 90%, olio di girasole, sale, "
              "aroma; «Prodotto in via Arese 11, Milano»). Tartuflanghe: purè di tartufo d'estate 95% in tubetto, "
              "17,60 €; il peso non è scritto nel catalogo scaricato, ma l'indirizzo della pagina dice «30g» "
              "(come per il purè di tartufo bianco di risultati_1, dove la crema bianca Peck porta il bollo IT "
              "9-2631/L CE di Tartuflanghe). Per la crema d'estate l'etichetta delivery ha solo Via Arese 11, "
              "non collegata a nessuna azienda: il legame con Tartuflanghe è per analogia con la crema bianca, "
              "non provato, e gli ingredienti Tartuflanghe non sono nel catalogo. Per questo «simile». Al "
              "chilo Peck costa meno, perché vende un vasetto più grande a un prezzo non proporzionale.")))

    # --- Condimento al tartufo bianco 250 ml (Tartuflanghe «Oro in cucina»)
    out.append(riga(
        nome="CONDIMENTO AROMATIZZATO AL TARTUFO BIANCO 25 cl", cod="3528",
        chiave="condimento-aromatizzato-al-tartufo-bianco-25-cl",
        nome_delivery="CONDIMENTO AROMATIZZATO AL TARTUFO BIANCO 250 ML",
        p_peck=24, f_peck="250 ml", kg_peck=96.0, azienda=tl,
        nome_prod="ORO IN CUCINA Condimento a base di olio extra vergine d'oliva aromatizzato al tartufo bianco 250 ml",
        url="https://shop.tartuflanghe.com/products/oro-in-cucina-olio-aromatizzato-tartufo-bianco-alba-langhe-latta",
        p_prod=28.8, f_prod="250 ml (lattina)", kg_prod=115.2, sim="simile", ingr="si",
        nota=("Prezzi al litro. Peck: 24 € dal delivery (cod. 3528; «olio di oliva 99,5% (origine UE), aroma», "
              "senza «extra vergine»; «Prodotto in Via Arese 11, Milano»). Tartuflanghe: olio extra vergine di oliva "
              "100% italiano con aroma naturale, lattina da 250 ml. Stessa idea e stesso formato, ma l'olio non è lo "
              "stesso (Peck non dice extra vergine né italiano) e il legame con Tartuflanghe passa solo dall'"
              "indirizzo Via Arese 11, non collegato a nessuna azienda: «simile».")))
    return out


def main():
    rows = righe()
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    with open(USCITA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} righe -> {USCITA}")
    for r in rows:
        print(f"  {r['somiglianza']:<14} {r['differenza_pct']:>7}%  {r['nome_peck'][:60]}")


if __name__ == "__main__":
    main()
