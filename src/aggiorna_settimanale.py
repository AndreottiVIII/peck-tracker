"""Aggiornamento settimanale dei dati e del sito (lo lancia .github/workflows/aggiorna.yml, ma si puo' lanciare anche a mano).

    python -I src/aggiorna_settimanale.py [--budget-minuti 50] [--solo passo1,passo2] [--scarica-voti-aperti]

Rilegge le fonti pubbliche che si possono riscaricare e poi riscrive il sito. Un passo alla volta, nell'ordine:

  winerim            carta dei vini (src/vini.py --dettagli): elenco sempre nuovo, scheda di dettaglio solo per i vini nuovi
  tannico            catalogo Tannico (src/tannico.py scarica) e abbinamenti (abbina)
  voti_tannico       schede Tannico dei vini abbinati: si scaricano solo quelle che non ci sono ancora (3 s di pausa)
  confronto_vini     prezzi Peck / Tannico al litro (src/confronto_vini.py)
  prezzi_produttori  prezzi dei produttori nei confronti del cibo (src/aggiorna_prezzi_produttori.py)
  box_valore         valore spacchettato delle box con i prezzi appena riletti (src/box_valore.py, offline)
  voti_aperti        voti Wine Enthusiast / X-Wines (src/voti_aperti.py abbina): solo se i dataset sono su disco
  voti_enoteche      voti dai negozi (src/voti_enoteche.py): SPENTO, si accende con la variabile VOTI_ENOTECHE=si
  confronto_enoteche prezzi Peck / negozi (src/confronto_vini_enoteche.py): solo se le schede dei negozi sono su disco
  foto_shop          pagine dello shop Peck per le foto (src/fetch.py): solo se mancano (computer pulito)
  sito               src/sito.py: riscrive docs/ (se questo passo fallisce il programma esce con errore)

Regole:
  - Un sito che non risponde non ferma gli altri: il passo e' segnato «errore» e si va avanti. Se un passo fallisce, o se
    i suoi file nuovi sono molto piu' piccoli dei vecchi (meno del 90% delle righe), i file vecchi tornano al loro posto.
  - Il tempo totale e' limitato (default 50 minuti, il job ne ha 60): un passo a cui non resta tempo si salta, e al
    sito si lascia sempre il tempo che gli serve. Con la cache di data/raw la volta dopo si riparte da dove si era arrivati.
  - Niente di cio' che sta in data/locale/ o in archivio/ (non ci sono su GitHub) e' necessario.
  - Il delivery di Peck (serve il login) non si tocca mai.
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
DATA = RADICE / "data"
RAW = DATA / "raw"
DOCS = RADICE / "docs"
T0 = time.time()
BUDGET_S = 50 * 60
RISERVA_SITO_MIN = 8
ESITI = []   # (passo, stato, secondi)


def py(*argv):
    # -X utf8: l'output in italiano non si rompe nemmeno dove la console non e' UTF-8; -I come tutto il progetto
    return [sys.executable, "-X", "utf8", "-I", *argv]


def righe(percorso):
    """Righe di dati di un CSV (0 se manca o non si legge)."""
    try:
        with open(percorso, encoding="utf-8-sig", newline="") as f:
            return max(sum(1 for _ in csv.reader(f)) - 1, 0)
    except (OSError, csv.Error):
        return 0


def righe_con_abbinamento(percorso):
    """tannico.csv: i vini che hanno un abbinamento (non «nessuna»)."""
    try:
        with open(percorso, encoding="utf-8-sig", newline="") as f:
            return sum(1 for r in csv.DictReader(f) if r.get("corrispondenza") != "nessuna")
    except (OSError, csv.Error):
        return 0


class Copia:
    """Copia di sicurezza di alcuni file; `ripristina()` li rimette com'erano."""

    def __init__(self, file):
        self.dir = Path(tempfile.mkdtemp(prefix="aggiorna_"))
        self.file = []
        for i, f in enumerate(file):
            f = Path(f)
            if f.exists():
                dest = self.dir / f"{i}_{f.name}"
                shutil.copy2(f, dest)
                self.file.append((f, dest))

    def ripristina(self):
        for f, dest in self.file:
            shutil.copy2(dest, f)

    def chiudi(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class PagineRaw:
    """Pagine di elenco scaricate in data/raw che il passo deve riscaricare sempre (catalogo Tannico, carta Winerim).
    Si mettono da parte, il programma le riscarica, e se qualcosa va storto tornano quelle vecchie
    (cosi' una pagina vecchia rimasta non si mescola con le nuove, e un sito spento non lascia buchi)."""

    def __init__(self, cartella, schemi):
        self.cartella = cartella
        self.dir = Path(tempfile.mkdtemp(prefix="aggiorna_raw_"))
        self.vecchie = []
        for schema in schemi:
            for f in cartella.glob(schema):
                shutil.move(str(f), str(self.dir / f.name))
                self.vecchie.append(f.name)
        self.schemi = schemi

    def ripristina(self):
        for schema in self.schemi:   # via le pagine nuove (incomplete), dentro le vecchie
            for f in self.cartella.glob(schema):
                f.unlink()
        for nome in self.vecchie:
            shutil.move(str(self.dir / nome), str(self.cartella / nome))

    def chiudi(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def resta_s(riserva_min=0):
    return BUDGET_S - (time.time() - T0) - riserva_min * 60


def registra(passo, stato, inizio=None):
    ESITI.append((passo, stato, int(time.time() - inizio) if inizio else 0))
    print(f"--- {passo}: {stato}", flush=True)
    if any(k in stato for k in ("errore", "scaduto", "RIPRISTINATO", "non partito", "FALLITO"))             and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning title=Aggiornamento settimanale::{passo}: {stato}", flush=True)


def passo(nome, argv, minuti, protetti=(), metrica=righe, soglia=0.9, raw=None, riserva_min=RISERVA_SITO_MIN,
          vero_nome=None):
    """Esegue un programma con tempo massimo; se fallisce o i file protetti si svuotano, rimette quelli vecchi.
    Restituisce True se e' andato bene."""
    nome = vero_nome or nome
    inizio = time.time()
    disponibile = resta_s(riserva_min)
    if disponibile < 90:
        registra(nome, "saltato: tempo finito", inizio)
        return False
    timeout = min(minuti * 60, disponibile)
    print(f"\n=== {nome} (al massimo {int(timeout / 60)} minuti)", flush=True)
    prima = {Path(f): metrica(f) for f in protetti}
    copia = Copia(protetti)
    pagine = PagineRaw(*raw) if raw else None
    try:
        rc = subprocess.run(py(*argv), cwd=RADICE, timeout=timeout).returncode
        stato = "ok" if rc == 0 else f"errore (codice {rc})"
    except subprocess.TimeoutExpired:
        rc, stato = None, f"tempo scaduto dopo {int(timeout / 60)} minuti"
    except OSError as e:
        rc, stato = None, f"non partito: {e}"
    ok = rc == 0
    if ok:
        for f, n_prima in prima.items():
            n_dopo = metrica(f)
            if n_prima >= 20 and n_dopo < n_prima * soglia:
                ok = False
                stato = f"RIPRISTINATO: {f.name} scenderebbe da {n_prima} a {n_dopo} righe"
                break
    if not ok:
        copia.ripristina()
        if pagine:
            pagine.ripristina()
        if stato == "ok":
            stato = "errore"
        if protetti:
            stato += " (file vecchi rimessi a posto)"
    copia.chiudi()
    if pagine:
        pagine.chiudi()
    registra(nome, stato, inizio)
    return ok


# ---------------------------------------------------------------- i passi
def catalogo_tannico_ok():
    n = len(list((RAW / "tannico").glob("products_p*.json")))
    return n >= 5


def p_winerim():
    carta = RAW / "winerim"
    passo("winerim", ["src/vini.py", "--dettagli", "--max-minuti", "15"], 25,
          protetti=[DATA / "vini.csv", DATA / "cantine.csv", DATA / "formati.csv"],
          raw=(carta, ["vini_p*.json", "filtri.json"]))


# Le condizioni d'uso di Tannico (iubenda, art. "Scraping") vietano la raccolta automatica di dati senza
# autorizzazione scritta: finche' non arriva, l'aggiornamento non scarica nulla da tannico.it (26/10/2026).
TANNICO_ATTIVO = False


def p_tannico():
    if not TANNICO_ATTIVO:
        registra("tannico: catalogo", "spento: le condizioni d'uso di Tannico vietano lo scraping senza autorizzazione")
        return
    ok = passo("tannico: catalogo", ["src/tannico.py", "scarica"], 12,
               raw=(RAW / "tannico", ["products_p*.json", "sitemap*.xml"]))
    if not catalogo_tannico_ok():
        registra("tannico: abbinamenti", "saltato: catalogo Tannico non disponibile")
        return
    if not ok:
        print("(catalogo non aggiornato: si abbina con quello che c'e')", flush=True)
    passo("tannico: abbinamenti", ["src/tannico.py", "abbina"], 8, protetti=[DATA / "tannico.csv"],
          metrica=righe_con_abbinamento, soglia=0.8)


def p_voti_tannico():
    if not TANNICO_ATTIVO:
        registra("voti Tannico", "spento: le condizioni d'uso di Tannico vietano lo scraping senza autorizzazione")
        return
    if not catalogo_tannico_ok() or righe(DATA / "tannico.csv") == 0:
        registra("voti Tannico", "saltato: mancano catalogo o abbinamenti")
        return
    passo("voti Tannico", ["src/tannico.py", "voti", "--pausa", "3"], 30,
          protetti=[DATA / "tannico_voti.csv"], soglia=0.95)


def p_confronto_vini():
    if not catalogo_tannico_ok() or righe(DATA / "tannico.csv") == 0:
        registra("confronto vini", "saltato: mancano catalogo o abbinamenti")
        return
    passo("confronto vini", ["src/confronto_vini.py"], 15,
          protetti=[DATA / "confronto" / "vini_tannico.csv"])


def p_prezzi_produttori():
    if not list((DATA / "confronto").glob("risultati_*.csv")):
        registra("prezzi produttori", "saltato: nessun file data/confronto/risultati_*.csv")
        return
    cartella = DATA / "confronto"
    passo("prezzi produttori", ["src/aggiorna_prezzi_produttori.py", "--max-minuti", "20"], 25,
          protetti=sorted(cartella.glob("risultati_*.csv")) + [cartella / "storico_prezzi.csv"],
          soglia=0.99)


def p_box_valore():
    """Il «valore spacchettato» delle box: usa i prezzi appena aggiornati (tutto offline)."""
    cartella = DATA / "confronto"
    if not (RADICE / "src" / "box_valore.py").exists():
        registra("valore delle box", "saltato: manca src/box_valore.py")
        return
    passo("valore delle box", ["src/box_valore.py"], 5,
          protetti=[cartella / "box_valore.csv", cartella / "box_valore_righe.csv"])


def p_confronto_enoteche():
    """Prezzi Peck / negozi online, letti dalle schede gia' salvate in data/raw/voti/<enoteca>/pagine (nessuno scarico).
    Su un computer pulito non ci sono: il file resta com'e'."""
    pagine = [p for p in (RAW / "voti").glob("*/pagine") if p.is_dir() and any(p.iterdir())]
    if not (RADICE / "src" / "confronto_vini_enoteche.py").exists() or not pagine:
        registra("prezzi vini / negozi", "saltato: schede dei negozi non su disco (il file resta com'e')")
        return
    passo("prezzi vini / negozi", ["src/confronto_vini_enoteche.py"], 8,
          protetti=[DATA / "confronto" / "vini_enoteche_prezzi.csv"], soglia=0.9)


def p_voti_aperti(scarica):
    voti = RAW / "voti"
    necessari = [voti / "wine_enthusiast" / "p1.csv", voti / "xwines" / "XWines_Full_100K_wines.csv",
                 voti / "xwines" / "ratings_per_vintage.csv"]
    if scarica and not all(f.exists() for f in necessari):
        passo("voti aperti: scarico dei dataset", ["src/voti_aperti.py", "scarica"], 30)
        # lo zip da 300 MB non serve piu' dopo l'aggregazione
        zip_ = voti / "xwines" / "XWines_Full_21M_ratings.zip"
        if zip_.exists() and (voti / "xwines" / "ratings_per_vintage.csv").exists():
            zip_.unlink()
    if not all(f.exists() for f in necessari):
        registra("voti aperti", "saltato: dataset non su disco (voti_aperti.csv resta com'e')")
        return
    voti.mkdir(parents=True, exist_ok=True)
    passo("voti aperti", ["src/voti_aperti.py", "abbina"], 15,
          protetti=[DATA / "voti_aperti.csv", DATA / "voti_aperti_da_controllare.csv"], soglia=0.9)


def p_voti_enoteche():
    if os.environ.get("VOTI_ENOTECHE", "").lower() not in ("si", "sì", "yes", "true", "1"):
        registra("voti enoteche", "spento (si accende con VOTI_ENOTECHE=si)")
        return
    script = RADICE / "src" / "voti_enoteche.py"
    csv_ = DATA / "voti_enoteche.csv"
    if not script.exists() or not csv_.exists():
        registra("voti enoteche", "saltato: manca il programma o data/voti_enoteche.csv")
        return
    # bbr si scarica solo dalle 02:00 alle 07:00 UTC con 10 s di pausa: resta fuori da questo giro
    passo("voti enoteche: sitemap", ["src/voti_enoteche.py", "sitemap"], 15)
    passo("voti enoteche: candidati", ["src/voti_enoteche.py", "abbina"], 10)
    for e in ("millesima", "callmewine", "zachys", "xtrawine"):
        if (RAW / "voti" / e / "candidati.csv").exists():
            passo(f"voti enoteche: {e}", ["src/voti_enoteche.py", "scarica", e], 12)
    passo("voti enoteche: estrazione", ["src/voti_enoteche.py", "estrai"], 8, protetti=[csv_], soglia=0.9)


def p_foto_shop():
    if list(RAW.glob("prodotto_*.html")):
        registra("foto dello shop", "non serve: pagine gia' su disco")
        return
    # senza queste pagine il sito perde le foto dei prodotti e delle box (le legge src/sito.py)
    passo("foto dello shop", ["src/fetch.py"], 25)


def p_sito():
    vini_prima = len(list((DOCS / "vino").glob("*"))) if (DOCS / "vino").exists() else 0
    ok = passo("sito", ["src/sito.py"], 15, riserva_min=0)
    if not ok:
        return False
    vini_dopo = len(list((DOCS / "vino").glob("*"))) if (DOCS / "vino").exists() else 0
    controlli = [(DOCS / "index.html").exists(), (DOCS / "vini.json").exists(),
                 vini_prima == 0 or vini_dopo >= 0.9 * vini_prima]
    if not all(controlli):
        registra("sito: controllo finale", f"FALLITO (index, vini.json, pagine dei vini {vini_prima} -> {vini_dopo})")
        return False
    print(f"pagine dei vini: {vini_prima} -> {vini_dopo}", flush=True)
    return True


def riepilogo(fallito):
    print("\n==== RIEPILOGO ====")
    righe_md = ["| Passo | Esito | Secondi |", "| --- | --- | ---: |"]
    for nome, stato, s in ESITI:
        print(f"{nome:36} {stato}  ({s} s)")
        righe_md.append(f"| {nome} | {stato} | {s} |")
    print(f"tempo totale: {int(time.time() - T0)} s")
    f = os.environ.get("GITHUB_STEP_SUMMARY")
    if f:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("## Aggiornamento settimanale\n\n" + "\n".join(righe_md) + "\n")


def main():
    global BUDGET_S
    sys.stdout.reconfigure(encoding="utf-8")
    passi = {
        "winerim": p_winerim, "tannico": p_tannico, "voti_tannico": p_voti_tannico,
        "confronto_vini": p_confronto_vini, "prezzi_produttori": p_prezzi_produttori,
        "box_valore": p_box_valore, "voti_aperti": None, "voti_enoteche": p_voti_enoteche,
        "confronto_enoteche": p_confronto_enoteche, "foto_shop": p_foto_shop,
    }
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-minuti", type=float, default=50)
    ap.add_argument("--solo", default="", help="solo questi passi, separati da virgola (il sito si riscrive sempre; "
                                                "con --solo senza 'sito' si salta)")
    ap.add_argument("--scarica-voti-aperti", action="store_true",
                    help="se i dataset di voti_aperti non sono su disco, scaricali (serve il pacchetto gdown)")
    a = ap.parse_args()
    BUDGET_S = a.budget_minuti * 60
    scelti = [x.strip() for x in a.solo.split(",") if x.strip()]
    for x in scelti:
        if x not in passi and x != "sito":
            sys.exit("passo sconosciuto: " + x + " (validi: " + ", ".join(list(passi) + ["sito"]) + ")")
    for nome, f in passi.items():
        if scelti and nome not in scelti:
            continue
        try:
            if nome == "voti_aperti":
                p_voti_aperti(a.scarica_voti_aperti)
            else:
                f()
        except Exception as e:   # un passo scritto male non deve fermare gli altri
            registra(nome, f"errore del programma di aggiornamento: {type(e).__name__}: {e}")
    sito_ok = True
    if not scelti or "sito" in scelti:
        try:
            sito_ok = p_sito()
        except Exception as e:
            registra("sito", f"errore del programma di aggiornamento: {type(e).__name__}: {e}")
            sito_ok = False
    riepilogo(not sito_ok)
    if not sito_ok:
        print("::error title=Aggiornamento settimanale::il sito non e' stato riscritto: niente da pubblicare", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
