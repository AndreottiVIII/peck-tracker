# Peck tracker: chi produce quello che vende Peck Milano

Peck e' la gastronomia di lusso di Milano (via Spadari 9). Su quasi tutti i suoi prodotti c'e' il
suo marchio, ma qualcuno li fa: un forno, un pastificio, un salumificio, una cantina. Questo
progetto cerca di capire **chi** e **dove**, usando fonti pubbliche e dicendo sempre quanto siamo
sicuri. Ci sono tre pezzi: lo shop online (passo 1), le aziende dietro gli indirizzi (passo 2) e
la carta dei vini dell'enoteca.

**Il sito: https://andreottiviii.github.io/peck-tracker/** — un catalogo da sfogliare come un
negozio online, ma senza niente in vendita: per ogni prodotto dice chi lo fa e dove, per ogni
bottiglia dell'enoteca cos'e'.

Progetto indipendente di appassionati, non affiliato a Peck. Nessun prodotto in vendita.

## Cosa trovi qui

Tutti i file sono in `data/` e si aprono bene anche con Excel (UTF-8 con BOM).

- `prodotti.csv`, `elementi.csv`, `indirizzi.csv`, `altre_origini.csv`: dove Peck dice che sono
  prodotti i 46 articoli dello shop (passo 1).
- `aziende.csv`: le aziende dietro quegli indirizzi, bolli CE e produttori nominati, 100 righe con
  la fonte e quanto siamo sicuri (passo 2).
- `vini.csv`: i 3.071 vini della carta dell'enoteca, una riga per formato (3.082 righe).
- `cantine.csv`: le 820 cantine della carta, con quante etichette hanno.
- `vini_nelle_box.csv`: i produttori di vino nominati nelle box dello shop, confrontati con la carta.
- `tannico.csv` e `tannico_voti.csv`: il vino di Tannico abbinato a ogni vino della carta e i voti presi dalla sua
  scheda (vedi "La carta dei vini" e "Il sito").
- `link_controllati.csv` (e `link_verifica_manuale.csv`): l'esito del controllo dei link ai siti, agli
  shop e alle fonti delle aziende (vedi "Il controllo dei link").

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

- `certa` (77 righe): una fonte mostra proprio quell'indirizzo o quel codice con quell'azienda.
- `probabile` (7 righe): l'indizio e' forte ma indiretto.
- `non trovata` (16 righe): non siamo riusciti a risalire all'azienda.

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

- **16 righe senza risposta**, anche dopo un secondo giro di ricerca: soprattutto aceto, olive,
  olio e conserve, piu' i codici degli imbottigliatori. Le note dicono cosa e' stato provato. Per
  chiuderle servirebbero una visura camerale per indirizzo, l'etichetta in mano o una richiesta
  all'ICQRF (che assegna i codici degli imbottigliatori).
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
  `prezzo_euro`, `in_stock`, `link`, `nota`, poi il profilo di degustazione da 0 a 5 come lo scrive
  Winerim (`intensita`, `freschezza`, `dolcezza`, `tannicita`, `fruttato`, `affinamento`; vuoto se
  non indicato) e, dalla scheda di ogni vino, `gradazione`, `temperatura_servizio`, `bere_da`,
  `bere_fino_a`, `picco_da`, `picco_a`, `abbinamenti` (tradotti in italiano).
- `cantine.csv`: 820 cantine con paese, regioni, numero di etichette (totale e per tipo: rossi,
  bianchi, spumanti, dolci, rosati, liquorosi) e prezzo minimo e massimo.
- `vini_nelle_box.csv` (scritto da `src/vini_box.py`): i 13 produttori di vino nominati nelle box
  dello shop, confrontati con la carta. 11 ci sono; **Nonino** (distillati) e **TV 1000** (che
  spumantizza il Prosecco Peck) no. La colonna `corrispondenza` dice se la cantina e' identica
  (`esatta`), collegata con un altro nome (`approssimata`) o assente (`non in carta`).

Con `python -I src/vini.py --dettagli` il programma scarica anche la scheda di ogni vino
(`data/raw/winerim/vini/<id>.json`, una richiesta al secondo, circa un'ora; le schede gia' scaricate
si saltano) per le colonne dopo `affinamento`. Quelle schede contengono anche testi lunghi
(note di degustazione, storia della cantina) che sono prosa di Winerim: restano in `data/raw/`, che non
si pubblica, e **non vengono copiati** ne' nei CSV ne' nel sito: per quelli il sito rimanda alla
«Scheda completa in enoteca». Nei dati strutturati molti valori sono di massima (per esempio circa un
terzo dei vini ha gradazione 13,5): il sito lo dice.

Qualche numero: le cantine con piu' etichette sono Gaja (68), Domaine de La Romanee-Conti (67),
Tenuta San Guido (64), Giacomo Conterno (56) e Chateau d'Yquem (47). Per paese, la Francia ha 1.607
righe e l'Italia 1.233. Non salviamo foto ne' testi descrittivi.

### Limiti della carta dei vini

- **I numeri non tornano con il sito.** L'intestazione della carta parla di 1.005 cantine e circa 4.676
  vini (2.735 rossi, 1.124 bianchi...), ma l'interfaccia pubblica ne restituisce solo 3.071, di 820
  cantine. I totali dell'intestazione vengono da un elenco di filtri che include anche cantine che
  non compaiono mai fra i vini. Forse sono vini archiviati o nascosti: non lo sappiamo.
- **E' una fotografia del 24 ottobre 2026.** I prezzi e i vini disponibili cambiano.
- Il confronto con le box e' fatto per nome: va controllato a occhio dove la corrispondenza non e' esatta.

## Il controllo dei link

`python -I src/controlla_link.py` apre ogni link di `data/aziende.csv` (colonne `sito`, `link_shop`,
`fonte`) e un campione di 40 link dei vini (`--vini-tutti` li fa tutti: circa un'ora, un secondo di
pausa per sito) con un browser finto: segue i reindirizzamenti, 15 secondi di attesa, un secondo
tentativo, e scrive `data/link_controllati.csv` con `url`, `campo`, `chiave`, `status`, `url_finale`,
`esito` (`ok`, `rotto`, `bloccato`, `dominio_parcheggiato`, `errore`) e `nota`.

- **Un link `rotto` o `dominio_parcheggiato` non diventa mai un bottone nel sito** (lo decide
  `src/sito.py` leggendo questo file).
- `bloccato` (401, 403, 429, pagine anti-robot) e `errore` (il nome del sito non si trova da questo
  computer) vanno guardati a mano: gli esiti decisi a mano stanno in `data/link_verifica_manuale.csv`
  e hanno la precedenza.
- Quando un link `sito` o `link_shop` e' rotto si cerca la vera home dell'azienda e si corregge
  `aziende.csv` solo se si apre il nuovo indirizzo e si vede che e' proprio il suo negozio (la
  colonna `nota` dice cosa e' cambiato); altrimenti si svuota `link_shop` e `shop_online` diventa
  `non verificato`.

## Il sito

Sta in `docs/` ed e' pubblicato con GitHub Pages (ramo `main`, cartella `/docs`). **Ogni pagina ha un
indirizzo vero** (una cartella con dentro `index.html`), come un sito normale: "Indietro" e "Avanti"
del browser funzionano, e ogni pagina ha il suo titolo e la sua descrizione. I link sono tutti relativi,
quindi va bene sia sotto `/peck-tracker/` su GitHub Pages sia alla radice di un server locale.

| Indirizzo | Che pagina e' | Quante |
| --- | --- | --- |
| `index.html`, `dispensa/` | la Dispensa (194 prodotti, filtri, Schede / Elenco) | 2 |
| `prodotto/<id>/` | un prodotto: chi lo fa, dove, la frase di Peck, le box in cui sta | 194 |
| `box/`, `box/<id>/` | le 46 pagine dello shop, "spacchettate" | 1 + 46 |
| `produttori/`, `produttore/<id>/` | le aziende, con fonti e prodotti | 1 + 90 |
| `enoteca/` | i 3.071 vini, con filtri e Schede / Elenco | 1 |
| `cantina/<id>/` | una cantina e le sue etichette | 820 |
| `vino/<id>-<nome>/` | un vino: foto, profilo di degustazione (punti e grafico a ragnatela), formati e prezzi, vini correlati, bottoni Vivino / Wine-Searcher / scheda completa in enoteca | 3.071 |
| `come-funziona/`, `404.html` | spiegazioni, limiti, link controllati | 2 |

Le pagine di prodotti, box, produttori, cantine e vini sono HTML completo, si leggono anche senza
JavaScript. Le liste (Dispensa, Box, Produttori, Enoteca) filtrano con un po' di JavaScript
(`docs/app.js`) e **tengono i filtri nell'indirizzo** (`?q=tartufo&cat=salumi&vista=elenco`), cosi'
aprendo un prodotto e premendo "Indietro" si torna alla stessa lista filtrata. `?vista=elenco` e' la
vista a righe (una riga per voce, con foto piccola); senza e' la vista a schede. Gli indirizzi vecchi
con `#/` rimandano alle pagine nuove. L'Enoteca legge `docs/vini.json` (dati compatti per i filtri).

I bottoni **Vivino** e **Wine-Searcher** di ogni vino aprono una *ricerca* sui loro siti
(`vivino.com/search/wines?q=<cantina + nome>` e `wine-searcher.com/find/<parole+unite>/<annata>`):
non copiamo punteggi.

Il bottone **Tannico** viene da `data/tannico.csv` (prodotto da `src/tannico.py`, che scarica il catalogo
pubblico di Tannico e lo abbina ai vini per nome). Corrispondenza `esatta`: bottone «Tannico» con il link
alla scheda; `annata diversa`: stesso bottone con la nota «su Tannico c'e' l'annata ...» (l'anno si legge
da `titolo_tannico`); `da controllare` e `nessuna`: bottone «Cerca su Tannico» che apre la ricerca
(`tannico.it/search?q=<cantina + nome>`, stesse parole di Vivino). Nell'Enoteca c'e' il filtro «Su
Tannico». Non copiamo i prezzi di Tannico. I link diretti stanno anche in `docs/vini.json`
(chiavi `tn`, `ta`).

**I voti (Tannico).** `python -I src/tannico.py voti` scarica la scheda prodotto (`/products/<handle>`, che il
robots.txt di Tannico consente; 3 secondi di pausa, browser finto, se arriva 429 aspetta 60 secondi e rallenta,
le schede gia' scaricate si saltano, `--forza` le riscarica) di ogni vino abbinato `esatta` o `annata diversa`
(194 indirizzi per 290 vini; alcuni vini puntano alla stessa scheda), le salva in `data/raw/tannico/prodotti/`
(non si pubblica) e scrive `data/tannico_voti.csv`: `id`, `url_tannico`, `annata_tannico`, `corrispondenza`,
`punteggio_tannico` (il «Giudizio di Tannico», che nel JSON-LD si chiama «Punteggio Tannico»; 0-100),
`voti_critici` (per esempio `Robert Parker 97/100; Decanter 97/100`, `Bibenda 5 grappoli`, `Jancis Robinson 16/20`),
`n_critici`, `data_raccolta` (2026-10-25). I critici vengono dai bollini in alto nella scheda (con la scala) e dal
blocco «Riconoscimenti annata corrente» (solo numero e nome: se non e' un critico noto la scala e' scritta `?`).
Si tengono **solo numeri e nomi dei critici**, nessun testo di recensione. Con `--solo-analisi` si rilegge
il CSV dalle schede gia' scaricate senza scaricare niente.
Sul sito: un bollino con il voto migliore (il primo critico su scala 100 in quest'ordine: Parker, Suckling, Wine
Spectator, Decanter, Galloni, ...; se non c'e' nessuno, il giudizio di Tannico: «Tannico 92») accanto all'annata
nelle schede dei vini, e una sezione «Voti» nella pagina del vino con tutte le fonti e il link a Tannico.
**Se la corrispondenza e' `annata diversa` i voti sono dell'annata di Tannico**: il bollino dice «Parker 96 · 2022»
e la pagina «Voti dell'annata 2022 (su Peck c'e' la ...)». Nell'Enoteca ci sono il filtro «Con voto» e l'ordine
«Voto: dal piu' alto» (chiavi `vb`, `vn`, `vy` in `docs/vini.json`). Limiti: 21 vini puntano a 10 schede che
Tannico ha tolto (404) e restano senza voti; per 5 schede non c'e' nessun voto; i vini vecchi (per esempio un
Sassicaia 1985) mostrano i voti dell'annata che Tannico vende oggi, scritta accanto.

Il programma `src/sito.py` legge i CSV di `data/` (e le pagine in `data/raw/` per i link alle foto),
**cancella le pagine generate e le riscrive tutte** (circa 4.200 pagine, 55 MB; circa un minuto): va
rilanciato dopo ogni modifica ai CSV. Non tocca `docs/style.css` e `docs/app.js`, che sono scritti a
mano.

**In `docs/` non ci sono foto.** Le immagini dei prodotti e delle bottiglie sono collegate
direttamente ai server di Peck e di Winerim: il sito le mostra ma non le copia.

**I disegni della Dispensa sono nostri** (`docs/disegni/*.svg`, 21 illustrazioni scritte a mano in
SVG, nei colori del sito). Quasi nessun prodotto ha una foto tutta sua (Peck mostra la foto della box,
che non fa capire che cosa sia il prodotto), quindi nella Dispensa e nelle pagine prodotto c'e' un
disegno; la pagina prodotto ha il link "Vedi la foto delle box che lo contengono". Il disegno lo sceglie
`src/sito.py` in base alle parole nel nome (`DISEGNI_PAROLE`, poi il disegno della categoria in
`DISEGNO_CATEGORIA`); la tabella completa e' anche in "Come funziona". I 10 prodotti con una foto propria
di Peck (panettoni, pandoro, veneziana, salmone, frutta disidratata) tengono la foto, e le Box regalo
usano sempre le foto di Peck. `sito.py` non cancella e non riscrive `docs/disegni/`.

**Grafica.** Giallo `#FFCD45` e marrone `#5E4824` sono i due colori del CSS di peck.it
(`--giallo-peck`, `--marrone-peck`); il carattere e' Raleway (quello di Peck, libero su Google Fonts,
caricato da li') e Playfair Display corsivo per le frasi di Peck. Non c'e' nessun file di Peck:
**il logo di Peck non e' mai pubblicato.** Sul computer del proprietario, e solo li', ogni pagina carica
`docs/personale.js` (solo se l'indirizzo e' `localhost` o `127.0.0.1`), che mette il logo nella
testata prendendolo dal server di Peck. `docs/personale.js` e' nel `.gitignore` (controllo:
`git check-ignore docs/personale.js`); se il file manca il sito funziona uguale, senza logo.

Per vederlo sul computer: `python -I -m http.server 8000 --directory docs`, poi
http://127.0.0.1:8000/ (aprire `index.html` direttamente non funziona: i vini si leggono con `fetch`).
Per controllare che funzioni anche sotto un prefisso: `python -I -m http.server 8001`
dalla cartella `peck-tracker` e aprire http://127.0.0.1:8001/docs/.

## Come rifare tutto

Servono Python 3.12, `requests` e `beautifulsoup4`. Dalla cartella `peck-tracker`, nell'ordine:

```
python -I src/fetch.py          # passo 1: scarica le pagine in data/raw/ (circa 10 minuti la prima volta)
python -I src/extract.py        # passo 1: scrive i quattro file CSV del passo 1 in data/
python -I src/bolli.py scarica  # passo 2: scarica gli elenchi UE degli stabilimenti (Italia e Spagna)
python -I src/bolli.py cerca    # passo 2: abbina i bolli CE
python -I src/vini.py --dettagli  # vini: scarica la carta e le schede dei vini (circa un'ora), scrive vini.csv e cantine.csv
python -I src/vini_box.py       # vini: confronta le box con la carta, scrive vini_nelle_box.csv
python -I src/controlla_link.py # link: controlla i link, scrive link_controllati.csv (ritocchi a mano in link_verifica_manuale.csv)
python -I src/tannico.py scarica  # Tannico: scarica il catalogo pubblico
python -I src/tannico.py abbina   # Tannico: abbina i vini, scrive tannico.csv
python -I src/tannico.py voti     # Tannico: scarica le schede dei vini abbinati (circa 15 minuti), scrive tannico_voti.csv
python -I src/sito.py           # sito: cancella e riscrive tutte le pagine di docs/ (e docs/vini.json)
```

`aziende.csv` non si rigenera con un programma: e' la ricerca a mano descritta sopra (dopo il controllo
dei link si correggono a mano i link rotti). `docs/personale.js` (il logo, solo in locale) non si rigenera e non si pubblica.

`fetch.py` aspetta 10 secondi fra una richiesta e l'altra (e' il `Crawl-delay` che lo shop
dichiara in robots.txt; si cambia con `--pausa 1`), salta i file gia' scaricati (con `--forza` li
riscarica) e legge solo le pagine in italiano. Parte dall'elenco `/it/negozio-online` (pagine 0-3)
e, per controllo, dall'elenco `/it/negozio-online/gift-box`: contengono gli stessi 46 prodotti. Lo
shop ha una sola categoria ("Gift box"); le pagine singole (panettoni, pandoro, veneziana, salmone,
frutta disidratata) sono nello stesso elenco.
