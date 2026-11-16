"""Legge la pagina di un prodotto del nuovo shop Peck (peck.it/shop, WooCommerce).

Nel nuovo shop il riquadro «Scheda prodotto» (div.accordion-content) e' un blocco di testo unico: i
paragrafi del vecchio shop sono stati uniti senza separatori, nella forma

    NOME DELL'ELEMENTO 250 gIngredienti:\\ncorpo...Prodotto in Via X 1, Comune (PR)NOME DEL SECONDO 30 gIngredienti:\\n...

Il corpo di un elemento finisce dove comincia il nome del successivo, e il nome non ha un
delimitatore: lo si riconosce (1) con i nomi gia' noti (quelli del vecchio shop e le righe della
«Descrizione» della pagina), confrontati senza maiuscole, accenti e spazi; (2) altrimenti come la
sequenza di MAIUSCOLE, cifre e unita' (g, kg, cl...) che precede «Ingredienti:».

Le frasi di origine si ricavano poi con gli stessi programmi di src/extract.py.
"""
import difflib
import html
import re
import unicodedata

from bs4 import BeautifulSoup

MARCA = "Ingredienti:"
MAIUSC = "A-ZÀ-ÖØ-Þ"


def nz(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pulisci_testo(t):
    t = html.unescape(t or "").replace("\xa0", " ").replace("’", "'").replace("´", "'")
    return re.sub(r"[ \t]+", " ", t)


def righe_descrizione(descrizione_html):
    """Le righe della «Descrizione» (API o pagina), una per riga, senza tag."""
    s = BeautifulSoup(descrizione_html or "", "html.parser")
    for br in s.find_all("br"):
        br.replace_with("\n")
    return [re.sub(r"\s+", " ", pulisci_testo(x)).strip() for x in s.get_text().split("\n") if x.strip()]


def testo_scheda(html_pagina):
    """Il testo del riquadro «Scheda prodotto» (stringa vuota se manca)."""
    s = BeautifulSoup(html_pagina, "html.parser")
    for el in s.select(".woocommerce-accordion .accordion-content"):
        item = el.find_parent(class_="accordion-item")
        titolo = item.find("label") if item else None
        if titolo and "scheda" in titolo.get_text().lower():
            return pulisci_testo(el.get_text())
    el = s.select_one(".accordion-content")
    return pulisci_testo(el.get_text()) if el else ""


def _alnum_mappa(testo):
    """(stringa confrontabile, posizione originale di ogni suo carattere)."""
    out, pos = [], []
    for i, c in enumerate(testo):
        d = "".join(x for x in unicodedata.normalize("NFD", c) if unicodedata.category(x) != "Mn").lower()
        for x in d:
            if re.fullmatch(r"[a-z0-9]", x):
                out.append(x)
                pos.append(i)
    return "".join(out), pos


def _inizio_per_vocabolario(testo, vocab):
    """Se il testo finisce con uno dei nomi noti, posizione in cui comincia (la piu' lunga); se no None."""
    conf, pos = _alnum_mappa(testo)
    migliore = None
    for chiave, nome in vocab:
        if len(chiave) < 4 or not conf.endswith(chiave):
            continue
        i = pos[len(conf) - len(chiave)]
        prima = testo[i - 1] if i > 0 else ""
        primo = testo[i]
        # un nome noto vale come confine anche se attaccato a MAIUSCOLE di prima («...CEFICO TARTUFATO»);
        # non vale in mezzo a una parola in minuscolo («...pomodorino» + «ORO»)
        if prima and prima.islower() and primo.islower():
            continue
        if migliore is None or i < migliore[0]:
            migliore = (i, nome)
    return migliore[0] if migliore else None


def _nome_finale(testo):
    """Il nome come ultima sequenza di MAIUSCOLE, cifre e unita' (g, kg, cl...) alla fine di `testo`;
    ritorna la posizione in cui comincia."""
    t = testo.rstrip()
    m = re.search(r"\d+(?:[.,]\d+)?\s?(?:kg|g|gr|cl|ml|l|pz)$", t)
    if m:
        t = t[:m.start()] + "0" * (len(t) - m.start())     # l'unita' in minuscolo non ferma la ricerca
    fine, i, par = len(t), len(t), 0
    while i > 0:
        c = t[i - 1]
        if re.match("[" + MAIUSC + r"0-9 '&/+*\"-]", c):
            i -= 1
        elif c == ")" and i == fine:
            par += 1
            i -= 1
        elif c == "(" and par:
            par -= 1
            i -= 1
        elif c == "." and (i == fine or t[i:i + 1].isdigit() or (t[i:i + 1] == " " and t[i + 1:i + 2].isdigit())):
            i -= 1
        elif c == "," and t[i:i + 1].isdigit() and t[i - 2:i - 1].isdigit():      # «51X33,5X22»
            i -= 1
        else:
            break
    # «c2», «c9»: la sigla della scatola, minuscola + cifre, attaccata alla frase di prima («Italia.c2»)
    if i < fine and i > 0 and t[i - 1].islower() and re.fullmatch(r"\d+", t[i:fine].strip()):
        i -= 1
    return i


RE_VERBO_CORPO = re.compile(r"^(?:PRODOTT[OA]|CONFEZIONAT|IMBOTTIGLIAT|SPUMANTIZZAT|CONTIENE|ALCOL)\b")
RE_BOLLO_INIZIO = re.compile(r"^(?:IT|ES|FR|DE)(?:\s?\d|\s[A-Z0-9]*\d[A-Z0-9]*\s)[0-9A-Z./ \-]*?CE\.?")
RE_ACCESSORIO = re.compile(r"^(?:FILTRO|COFANETTO|SCATOL|SCATON|CESTO|ASTUCCIO|BORSA|CARTONE|CONFEZIONE REGALO)", re.I)


def _separa(blocco, vocab):
    """Divide il testo che sta fra due «Ingredienti:» in (corpo dell'elemento prima, nome dell'elemento dopo)."""
    pos = _inizio_per_vocabolario(blocco, vocab)
    if pos is None:
        pos = _nome_finale(blocco)
    corpo, cand = blocco[:pos], blocco[pos:].strip()
    # il «nome» trovato con le maiuscole puo' essere in realta' la coda del corpo (un bollo, «PRODOTTO IN...»)
    if pos is not None and cand:
        if RE_VERBO_CORPO.match(cand):
            return corpo + cand, ""
        m = RE_BOLLO_INIZIO.match(cand)
        if m:
            corpo, cand = corpo + cand[:m.end()], cand[m.end():].strip()
    return corpo, cand


def segmenti(testo, vocab_nomi=()):
    """Il testo della scheda -> [(nome, [righe del corpo])]; nome «» = voce senza nome (di solito un vino)."""
    vocab = sorted(({(nz(n), n) for n in vocab_nomi if n}), key=lambda x: -len(x[0]))
    pezzi = testo.split(MARCA)
    nomi, corpi = [], []
    _, nome0 = _separa(" " + pezzi[0], vocab)
    nomi.append(nome0)
    for k in range(1, len(pezzi)):
        if k == len(pezzi) - 1:
            corpi.append(pezzi[k])
            break
        corpo, nome = _separa(pezzi[k], vocab)
        corpi.append(corpo)
        nomi.append(nome)
    out = []
    for nome, corpo in zip(nomi, corpi):
        nome = re.sub(r"\s+", " ", nome).strip(" :\n")
        if len(re.findall(r"[A-Za-zÀ-ÿ]", nome)) < 3:      # «.», «c2»: non e' un nome
            nome = ""
        righe = [re.sub(r"\s+", " ", r).strip() for r in corpo.split("\n")]
        # «Thailandia.Confezionato da...»: il punto attaccato alla frase dopo (le frasi sono state unite senza spazio)
        righe = [re.sub(r"(?<=[a-z0-9\)])\.(?=[A-Z][a-zà-ÿ])", ". ", r) for r in righe]
        out.append((nome, [r for r in righe if r]))
    return out


def _quantita(s):
    """«0.7 KG», «700g», «25 cl», «250ml» -> «q700», «q250»: la stessa quantita' scritta in modi diversi."""
    def f(m):
        v = float(m.group(1).replace(",", "."))
        u = m.group(2).lower()
        v *= {"kg": 1000, "l": 1000, "lt": 1000, "cl": 10}.get(u, 1)
        return f" q{int(round(v))} "
    return re.sub(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g|lt|l|cl|ml)\b", f, s, flags=re.I)


def _token(s):
    s = _quantita(s)
    return set(re.findall(r"q\d+|[a-z]+|\d+", "".join(c for c in unicodedata.normalize("NFD", s.lower())
                                              if unicodedata.category(c) != "Mn")))


def _anni(s):
    return set(re.findall(r"\b(?:19|20)\d\d\b", s))


def _coperta(riga, nome):
    """La riga della «Descrizione» e il nome di un elemento della scheda sono lo stesso prodotto?
    (parole in comune, stessi anni: «Sassicaia 2015» non e' «Sassicaia 2017»)"""
    a, b = nz(riga), nz(nome)
    if not a or not b:
        return False
    if a == b:
        return True
    if _anni(riga) != _anni(nome):
        return False
    ta, tb = _token(riga), _token(nome)
    if (ta <= tb and len(ta) >= 3) or (tb <= ta and len(tb) >= 3):
        return True
    if len(ta & tb) / min(len(ta), len(tb)) >= 0.8:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


RE_VINO = re.compile(r"champagne|franciacorta|prosecco|spumante|barolo|brunello|chianti|lucente|pomino|"
                     r"\bvino\b|coffret|riserva|metodo classico|pas dos|\bbrut\b|(?<![\d.,])\b(?:19|20)\d\d\b(?!\s*/)", re.I)
RE_NON_PRODOTTO = re.compile(r"^(?:ordinabile|spedibile|disponibile)", re.I)


def _sembra_vino(riga):
    return bool(RE_VINO.search(riga)) and not RE_NON_PRODOTTO.match(riga)


def _marca(righe):
    """La marca dopo «da» nella frase di origine di un vino («PRODOTTO IN FRANCIA DA KRUG» -> krug)."""
    for r in righe:
        m = re.search(r"\bda\s+([A-Za-zÀ-ÿ' ]+)$", r, re.I)
        if m:
            return nz(m.group(1))
    return ""


def elementi_pagina(testo_scheda, righe_desc, vocab_nomi=(), vini=False):
    """Gli elementi di una pagina: [{"nome", "righe", "da": "scheda"|"descrizione"}].

    Gli elementi con nome vengono dalla scheda (come nel vecchio shop). Le voci senza nome (nel nuovo shop
    i vini non hanno il nome nella scheda, solo «PRODOTTO IN FRANCIA DA KRUG»...) si abbinano alle righe
    della «Descrizione» che nessun elemento della scheda copre: prima per la marca, poi in ordine se i
    numeri tornano. `vini=True` (box di vini): ogni riga della Descrizione e' un elemento, anche senza
    scheda. Nelle altre pagine la Descrizione e' prosa o l'elenco dei contenuti con altri nomi, e dalle
    sue righe si prendono solo quelle che sembrano un vino e hanno una voce senza nome da abbinare."""
    noti = {nz(n): n for n in vocab_nomi if n}
    seg = segmenti(testo_scheda, vocab_nomi) if testo_scheda else []
    elementi, anonime = [], []
    for nome, righe in seg:
        if not nome:
            if righe:
                anonime.append(righe)
            continue
        if RE_ACCESSORIO.match(nome):
            continue
        elementi.append({"nome": nome, "righe": righe, "da": "scheda"})
    nomi_scheda = [e["nome"] for e in elementi]
    scoperte = []
    for r in righe_desc:
        if (RE_ACCESSORIO.match(r) or "cartone goffrat" in r.lower() or RE_NON_PRODOTTO.match(r)
                or len(re.findall(r"[A-Za-zÀ-ÿ]", r)) < 4):
            continue
        if any(_coperta(r, n) for n in nomi_scheda):
            continue
        nome = noti.get(nz(r))
        if nome is None and (vini or _sembra_vino(r)):
            # un vino: stesso prodotto con il nome del vecchio shop (maiuscole, marca...), se no la riga com'e'
            mig = max(((difflib.SequenceMatcher(None, nz(r), k).ratio(), n) for k, n in noti.items()
                       if _coperta(r, n) and n not in nomi_scheda), default=(0, None))
            if mig[1]:
                nome = mig[1]
            elif vini or anonime:
                nome = r
        if nome is None:
            continue
        scoperte.append(nome)
    abbinate = {}
    rimaste = list(range(len(anonime)))
    for j, riga in enumerate(scoperte):
        for i in list(rimaste):
            marca = _marca(anonime[i])
            if marca and marca in nz(riga):
                abbinate[j] = anonime[i]
                rimaste.remove(i)
                break
    libere = [j for j in range(len(scoperte)) if j not in abbinate]
    if len(libere) == len(rimaste):
        for j, i in zip(libere, rimaste):
            abbinate[j] = anonime[i]
    visti = set(nz(e["nome"]) for e in elementi)
    for j, riga in enumerate(scoperte):
        if nz(riga) in visti:
            continue
        visti.add(nz(riga))
        elementi.append({"nome": riga, "righe": abbinate.get(j, []), "da": "descrizione"})
    return elementi
