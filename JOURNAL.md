# Diario del progetto

Le decisioni prese, con la data e il perche'. Si aggiunge in fondo, non si riscrive.

## 24 ottobre 2026

- **Idea**: capire chi produce quello che Peck vende online, partendo dalle frasi "Prodotto in /
  Confezionato da" che Peck scrive in ogni scheda, anche dentro le gift box.
- **Passo 1** (`src/fetch.py`, `src/extract.py`): scaricate le 46 pagine dello shop (tutte di
  "Selezioni Natalizie": 36 box e 10 prodotti singoli), 347 pezzi spacchettati, 194 prodotti
  diversi, 67 indirizzi di produzione. Rispettato il `Crawl-delay: 10` di robots.txt.
- **Cosa si pubblica**: solo le frasi brevi sull'origine. Niente HTML, descrizioni, ingredienti o
  foto di Peck nel repo: `data/raw/` e' escluso da git.
- **Repo** pubblico `AndreottiVIII/peck-tracker`, scelto da Davide.
- **Passo 2** (`data/aziende.csv`): azienda, sito e shop per indirizzi, bolli CE e produttori
  nominati, con una fonte per riga e tre gradi: certa / probabile / non trovata. Mai un nome
  indovinato da un indirizzo senza fonte.
- **Bolli CE** (`src/bolli.py`): il sito del Ministero della Salute (SINTESIS) blocca i programmi,
  quindi si usano gli elenchi UE TRACES degli stabilimenti riconosciuti (stesse autorizzazioni).
- **Enoteca**: la carta dei vini di peck.it/enoteca e' di Winerim; la sua interfaccia dati
  pubblica restituisce 3071 vini di 820 cantine, mentre l'intestazione dice 1005 cantine (filtri
  che contano anche vini mai restituiti). `src/vini.py`, pausa 2 s.
- **Sito** su GitHub Pages (`docs/`): titolo "Peck Tracker", catalogo a schede tipo e-commerce,
  avviso "Progetto indipendente di appassionati, non affiliato a Peck. Nessun prodotto in vendita."
  in cima e in fondo.
- **Foto**: Davide le vuole. Sono collegate ai server di Peck e Winerim, mai copiate nel repo.
- **Secondo giro di ricerca**: non trovate da 21 a 16. L'olio di San Feliciano declassato a
  "probabile" (unica fonte: una banca dati aziendale).

## 25 ottobre 2026

- **Pagine vere** (come il sito perfect-games): una per prodotto, box, produttore, cantina e vino,
  ~4200 pagine, Indietro/Avanti normali, filtri nell'indirizzo. Vista Schede / Elenco.
- **Link**: `src/controlla_link.py` + `data/link_verifica_manuale.csv`. Davide aveva visto "molti
  link rotti": in realta' uno shop su 39 (Legu'), piu' Verrigni e Riso Gallo; corretti. Il sito
  non mostra mai bottoni verso link rotti.
- **Vini**: pagina per ogni vino con profilo di degustazione e dati della scheda Winerim. I testi
  descrittivi di Winerim NON si copiano (prosa loro): c'e' il link "Scheda completa in enoteca".
  Link di ricerca a Vivino e Wine-Searcher; nessun punteggio scaricato.
- **Grafica**: giallo Peck #FFCD45, marrone #5E4824, Raleway e Playfair Display da Google Fonts.
- **Logo Peck**: Davide lo vuole anche online; non si mette sul sito pubblico (con logo e aspetto
  da negozio sembrerebbe Peck). C'e' solo in locale: `docs/personale.js`, escluso da git,
  caricato solo su localhost.
- **Archivio**: tutti i dati scaricati sono anche zippati in `archivio/raw_2026-10-25.zip`
  (escluso da git), per poter rivedere tutto anche se i siti cambiano.
- **Dispensa**: le foto delle box sui singoli prodotti confondono; si passa a disegni per
  categoria fatti apposta. Box regalo resta con le foto.
- **Punteggi Vivino**: non si scaricano (Vivino blocca e vieta la raccolta automatica). Si
  aggiunge Tannico: link alla scheda del vino se c'e', altrimenti alla ricerca.
- **Disegni della Dispensa**: 21 disegni SVG nostri in `docs/disegni/` (palette del sito); scelta
  automatica per parole nel nome (`DISEGNI_PAROLE` in `src/sito.py`), altrimenti per categoria. Tolta
  l'etichetta "Foto della box"; nella pagina prodotto c'e' il link alla foto delle box.

- 25 ottobre 2026: bottoni Tannico sui vini (pagine vino, cantine, Enoteca + filtro «Su Tannico»), da `data/tannico.csv`: 116 link esatti, 174 con annata diversa (con nota), gli altri aprono la ricerca; nessun prezzo o punteggio copiato; «Come funziona» e README aggiornati.
- 25 ottobre 2026: voti dalle schede Tannico (`tannico.py voti`, approvato da Davide): 184 schede scaricate di 194 (10 tolte da Tannico, 404), `data/tannico_voti.csv` con 269 vini (264 con giudizio Tannico, 67 con critici: Parker, Decanter, Galloni, Suckling, Wine Spectator...). Bollino col voto migliore sulle schede dei vini, sezione «Voti» nella pagina, filtro «Con voto» e ordine per voto nell'Enoteca; per «annata diversa» l'anno e' sempre scritto accanto al voto.

- 25 ottobre 2026: bollino e filtro/ordine per voto solo se l'annata Tannico dista al massimo 2 anni da quella di Peck (senza annata: solo se manca da entrambe); piu' lontane, i voti restano nella pagina del vino dentro l'avviso, senza bollino. Aggiornato «Come funziona».
