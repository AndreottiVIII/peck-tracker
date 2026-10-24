# Peck tracker: chi produce quello che vende Peck Milano

Peck e' la gastronomia di lusso di Milano (via Spadari 9). Su quasi tutti i suoi prodotti c'e' il
suo marchio, ma qualcuno li fa: un forno, un pastificio, un salumificio, una cantina. Questo
progetto cerca di capire **chi** e **dove**, usando fonti pubbliche e dicendo sempre quanto siamo
sicuri. Ci sono tre pezzi: lo shop online (passo 1), le aziende dietro gli indirizzi (passo 2) e
la carta dei vini dell'enoteca.

## Cosa trovi qui

Tutti i file sono in `data/` e si aprono bene anche con Excel (UTF-8 con BOM).

- `prodotti.csv`, `elementi.csv`, `indirizzi.csv`, `altre_origini.csv`: dove Peck dice che sono
  prodotti i 46 articoli dello shop (passo 1).
- `aziende.csv`: le aziende dietro quegli indirizzi, bolli CE e produttori nominati, 100 righe con
  la fonte e quanto siamo sicuri (passo 2).
- `vini.csv`: i 3.071 vini della carta dell'enoteca, una riga per formato (3.082 righe).
- `cantine.csv`: le 820 cantine della carta, con quante etichette hanno.
- `vini_nelle_box.csv`: i produttori di vino nominati nelle box dello shop, confrontati con la carta.

## Passo 1: dove viene prodotto quello che Peck vende online

Questo passo raccoglie, per ogni prodotto in vendita su https://shop.peck.it, **dove dice di essere
prodotto**, usando soltanto le frasi che Peck stessa scrive nella scheda del prodotto ("Prodotto
in via ...", "Confezionato da ...", il bollo CE degli stabilimenti). Non ci sono mappe e non si
cerca di capire chi sono i fornitori: quello e' il passo 2.

### I dati

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

#### L'indirizzo di Peck

Via Spadari 9, Milano e' la sede legale di Peck e compare quasi ovunque come titolare del marchio:
**non e' un luogo di produzione** e infatti non finisce nei campi indirizzo (per esempio da
"Spumantizzato da TV 1000 per PECK S.P.A. VIA SPADARI 9" nei campi resta solo TV 1000; la frase
resta intera in `frase_origine`). Compare in `elementi.csv` e in
`indirizzi.csv` (colonna `sede_peck` = `si`) solo dove una frase dice esplicitamente che il prodotto
e' prodotto o confezionato li' ("Confezionato in: via Spadari 9", "Prodotto e confezionato da
Peck S.p.A. ..."). In `indirizzi.csv` quella riga e' messa in fondo.

### Limiti del passo 1

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

## Passo 2: chi c'e' dietro gli indirizzi

`data/aziende.csv` ha 100 righe: 67 indirizzi di produzione, 22 bolli CE e 11 produttori nominati
(vini compresi). Per ognuna: `tipo_chiave` (`indirizzo`, `bollo_ce` o `produttore`), `chiave` (l'indirizzo,
il codice o il nome cosi' come sta nei dati del passo 1), `ragione_sociale`, `marchio`, `sito`,
`shop_online` (`si`, `no` o `non verificato`), `link_shop`, `fonte`, `certezza`, `prodotti_peck` (i
prodotti Peck collegati) e `nota`.

Non e' stato compilato da un programma: e' una ricerca sul web fatta a mano, **con una fonte per
riga** (colonna `fonte`). Come leggere la colonna `certezza`:

- `certa` (72 righe): una fonte mostra proprio quell'indirizzo o quel codice con quell'azienda.
- `probabile` (7 righe): l'indizio e' forte ma indiretto.
- `non trovata` (21 righe): non siamo riusciti a risalire all'azienda.

`shop_online = no` vuol dire solo che sul sito ufficiale non abbiamo trovato un negozio online:
non e' una prova che non esista.

Molte di queste aziende sono **produttori per conto terzi**: fanno il prodotto che poi Peck vende
con il suo marchio. Qualche esempio: il Panificio Follador di Pordenone per i lievitati (panettoni,
pandoro, veneziana), Walcor (Pozzaglio ed Uniti, Cremona) per le monete di cioccolato, Callipo per il
tonno, Joselito per il jamon iberico, Riso Gallo per il riso, Tartuflanghe per i prodotti al tartufo,
Agrimontana per i marron glaces, Dethlefsen & Balk (Amburgo) per il te'.

### I bolli CE (programma `src/bolli.py`)

Il bollo CE ovale (per esempio "IT 586 L CE") dice che lo stabilimento e' riconosciuto per
lavorare carne, pesce, latticini o uova, ma non dice dove sta ne' di chi e'. Il programma scarica gli
elenchi pubblici della Commissione europea (TRACES) degli stabilimenti riconosciuti
(Reg. CE 853/2004) per Italia e Spagna, e vi cerca i codici trovati nel passo 1. Il sito del
Ministero della Salute (SINTESIS) blocca i download automatici; gli elenchi europei contengono le
stesse autorizzazioni. I file scaricati finiscono in `data/raw/sintesis/` e non si pubblicano.

```
python -I src/bolli.py scarica   # scarica gli elenchi di Italia e Spagna
python -I src/bolli.py cerca     # abbina i codici di data/altre_origini.csv e stampa i risultati
```

### Limiti del passo 2

- **21 righe senza risposta.** In parte perche' la ricerca ha esaurito il tempo a disposizione: si
  possono riprovare.
- **Refusi di Peck negli indirizzi**: Legnano al posto di Legnago, Borgomanaro al posto di Borgomaro,
  Ortobello al posto di Orbetello.
- **Non tutti i codici sono bolli sanitari**: "IT CN 9744" e "TV 1000" sono codici di chi
  imbottiglia il vino, e "IT00ATA00023D" sembra un codice delle accise.
- Un'azienda trovata a un indirizzo puo' essere chi confeziona e non chi fabbrica (vedi i limiti del
  passo 1).

## La carta dei vini dell'enoteca

La pagina dell'enoteca (https://peck.it/enoteca/) mostra una carta dei vini gestita da Winerim
(https://web.winerim.com/enotecapeck). Il programma `src/vini.py` la scarica dall'interfaccia dati
pubblica di Winerim (una richiesta alla volta, con 2 secondi di pausa) in `data/raw/winerim/` e
scrive:

- `vini.csv`: 3.082 righe per 3.071 vini, una riga per formato. Colonne: `id`, `nome`, `annata`,
  `tipo`, `codice_paese`, `paese`, `regione`, `cantina`, `uve`, `formato`, `variante`,
  `prezzo_euro`, `in_stock`, `link`, `nota`.
- `cantine.csv`: 820 cantine con paese, regioni, numero di etichette (totale e per tipo: rossi,
  bianchi, spumanti, dolci, rosati, liquorosi) e prezzo minimo e massimo.
- `vini_nelle_box.csv` (scritto da `src/vini_box.py`): i 13 produttori di vino nominati nelle box
  dello shop, confrontati con la carta. 11 ci sono; **Nonino** (distillati) e **TV 1000** (che
  spumantizza il Prosecco Peck) no. La colonna `corrispondenza` dice se la cantina e' identica
  (`esatta`), collegata con un altro nome (`approssimata`) o assente (`non in carta`).

Qualche numero: le cantine con piu' etichette sono Gaja (68), Domaine de La Romanee-Conti (67),
Tenuta San Guido (64), Giacomo Conterno (56) e Chateau d'Yquem (47). Per paese, la Francia ha 1.607
righe e l'Italia 1.233. Non salviamo foto ne' note di degustazione.

### Limiti della carta dei vini

- **I numeri non tornano con il sito.** L'intestazione della carta parla di 1.005 cantine e circa 4.676
  vini (2.735 rossi, 1.124 bianchi...), ma l'interfaccia pubblica ne restituisce solo 3.071, di 820
  cantine. I totali dell'intestazione vengono da un elenco di filtri che include anche cantine che
  non compaiono mai fra i vini. Forse sono vini archiviati o nascosti: non lo sappiamo.
- **E' una fotografia del 24 ottobre 2026.** I prezzi e i vini disponibili cambiano.
- Il confronto con le box e' fatto per nome: va controllato a occhio dove la corrispondenza non e' esatta.

## Come rifare tutto

Servono Python 3.12, `requests` e `beautifulsoup4`. Dalla cartella `peck-tracker`, nell'ordine:

```
python -I src/fetch.py          # passo 1: scarica le pagine in data/raw/ (circa 10 minuti la prima volta)
python -I src/extract.py        # passo 1: scrive i quattro file CSV del passo 1 in data/
python -I src/bolli.py scarica  # passo 2: scarica gli elenchi UE degli stabilimenti (Italia e Spagna)
python -I src/bolli.py cerca    # passo 2: abbina i bolli CE
python -I src/vini.py           # vini: scarica la carta dell'enoteca, scrive vini.csv e cantine.csv
python -I src/vini_box.py       # vini: confronta le box con la carta, scrive vini_nelle_box.csv
```

`aziende.csv` non si rigenera con un programma: e' la ricerca a mano descritta sopra.

`fetch.py` aspetta 10 secondi fra una richiesta e l'altra (e' il `Crawl-delay` che lo shop
dichiara in robots.txt; si cambia con `--pausa 1`), salta i file gia' scaricati (con `--forza` li
riscarica) e legge solo le pagine in italiano. Parte dall'elenco `/it/negozio-online` (pagine 0-3)
e, per controllo, dall'elenco `/it/negozio-online/gift-box`: contengono gli stessi 46 prodotti. Lo
shop ha una sola categoria ("Gift box"); le pagine singole (panettoni, pandoro, veneziana, salmone,
frutta disidratata) sono nello stesso elenco.
