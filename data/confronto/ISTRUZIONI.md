# Confronto prezzi Peck / produttore — istruzioni comuni

Progetto "Peck Tracker" (leggi README.md e JOURNAL.md). Per ogni prodotto venduto da Peck di cui
conosciamo il produttore, cerchiamo **lo stesso prodotto (o uno molto simile) venduto dal produttore
sul proprio sito/shop**, con il suo prezzo, e lo confrontiamo con il prezzo Peck.

Esempio che ha fatto partire tutto: Peck vende "Salsa di funghi porcini 180 g" a 16 € (delivery);
il produttore Inaudi (Borgo San Dalmazzo, l'indirizzo stampato sull'etichetta Peck) vende sul suo
shop "Crema di funghi porcini" vaso 180 g a 9,50 €.

## Dati da usare
- Il tuo gruppo di produttori: `data/confronto/gruppo_N.json` (azienda, sito, link_shop, prodotti
  Peck che fanno).
- Prezzi Peck: `data/delivery_dispensa.csv` (prezzo, unita KG/PZ, formato) per 60 prodotti; per gli
  altri prodotti Peck il prezzo singolo non c'e' (stanno solo nelle box: `data/prodotti.csv` ha il
  prezzo della box intera). Nomi e formati dei prodotti Peck: `data/elementi.csv`.
- Il catalogo completo del delivery (503 prodotti, prezzi, ingredienti) e' in
  `data/locale/delivery_catalogo_2026-10-25.json`: usalo per trovare prezzi Peck di prodotti dello
  stesso produttore anche se non sono nella Dispensa (es. altri sughi Inaudi), e gli ingredienti per
  confrontare le ricette.

## Come cercare (scaricare non richiede permessi)
- Prima il catalogo pubblico del produttore, intero, in `data/raw/confronto/<dominio>/`: Shopify
  `/products.json?limit=250&page=N`, WooCommerce `/wp-json/wc/store/v1/products?per_page=100&page=N`,
  sitemap prodotti, oppure le pagine prodotto. Controlla prima `robots.txt` e rispettalo; pausa 1-2 s.
  Niente login, niente aggiramento di blocchi anti-bot (se un sito blocca, segnalo e passa oltre).
  Se il robots.txt ha una sezione per ClaudeBot, Claude-Web, Claude-User, anthropic-ai o altri
  agenti AI che vieta dei percorsi, quei percorsi NON si scaricano, nemmeno cambiando User-Agent:
  il produttore resta "non verificato" (confronto da fare a mano). Casi noti: fornofollador.it,
  casaiuorio.it.
- Poi abbina: stesso tipo di prodotto, stesso formato (grammi/ml) o il piu' vicino; confronta anche
  gli ingredienti quando li hai (etichetta Peck nel catalogo delivery vs scheda del produttore).
- Se il produttore non ha shop ma vende tramite rivenditori, NON cercare altrove: segna
  "nessun prezzo dal produttore".

## Livelli di somiglianza (colonna `somiglianza`)
- `stesso prodotto`: stesso produttore, stesso tipo, stesso formato, ingredienti uguali o quasi
  (es. funghi porcini 79%/80%).
- `molto simile`: stesso produttore e tipo, formato o ricetta un po' diversi (spiega in nota).
- `simile`: stesso produttore, prodotto della stessa famiglia (es. altra crema di funghi).
Mai dire "stesso prodotto" senza prova: in caso di dubbio scendi di livello.

## Output: `data/confronto/risultati_N.csv` (UTF-8 con BOM)
Colonne: nome_peck, chiave_dispensa (se il prodotto e' nella Dispensa: vedi come la costruisce
src/sito.py / data/delivery_dispensa.csv), prezzo_peck, formato_peck, prezzo_peck_al_kg,
azienda, nome_produttore, url_produttore, prezzo_produttore, formato_produttore,
prezzo_produttore_al_kg, differenza_pct (Peck rispetto al produttore, al kg o al litro),
somiglianza, ingredienti_confrontati (si/no), data (2026-10-25), nota.
Una riga per prodotto Peck (anche quelli senza esito: somiglianza = "non trovato" con nota).

Non toccare src/sito.py, docs/, README.md: un altro agente mettera' tutto sul sito. Niente git.

## Rapporto finale (breve)
Produttori controllati, quanti con catalogo scaricato, i confronti trovati per livello, i 5 casi con
la differenza maggiore, i siti che bloccavano.
