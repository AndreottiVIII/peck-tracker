# Peck tracker, passo 1: dove viene prodotto quello che Peck vende online

Questo passo raccoglie, per ogni prodotto in vendita su https://shop.peck.it, **dove dice di essere
prodotto**, usando soltanto le frasi che Peck stessa scrive nella scheda del prodotto ("Prodotto
in via ...", "Confezionato da ...", il bollo CE degli stabilimenti). Non ci sono mappe e non si
cerca di capire chi sono i fornitori: quello e' il passo 2, da fare a parte con le fonti.

## I dati

Le tabelle sono in `data/`. I file si aprono bene anche con Excel (UTF-8 con BOM).

- `prodotti.csv`: una riga per pagina prodotto (46 pagine). Colonne: `url`, `nome`, `tipo`
  (`box` se la scheda contiene piu' prodotti, `singolo` se ne contiene uno), `prezzo` (euro, con
  il punto decimale), `numero_elementi` (quanti prodotti ci sono nella scheda), `categoria`.
- `elementi.csv`: il cuore. Un "elemento" e' un prodotto realmente fabbricato: un prodotto singolo
  e' un elemento, una box ne contiene tanti (ognuno con la sua scheda). C'e' **una riga per ogni
  frase di origine** di ogni elemento, quindi un elemento con due frasi diverse (per esempio
  "prodotto in A" e "confezionato in B") ha due righe. Un elemento senza nessuna frase di origine
  ha una riga sola con i campi vuoti e la nota "nessuna frase di origine nel testo".
  Colonne: `url_pagina`, `nome_pagina`, `nome_elemento`, `ruolo` (la parola usata: prodotto,
  confezionato, imbottigliato, spumantizzato...), `frase_origine` (la frase, copiata identica),
  `indirizzo`, `cap`, `comune`, `provincia`, `paese`, `produttore_nominato` (solo se il testo
  nomina un'azienda), `bollo_ce` (il codice dello stabilimento, tipo "IT 3 L CE"), `sede_peck`
  (vedi sotto), `nota`.
- `indirizzi.csv`: gli indirizzi di produzione unici, con quante pagine, quanti prodotti diversi
  e quante frasi puntano a ciascuno, e l'elenco dei nomi dei prodotti. Scritture leggermente
  diverse dello stesso indirizzo (per esempio "Napoleoni" / "Mapoleoni") sono unite.
- `altre_origini.csv`: le origini che non hanno un indirizzo: bolli CE (con l'elenco dei prodotti
  che li portano), produttori nominati senza indirizzo (soprattutto vini: Krug, Berlucchi...) e
  frasi che dicono solo "Prodotto in Italia".

Non salviamo ingredienti, descrizioni, foto o testi di Peck: solo le frasi brevi sull'origine. Le
pagine scaricate (`data/raw/`) restano sul computer e non vanno pubblicate (sono escluse da
`.gitignore`).

### L'indirizzo di Peck

Via Spadari 9, Milano e' la sede legale di Peck e compare quasi ovunque come titolare del marchio:
**non e' un luogo di produzione** e infatti non finisce nei campi indirizzo (per esempio da
"Spumantizzato da TV 1000 per PECK S.P.A. VIA SPADARI 9" nei campi resta solo TV 1000; la frase
resta intera in `frase_origine`). Compare in `elementi.csv` e in
`indirizzi.csv` (colonna `sede_peck` = `si`) solo dove una frase dice esplicitamente che il prodotto
e' prodotto o confezionato li' ("Confezionato in: via Spadari 9", "Prodotto e confezionato da
Peck S.p.A. ..."). In `indirizzi.csv` quella riga e' messa in fondo.

## Come rifare tutto

Servono Python 3.12, `requests` e `beautifulsoup4`. Dalla cartella `peck-tracker`:

```
python -I src/fetch.py       # scarica le pagine in data/raw/ (circa 10 minuti la prima volta)
python -I src/extract.py     # scrive i quattro file CSV in data/
```

`fetch.py` aspetta 10 secondi fra una richiesta e l'altra (e' il `Crawl-delay` che lo shop
dichiara in robots.txt; si cambia con `--pausa 1`), salta i file gia' scaricati (con `--forza` li
riscarica) e legge solo le pagine in italiano. Parte dall'elenco `/it/negozio-online` (pagine 0-3)
e, per controllo, dall'elenco `/it/negozio-online/gift-box`: contengono gli stessi 46 prodotti. Lo
shop ha una sola categoria ("Gift box"); le pagine singole (panettoni, pandoro, veneziana, salmone,
frutta disidratata) sono nello stesso elenco.

## Limiti da tenere presenti

- **Solo cio' che e' in vendita online adesso**, e adesso e' la stagione natalizia ("Selezioni
  Natalizie"): il catalogo cambia. Alcune box dicono "ordinabile dal 15 ottobre 2026".
- **Un indirizzo puo' essere quello di chi confeziona, non di chi fabbrica.** Peck scrive "prodotto
  in", "prodotto e confezionato in", "confezionato da" senza spiegare la differenza; la colonna
  `ruolo` conserva la parola usata. Nessun nome d'azienda e' ricavato dall'indirizzo.
- **Elementi senza frase di origine**: ce ne sono (cioccolatini e praline, tavolette, il pecorino
  in grotta, la bresaola, un vino Frescobaldi...). Per alcuni c'e' solo "PECK S.P.A. via Spadari 9"
  come titolare. Restano in tabella con i campi vuoti.
- **Il bollo CE dice dove e' lo stabilimento, ma non dove e' l'indirizzo**: bisogna cercarlo (passo
  2). Alcuni codici sono senza la sigla CE (per esempio "IT CN 9744" e "IT00ATA00023D") e sono
  segnati nella colonna `nota`.
- **Le box sono lette dalle schede prodotto**, non dalla descrizione: una box che elenca un
  prodotto nella descrizione ma non ha la sua scheda (per esempio la "Moneta di cioccolato" nella
  box Cometa) non lo ha in tabella. Gli oggetti non alimentari (scatola, filtro per il te') non
  hanno scheda e non sono contati.
- **Gli stessi prodotti compaiono in molte box**: per contare i prodotti reali si guardino i
  nomi distinti, non le righe.
- **Errori di battitura di Peck**: i testi originali hanno refusi ("Mapoleoni", "vuia Volterra",
  "Ortobello"/"Orbetello", "Dalmazzzo"); le frasi sono copiate come sono. Dove le due scritture
  indicano chiaramente lo stesso posto la riga e' una sola e l'altra scrittura sta nella `nota`.
- **Separazione dei campi**: il programma spezza gli indirizzi con regole semplici; tre frasi
  scritte in modo confuso sono corrette a mano nel dizionario `CORREZIONI` in `src/extract.py`
  (la `nota` lo dice). Per altre (per esempio "Via Alfieri 16, loc. Oriolo" o "Reg. Prati e Pescine")
  il confine fra indirizzo e comune puo' essere approssimato: la `frase_origine` e' sempre quella vera.
- Quando una scheda ha due luoghi diversi per lo stesso prodotto (la pasta, per esempio, dice sia
  Gragnano sia Roseto degli Abruzzi), tutti e due sono in tabella: non abbiamo scelto noi quale
  sia "il vero".
