/* Peck Tracker – il poco JavaScript che serve.
   0. la testata: in cima c'è tutta, scorrendo restano solo il menu (sticky) e un piccolo «Peck Tracker» a sinistra;
   1. i filtri delle liste (Dispensa, Box, Produttori, Enoteca), con lo stato nell'indirizzo (?q=...&cat=...)
      così "Indietro" riporta alla stessa lista filtrata;
   2. il passaggio Schede / Elenco (?vista=elenco);
   3. l'elenco dei vini dell'enoteca, che si legge da vini.json;
   4. il riquadro al posto di una foto che non si carica;
   5. i ritagli delle foto delle box (si caricano solo quando sono vicini allo schermo; se la foto manca resta il disegno);
   6. la pagina «Prezzi confrontati», che legge prezzi.json (filtri, categorie, pagine). */

/* ---------- 5. ritagli dalle foto delle box ---------- */
(() => {
  'use strict';
  const stato = new Map();   // url della foto -> 'ok' | 'ko' | [elementi in attesa]
  const mostra = (el, url) => { el.style.backgroundImage = 'url("' + url + '")'; el.classList.add('pronto'); };
  const manca = el => {      // la foto non si carica: via il ritaglio e la didascalia, resta il disegno che sta sotto
    const c = el.closest('.ritaglio-box');
    if (c) { c.classList.add('ko'); const e = c.querySelector('.etic-foto'); if (e) e.remove(); }
    el.remove();
  };
  function carica(el) {
    const url = el.dataset.src;
    if (!url) return;
    const s = stato.get(url);
    if (s === 'ok') return mostra(el, url);
    if (s === 'ko') return manca(el);
    if (s) { s.push(el); return; }
    stato.set(url, [el]);
    const im = new Image();
    im.referrerPolicy = 'no-referrer';
    im.onload = () => { const a = stato.get(url); stato.set(url, 'ok'); a.forEach(e => mostra(e, url)); };
    im.onerror = () => { const a = stato.get(url); stato.set(url, 'ko'); a.forEach(manca); };
    im.src = url;
  }
  const io = 'IntersectionObserver' in window
    ? new IntersectionObserver(es => { for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); carica(e.target); } }, { rootMargin: '400px' })
    : null;
  window.ptRitagli = root => {
    for (const el of (root || document).querySelectorAll('.ritaglio[data-src]:not([data-visto])')) {
      el.dataset.visto = '1';
      if (io) io.observe(el); else carica(el);
    }
  };
  window.ptRitagli(document);
})();


/* ---------- 0. testata ---------- */
(() => {
  'use strict';
  const testata = document.getElementById('testata');
  const menu = testata && testata.querySelector('.menu');
  if (!testata || !menu) return;
  const avviso = document.querySelector('.avviso');
  let cima = 0, compatta = false;

  // l'altezza di quello che sta sopra il menu (titolo e sottotitolo): lo spazio che esce dallo schermo
  const misura = () => {
    cima = menu.parentNode.offsetTop;
    testata.style.setProperty('--cima', cima + 'px');
    aggiorna();
  };
  const aggiorna = () => {
    const dove = (avviso ? avviso.offsetHeight : 0) + cima;   // scroll a cui il titolo è uscito del tutto
    const y = window.scrollY;
    const vuole = compatta ? y > dove - 40 : y > dove - 2;     // un po' di margine, per non far lampeggiare
    if (vuole !== compatta) { compatta = vuole; testata.classList.toggle('compatta', vuole); }
  };
  window.addEventListener('scroll', aggiorna, { passive: true });   // poche operazioni: non serve rimandarle
  window.addEventListener('resize', misura);
  if (window.ResizeObserver) new ResizeObserver(misura).observe(testata);   // per esempio quando arriva il logo (solo in locale)
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(misura);
  misura();
  // sul telefono il menu scorre: la voce della pagina corrente si porta in vista
  const corrente = menu.querySelector('[aria-current="page"]');
  if (corrente && menu.scrollWidth > menu.clientWidth) menu.scrollLeft = Math.max(0, corrente.offsetLeft - 16);
})();

(() => {
  'use strict';

  const main = document.getElementById('principale');
  const radice = document.body.dataset.radice || './';

  /* ---------- attrezzi ---------- */
  const norm = s => (s || '').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const num = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const cap = s => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const euro = x => {
    if (x == null) return '';
    let [i, d] = (Number.isInteger(x) ? String(x) : x.toFixed(2)).split('.');
    i = i.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return i + (d ? ',' + d : '') + ' €';
  };
  const salva = (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* niente */ } };
  const leggi = k => { try { return sessionStorage.getItem(k); } catch (e) { return null; } };

  /* ---------- foto che non si carica ---------- */
  document.addEventListener('error', ev => {
    const t = ev.target;
    if (t && t.tagName === 'IMG' && t.dataset.ph) {
      const sp = document.createElement('div');
      sp.className = 'segnaposto ' + (t.dataset.ph === 'vino' ? 'vino' : 'cibo');
      sp.setAttribute('role', 'img');
      sp.setAttribute('aria-label', 'Foto non disponibile');
      const box = t.parentNode;
      const e = box && box.querySelector('.etic-foto');
      if (e) e.remove();
      t.replaceWith(sp);
    }
  }, true);

  /* ---------- stato nell'indirizzo ---------- */
  const form = document.querySelector('form.filtri');
  const cont = document.getElementById('lista');
  const conteggio = document.getElementById('conteggio');
  if (!form || !cont) return;

  const controlli = [...form.querySelectorAll('[name]')];
  const params = new URLSearchParams(location.search);
  let vista = params.get('vista') === 'elenco' ? 'elenco' : 'schede';

  function leggiStato() {
    const S = {};
    for (const c of controlli) {
      if (c.type === 'checkbox') S[c.name] = c.checked ? '1' : '';
      else S[c.name] = c.value.trim();
    }
    return S;
  }

  function scriviIndirizzo(S) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(S)) if (v) p.set(k, v);
    const senzaVista = p.toString();
    if (vista === 'elenco') p.set('vista', 'elenco');
    const q = p.toString();
    history.replaceState(null, '', location.pathname + (q ? '?' + q : '') + location.hash);
    for (const a of document.querySelectorAll('.vista-scelta a')) {
      const v = a.dataset.vista;
      const pp = new URLSearchParams(senzaVista);
      if (v === 'elenco') pp.set('vista', 'elenco');
      const s = pp.toString();
      a.setAttribute('href', '?' + s);
      a.setAttribute('aria-current', v === vista ? 'true' : 'false');
    }
  }

  function mostraVista() {
    main.classList.toggle('vista-elenco', vista === 'elenco');
    for (const a of document.querySelectorAll('.vista-scelta a')) a.setAttribute('aria-current', a.dataset.vista === vista ? 'true' : 'false');
  }

  // valori iniziali dai parametri dell'indirizzo
  for (const c of controlli) {
    const v = params.get(c.name);
    if (v == null) continue;
    if (c.type === 'checkbox') c.checked = v === '1';
    else c.value = v;
  }

  // menu a tendina che dipendono da un altro (provincia da regione, regione da paese)
  const dipendenti = controlli.filter(c => c.dataset.dip);
  for (const sel of dipendenti) sel._tutte = [...sel.options].map(o => o.cloneNode(true));
  function aggiornaDipendenti() {
    for (const sel of dipendenti) {
      const padre = form.querySelector('[name="' + sel.dataset.dip + '"]');
      const cur = sel.value;
      const visti = new Set();
      sel.replaceChildren(...sel._tutte.filter(o => {
        if (o.value && padre.value && o.dataset.reg !== padre.value) return false;
        if (visti.has(o.value)) return false;
        visti.add(o.value);
        return true;
      }).map(o => o.cloneNode(true)));
      sel.value = [...sel.options].some(o => o.value === cur) ? cur : '';
    }
  }
  aggiornaDipendenti();
  // il valore iniziale dei dipendenti va riletto dopo aver ricostruito le opzioni
  for (const sel of dipendenti) { const v = params.get(sel.name); if (v && [...sel.options].some(o => o.value === v)) sel.value = v; }

  /* ---------- liste statiche (Dispensa, Box, Produttori) ---------- */
  const ul = cont.querySelector('ul.griglia');
  const vuoto = cont.querySelector('.vuoto');
  const sing = cont.dataset.singolare, plur = cont.dataset.plurale;
  const scrittoConteggio = n => { conteggio.textContent = n === 0 ? 'Nessun risultato' : `${num(n)} ${n === 1 ? sing : plur}`; };

  function ordinaPer(S) {
    const o = S.ord;
    if (o === 'prezzo-su') return ['prezzo', 1];
    if (o === 'prezzo-giu') return ['prezzo', -1];
    if (o === 'n') return ['n', -1];
    if (o === 'annata-giu') return ['annata', -1];
    if (o === 'annata-su') return ['annata', 1];
    return ['nome', 1];
  }

  function filtraStatica() {
    const S = leggiStato();
    const voci = cont._voci || (cont._voci = [...ul.querySelectorAll('li.it')]);
    const q = norm(S.q || '').split(/\s+/).filter(Boolean);
    let n = 0;
    for (const li of voci) {
      let ok = q.every(t => (li.dataset.k || '').includes(t));
      for (const c of controlli) {
        if (!ok) break;
        const v = S[c.name];
        if (!v || !c.dataset.attr) continue;
        const dato = li.dataset[c.dataset.attr] || '';
        if (c.dataset.modo === 'multi') ok = dato.includes('|' + v + '|');
        else if (c.dataset.modo === 'flag') ok = dato === '1';
        else ok = dato === v;
      }
      li.hidden = !ok;
      if (ok) n++;
    }
    // ordine (solo se c'è il menu "Ordina")
    if (form.querySelector('[name="ord"]')) {
      const [chiave, verso] = ordinaPer(S);
      const key = 'o' + chiave.charAt(0).toUpperCase() + chiave.slice(1);
      const ordinate = voci.slice().sort((a, b) => verso * ((+a.dataset[key] || 0) - (+b.dataset[key] || 0)) || (+a.dataset.oNome - +b.dataset.oNome));
      for (const li of ordinate) ul.append(li);
    }
    scrittoConteggio(n);
    vuoto.hidden = n !== 0;
    return S;
  }

  /* ---------- Enoteca (si legge vini.json) ---------- */
  let V = null, aggiornaEnoteca = null;
  if (cont.hasAttribute('data-enoteca')) {
    let mostrati = 0, elenco = [];
    const bottone = cont.querySelector('button.altri');
    const caricamento = cont.querySelector('.caricamento');
    const passo = () => (vista === 'elenco' ? 100 : 48);
    const chiaveMemoria = () => 'pt:' + location.pathname + location.search;

    const urlVivino = t => 'https://www.vivino.com/search/wines?q=' + encodeURIComponent(t);
    const urlWS = (t, a) => 'https://www.wine-searcher.com/find/' +
      norm(t).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').join('+') + (/^(19|20)\d\d$/.test(a || '') ? '/' + a : '');

    // formato di una riga prezzo: f = [etichetta Winerim, capacità, prezzo, in stock, nota, litri, nome]
    const litriIt = x => String(x).replace('.', ',');
    const chipFormato = f => {
      const litri = f[5], nome = f[6];
      if (!nome) return '';
      const classe = 'fmt' + (nome === 'Set' ? ' set' : litri != null && litri >= 1.5 ? ' grande'
        : litri != null && litri < 0.75 ? ' piccolo' : litri === 0.75 ? ' solito' : '');
      return `<span class="${classe}"${f[4] ? ` title="${esc(f[4])}"` : ''}>${esc(litri != null ? nome + ' · ' + litriIt(litri) + ' L' : nome)}</span>`;
    };
    // categoria del filtro «Formato»
    const catFormato = f => {
      const l = f[5];
      if (f[6] === 'Set') return 'set';
      if (l == null) return '';
      if (l < 0.75) return 'piccoli';
      if (l === 0.75) return 'bottiglia';
      if (l < 1.5) return 'litro';
      if (l < 3) return 'magnum';
      return 'grandi';
    };
    // riga che fa da riferimento per il prezzo: bottiglia da 0,75 L, se c'è; altrimenti la prima con prezzo
    const rigaPrincipale = w => { const p = w.f.filter(f => f[2] != null); return p.find(f => f[5] === 0.75) || p[0] || null; };
    // riga da confrontare con il filtro Formato attivo (prezzo più basso fra quelle di quella categoria)
    const rigaPerFormato = (w, fmt) => w.f.filter(f => f[2] != null && catFormato(f) === fmt).sort((a, b) => a[2] - b[2])[0] || null;

    const urlTannico = t => 'https://www.tannico.it/search?q=' + t.split(/\s+/).filter(Boolean).map(encodeURIComponent).join('+');

    // bollino del voto (stessa logica di badge_voto() in sito.py): critici, Tannico e utenti hanno colori diversi
    const votoBadge = w => {
      if (!w.vb) return '';
      const tit = w.vf + (w.vy ? ' per l’annata ' + w.vy + ', non quella di Peck' : '');
      return ` <span class="voto-badge vk-${esc(w.vk)}" title="${esc(tit)}">${esc(w.vb + (w.vy ? ' · ' + w.vy : ''))}</span>`;
    };

    // chip del premio (stessa logica di badge_premio() in sito.py): solo per i premi della stessa annata
    const premioChip = w => w.zb ? ` <span class="premio-chip" title="${esc(w.zt)}">${esc(w.zb)}</span>` : '';

    function cardVino(w) {
      const pagina = radice + 'vino/' + w.d + '/';
      const fotoUrl = w.ph ? (w.ph.startsWith('http') ? w.ph : V.meta.prefisso_foto + w.ph) : '';
      const alt = 'Bottiglia: ' + w.n + (w.a ? ' ' + w.a : '');
      const foto = fotoUrl
        ? `<div class="foto bottiglia"><img src="${esc(fotoUrl)}" alt="${esc(alt)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-ph="vino"></div>`
        : '<div class="foto bottiglia"><div class="segnaposto vino" role="img" aria-label="Foto non disponibile"></div></div>';
      const formati = w.f.filter(f => f[2] != null);
      const principale = rigaPrincipale(w);
      const altri = formati.filter(f => f !== principale);
      const elencoFormati = altri.length ? '<ul class="formati">' + altri.map(f => `<li>${chipFormato(f) || esc(cap(f[0] || f[1]))} ${euro(f[2])}</li>`).join('') + '</ul>' : '';
      const tipo = w.tipo;
      const chip = `<span class="tipo tipo-${tipo.replace(/[^a-z]+/g, '-')}">${esc(tipo === 'liquoroso/fortificato' ? 'liquoroso' : tipo)}</span>`;
      const ext = (url, t) => `<a class="bottone secondario piccolo" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${t}<span class="sr"> (si apre in una nuova scheda)</span></a>`;
      const tt = w.tt || (w.n);
      return `<li class="it"><article class="scheda vino">${foto}<div class="corpo">` +
        `<div class="col-a"><p class="tipo-riga">${chip}${w.a ? ` <span class="meta">· ${esc(w.a)}</span>` : ''}${votoBadge(w)}${premioChip(w)}</p>` +
        `<h2 class="nome"><a class="vai" href="${pagina}">${esc(w.n)}</a></h2></div>` +
        `<p class="meta"><span class="col-b"><a href="${radice}cantina/${esc(w.cantina.id)}/">${esc(w.cantina.nome)}</a></span>` +
        `<span class="col-c">${esc([w.r, w.paese].filter(Boolean).join(' · '))}</span></p>` +
        `<div class="col-d"><p class="prezzo">${w.pr != null ? euro(w.pr) + (principale && chipFormato(principale) ? ' ' + chipFormato(principale) : '') : '<span class="meta">Prezzo non indicato</span>'}</p>${elencoFormati}</div>` +
        `<div class="bottoni">${ext(urlVivino(tt), 'Vivino')}${ext(urlWS(tt, w.a), 'Wine-Searcher')}` +
        (w.tn ? ext(w.tn, 'Tannico') + (w.tf ? `<span class="nota-tannico meta">su Tannico c’è la ${esc(w.tf)}${w.ta ? ', annata ' + esc(w.ta) : ''}</span>`
              : w.ta ? `<span class="nota-tannico meta">su Tannico c’è l’annata ${esc(w.ta)}</span>` : '')
              : ext(urlTannico(tt), 'Cerca su Tannico')) + `</div>` +
        `</div></article></li>`;
    }

    const GRUPPO_VOTO = { c: 0, t: 1, u: 2 };

    function filtraVini(S) {
      const M = V.meta;
      const q = norm(S.q || '').split(/\s+/).filter(Boolean);
      const can = norm(S.can || '').trim();
      const pmin = S.pmin !== '' && S.pmin != null ? Number(S.pmin) : null;
      const pmax = S.pmax !== '' && S.pmax != null ? Number(S.pmax) : null;
      const ti = S.tipo ? M.tipi.indexOf(S.tipo) : -1;
      const pi = S.paese ? M.paesi.indexOf(S.paese) : -1;
      // prezzo e formato di riferimento di ogni vino: se c'è il filtro Formato, quello; se no la bottiglia da 0,75 L (o la prima)
      const rif = w => (S.fmt ? rigaPerFormato(w, S.fmt) : rigaPrincipale(w));
      let arr = V.vini.filter(w => {
        if (!((ti < 0 || w.t === ti) && (pi < 0 || w.p === pi) && (!S.reg || w.r === S.reg) &&
          (!can || w.kc.includes(can)) && (!S.tan || (w.tn && !w.tf)) && (!S.voto || w.vk) && (!S.crit || w.vk === 'c') && (!S.premi || w.ze) &&
          q.every(t => w.k.includes(t)))) return false;
        if (S.fmt) {
          if (S.fmt === 'set' ? !w.f.some(f => f[6] === 'Set') : !w.f.some(f => catFormato(f) === S.fmt)) return false;
        }
        if (pmin == null && pmax == null) return true;
        const r = rif(w);
        return !!r && (pmin == null || r[2] >= pmin) && (pmax == null || r[2] <= pmax);
      });
      // a parità di formato: la riga di riferimento di ogni vino ha un «gruppo» (0 = bottiglia da 0,75 L, poi i litri)
      for (const w of arr) { const r = rif(w); w._r = r; w._pr = r ? r[2] : null; w._g = r ? (r[5] === 0.75 ? 0 : (r[5] == null ? 99 : r[5])) : 99; }
      const conFiltro = !!S.fmt;
      const senza = (x, y, f) => (x._pr == null) - (y._pr == null) || f(x, y);   // senza prezzo in fondo
      const gruppo = (x, y, f) => conFiltro ? f(x, y) : ((x._g - y._g) || f(x, y));
      const perLitro = x => (x._pr != null && x._r[5]) ? x._pr / x._r[5] : null;
      const f = {
        'prezzo-su': (x, y) => senza(x, y, (a, b) => gruppo(a, b, (c, d) => c._pr - d._pr)),
        'prezzo-giu': (x, y) => senza(x, y, (a, b) => gruppo(a, b, (c, d) => d._pr - c._pr)),
        'litro-su': (x, y) => (perLitro(x) == null) - (perLitro(y) == null) || (perLitro(x) - perLitro(y)),
        'annata-giu': (x, y) => (Number(y.a) || 0) - (Number(x.a) || 0),
        'annata-su': (x, y) => (Number(x.a) || 9999) - (Number(y.a) || 9999),
        // tre gruppi che non si mischiano: critici /100, poi giudizio Tannico /100, poi utenti (stelle x 20, solo per ordinare)
        'voto-giu': (x, y) => (GRUPPO_VOTO[x.vk] ?? 9) - (GRUPPO_VOTO[y.vk] ?? 9) || (y.vn - x.vn) || x.n.localeCompare(y.n, 'it', { numeric: true }),
      }[S.ord] || ((x, y) => x.n.localeCompare(y.n, 'it', { numeric: true }));
      return arr.sort(f);
    }

    function disegna(daCapo, quanti) {
      const S = leggiStato();
      elenco = filtraVini(S);
      const notaOrd = document.getElementById('nota-ord');
      if (notaOrd) notaOrd.hidden = !(String(S.ord || '').startsWith('prezzo') && !S.fmt);
      const notaVoto = document.getElementById('nota-voto');
      if (notaVoto) notaVoto.hidden = S.ord !== 'voto-giu';
      const n = elenco.length;
      scrittoConteggio(n);
      vuoto.hidden = n !== 0;
      if (daCapo) { mostrati = Math.max(quanti || 0, passo()); ul.replaceChildren(); }
      const html = elenco.slice(ul.children.length, mostrati).map(cardVino).join('');
      ul.insertAdjacentHTML('beforeend', html);
      bottone.hidden = n <= ul.children.length;
      bottone.textContent = `Mostra altri (${num(n - ul.children.length)})`;
      return S;
    }

    aggiornaEnoteca = () => disegna(true);
    bottone.addEventListener('click', () => {
      const prima = ul.children.length;
      mostrati += passo();
      disegna(false);
      const primo = ul.children[prima];
      const a = primo && primo.querySelector('a');
      if (a) a.focus({ preventScroll: true });
    });
    // prima di lasciare la pagina ricordiamo dove eravamo (per "Indietro")
    const ricorda = () => salva(chiaveMemoria(), JSON.stringify({ y: window.scrollY, n: ul.children.length }));
    window.addEventListener('pagehide', ricorda);
    cont.addEventListener('click', ricorda);
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

    fetch(cont.dataset.json).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(j => {
      V = j;
      const byId = V.cantine;
      for (const w of V.vini) {
        w.cantina = byId[w.c];
        w.paese = V.meta.paesi[w.p];
        w.tipo = V.meta.tipi[w.t];
        w.k = norm([w.n, w.a, w.cantina.nome, w.r, w.paese, (w.u || []).join(' ')].join(' '));
        w.kc = norm(w.cantina.nome);
      }
      const dl = document.getElementById('lista-cantine');
      if (dl) dl.innerHTML = V.cantine.map(c => `<option value="${esc(c.nome)}"></option>`).join('');
      if (caricamento) caricamento.remove();
      let ricordo = null;
      try { ricordo = JSON.parse(leggi(chiaveMemoria()) || 'null'); } catch (e) { ricordo = null; }
      disegna(true, ricordo && ricordo.n);
      if (ricordo) window.scrollTo(0, ricordo.y);
    }).catch(e => {
      console.error(e);
      if (caricamento) caricamento.textContent = 'Non sono riuscito a caricare i vini. Controlla la connessione e riprova, oppure usa l’elenco delle cantine qui sotto.';
      const d = document.getElementById('cantine'); if (d) d.open = true;
    });
  }

  /* ---------- Prezzi confrontati (si legge prezzi.json) ---------- */
  if (cont.hasAttribute('data-prezzi')) {
    let mostrati = 0, elenco = [], ultimo = null;
    const bottone = cont.querySelector('button.altri');
    const caricamento = cont.querySelector('.caricamento');
    const vivo = document.getElementById('riepilogo-vivo');
    const PASSO = 40;
    const SRC = { produttore: 1, altro: 8, tannico: 2, enoteche: 4 };
    let soglia = 5;
    const ordineGruppi = {}, etichetteGruppi = {};

    const pctTesto = a => (a >= 10 ? String(Math.round(a)) : a.toFixed(1).replace('.', ',').replace(/,0$/, ''));
    const pctSegno = dp => (dp == null ? 'n.d.' : Math.abs(dp) < 0.5 ? '≈ 0%' : (dp > 0 ? '+' : '−') + pctTesto(Math.abs(dp)) + '%');
    const verdetto = dp => {
      if (Math.abs(dp) < 0.5) return 'Da Peck costa praticamente lo stesso';
      const p = pctTesto(Math.abs(dp));
      return 'Da Peck costa ' + (p[0] === '8' || p === '11' ? 'l’' : 'il ') + p + '% in ' + (dp > 0 ? 'più' : 'meno');
    };
    const classeDiff = dp => (dp < -soglia ? 'meno' : dp <= soglia ? 'pari' : 'piu');
    const barra = dp => `<span class="barra-diff d-${classeDiff(dp)}" role="img" aria-label="${esc(verdetto(dp))}"><span class="riempi ${dp > 0 ? 'dx' : 'sx'}" style="width:${(Math.min(Math.abs(dp), 100) / 2).toFixed(1)}%"></span></span>`;
    const prezzoFormato = (p, f) => euro(p) + (f ? ` <span class="meta">(${esc(f.replace(/\s*\(([^)]*)\)/g, ', $1'))})</span>` : '');
    const alUnita = (v, u) => (v ? `<span class="meta">${euro(v)} al ${u}</span>` : '');
    const mediana = a => { if (!a.length) return null; const v = a.slice().sort((x, y) => x - y), n = v.length; return n % 2 ? v[(n - 1) / 2] : (v[n / 2 - 1] + v[n / 2]) / 2; };

    function foto(r) {
      if (r.t === 'v') {
        return r.ph ? `<div class="foto bottiglia"><img src="${esc(r.ph)}" alt="Bottiglia: ${esc(r.n)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-ph="vino"></div>`
          : '<div class="foto bottiglia"><div class="segnaposto vino" role="img" aria-label="Foto non disponibile"></div></div>';
      }
      const im = r.im;
      if (im[0] === 'r') {
        const [, url, x, y, w, h, media, dis, box] = im;
        const stile = `background-size:${(100 / w).toFixed(2)}% ${(100 / h).toFixed(2)}%;background-position:${w < 1 ? (x / (1 - w) * 100).toFixed(2) : 0}% ${h < 1 ? (y / (1 - h) * 100).toFixed(2) : 0}%;background-repeat:no-repeat`;
        const did = 'Dettaglio dalla foto della box «' + box + '»' + (media ? ' (riconosciuto per esclusione)' : '');
        return `<div class="foto disegno ritaglio-box${media ? ' incerta' : ''}"><img class="sotto" src="${radice + dis}" width="200" height="200" alt="" loading="lazy" decoding="async">` +
          `<div class="ritaglio" role="img" aria-label="${esc(did + ': ' + r.n)}" data-src="${esc(url)}" style="${esc(stile)}"></div>` +
          `<span class="etic-foto" title="${esc(did)}">Dettaglio dalla box${media ? ' · per esclusione' : ''}</span></div>`;
      }
      if (im[0] === 'd') return `<div class="foto disegno"><img src="${radice + im[1]}" width="200" height="200" alt="Disegno: ${esc(im[2])}" loading="lazy" decoding="async"></div>`;
      if (im[0] === 'i') return `<div class="foto"><img src="${esc(im[1])}" alt="Foto di ${esc(r.n)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-ph="cibo"></div>`;
      return '<div class="foto"><div class="segnaposto cibo" role="img" aria-label="Foto non disponibile"></div></div>';
    }
    const esterno = (url, testo, cl) => (url ? `<a${cl ? ` class="${cl}"` : ''} href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(testo)}<span class="sr"> (si apre in una nuova scheda)</span></a>` : esc(testo));

    function riga(r) {
      const dp = r.dp;
      const nome = r.h ? `<a href="${radice + r.h}">${esc(r.n)}</a>` : esc(r.n);
      let meta, peck, fuori;
      if (r.t === 'c') {
        const f = r.fu[0], altro = (r.s & 8) !== 0;
        meta = `Confrontato con: ${esterno(f[2], f[0])}` + (r.sd ? ' <span class="chip-nd">solo nel delivery, non nello shop</span>' : '');
        peck = `<div class="lato"><p class="et">Da Peck</p><p class="cifra">${prezzoFormato(r.pk[0], r.pk[1])}</p><p>${alUnita(r.pk[2], r.pk[3])}</p></div>`;
        fuori = `<div class="lato"><p class="et">${altro ? 'Da un altro produttore' : 'Dal produttore'}</p><p class="cifra">${prezzoFormato(f[3], f[4])}</p><p>${alUnita(f[5], f[6])}</p></div>`;
      } else {
        meta = [r.ti, r.r, r.pa].filter(Boolean).map(esc).join(' · ') + (r.a ? ' · ' + esc(r.a) : '');
        peck = `<div class="lato"><p class="et">Da Peck</p><p class="cifra">${euro(r.pk[0])} <span class="meta">(${String(r.l).replace('.', ',')} L)</span></p><p><span class="meta">${euro(r.pk[1])} al litro</span></p></div>`;
        const of = r.fu.map(o => `<li class="${o[5] ? '' : 'nd'}${o[8] ? ' rif' : ''}">${esterno(o[1], o[0])}${o[7] ? '' : ` <span class="chip-annata">annata ${esc(o[2] || '?')}</span>`}${o[5] ? '' : ' <span class="chip-nd">non disponibile</span>'}<br>` +
          `${euro(o[3])} <span class="meta">(${euro(o[4])} al litro) · ${pctSegno(o[6])}</span></li>`).join('');
        fuori = `<div class="lato"><p class="et">${'Altrove'}</p><ul class="of-mini">${of}</ul></div>`;
      }
      const pagina = r.h ? `<a class="vai-pagina" href="${radice + r.h}">Vai alla pagina<span class="sr"> di ${esc(r.n)}</span></a>` : '';
      const nd = r.nd ? '<p class="meta">Oggi nessun negozio ha la bottiglia in vendita: prezzi dell’ultima volta.</p>' : '';
      return `<li class="occ" data-g="${esc(r.g)}">${foto(r)}` +
        `<div class="occ-nome"><p class="cat">${r.t === 'c' ? 'Cibo' : 'Vino'} · ${esc(r.st)}</p><p class="nome">${nome}</p><p class="meta">${meta}</p>${pagina}</div>` +
        `<div class="occ-prezzi">${peck}${fuori}</div>` +
        `<div class="occ-diff v-${classeDiff(dp)}"><p class="grande">${pctSegno(dp)}</p>${barra(dp)}<p class="meta">${esc(verdetto(dp))} (${esc(r.b)})</p>${nd}</div></li>`;
    }

    function filtra(S) {
      const q = norm(S.q || '').split(/\s+/).filter(Boolean);
      const modo = S.ord;
      const arr = V.righe.filter(r => {
        if (S.cat && r.g !== S.cat) return false;
        if (S.reg && !(r.t === 'v' && r.r === S.reg)) return false;
        if (S.fonte && !(r.s & SRC[S.fonte])) return false;
        if (S.stesso && r.sp !== 3) return false;
        if (S.occ && !(r.x === 1 && r.dp <= soglia)) return false;
        if (q.length) {
          if (!r.k) r.k = norm([r.n, r.fu.map(f => f[0]).join(' '), r.r || '', r.pa || '', r.ti || '', etichetteGruppi[r.g] || ''].join(' '));
          if (!q.every(t => r.k.includes(t))) return false;
        }
        return true;
      });
      const nome = (a, b) => a.n.localeCompare(b.n, 'it', { numeric: true });
      if (modo === 'dp-su') arr.sort((a, b) => a.dp - b.dp || nome(a, b));
      else if (modo === 'dp-giu') arr.sort((a, b) => b.dp - a.dp || nome(a, b));
      else if (modo === 'nome') arr.sort(nome);
      else arr.sort((a, b) => (ordineGruppi[a.g] - ordineGruppi[b.g]) || a.dp - b.dp || nome(a, b));
      return arr;
    }

    function disegna(daCapo) {
      const S = leggiStato();
      elenco = filtra(S);
      const raggruppa = !S.ord;
      const n = elenco.length;
      scrittoConteggio(n);
      vuoto.hidden = n !== 0;
      if (vivo) {
        const m = mediana(elenco.map(r => r.dp));
        const meno = elenco.filter(r => r.dp <= soglia).length;
        vivo.textContent = n ? `Differenza mediana di quelli mostrati: ${pctSegno(m)}. Peck costa meno o al massimo +${String(soglia).replace('.', ',')}% in ${num(meno)}.` : '';
      }
      if (daCapo) { mostrati = PASSO; ul.replaceChildren(); ultimo = null; }
      const conta = {};
      if (raggruppa) for (const r of elenco) conta[r.g] = (conta[r.g] || 0) + 1;
      let html = '';
      for (const r of elenco.slice(ul.querySelectorAll('li.occ').length, mostrati)) {
        if (raggruppa && r.g !== ultimo) {
          ultimo = r.g;
          html += `<li class="gruppo-testa"><h2>${esc(etichetteGruppi[r.g] || r.g)} <span class="meta">(${num(conta[r.g])})</span></h2></li>`;
        }
        html += riga(r);
      }
      ul.insertAdjacentHTML('beforeend', html);
      if (window.ptRitagli) window.ptRitagli(ul);
      const visti = ul.querySelectorAll('li.occ').length;
      bottone.hidden = n <= visti;
      bottone.textContent = `Mostra altri (${num(n - visti)})`;
      return S;
    }

    aggiornaEnoteca = () => disegna(true);
    bottone.addEventListener('click', () => {
      const prima = ul.querySelectorAll('li.occ').length;
      mostrati += PASSO;
      disegna(false);
      const nuovo = ul.querySelectorAll('li.occ')[prima];
      const a = nuovo && nuovo.querySelector('a');
      if (a) a.focus({ preventScroll: true });
    });
    fetch(cont.dataset.json).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(j => {
      V = j;
      soglia = j.meta.soglia;
      j.meta.gruppi.forEach((g, i) => { ordineGruppi[g.k] = i; etichetteGruppi[g.k] = g.t; });
      if (caricamento) caricamento.remove();
      disegna(true);
    }).catch(e => {
      console.error(e);
      if (caricamento) caricamento.textContent = 'Non sono riuscito a caricare i confronti. Controlla la connessione e riprova, oppure guarda l’Angolo delle occasioni.';
    });
  }

  /* ---------- collegamenti ai controlli ---------- */
  function applica() {
    aggiornaDipendenti();
    const S = aggiornaEnoteca ? (V ? aggiornaEnoteca() : leggiStato()) : filtraStatica();
    scriviIndirizzo(S || leggiStato());
  }

  let timer = null;
  form.addEventListener('input', ev => {
    const t = ev.target;
    if (t.tagName === 'SELECT' || t.type === 'checkbox') return;   // questi partono da 'change'
    clearTimeout(timer);
    timer = setTimeout(applica, 180);
  });
  // «solo critici» è un sotto-filtro di «Con voto»: spuntarlo spunta anche l'altro, togliere «Con voto» toglie anche lui
  const fVoto = form.querySelector('[name="voto"]'), fCrit = form.querySelector('[name="crit"]');
  if (fVoto && fCrit && fCrit.checked) fVoto.checked = true;
  form.addEventListener('change', ev => {
    if (fVoto && fCrit) {
      if (ev.target === fCrit && fCrit.checked) fVoto.checked = true;
      if (ev.target === fVoto && !fVoto.checked) fCrit.checked = false;
    }
    clearTimeout(timer); applica();
  });
  form.querySelector('.azzera').addEventListener('click', () => {
    for (const c of controlli) { if (c.type === 'checkbox') c.checked = false; else c.value = ''; }
    applica();
    controlli[0].focus();
  });
  const apri = form.querySelector('.apri-filtri');
  const altri = form.querySelector('.altri-filtri');
  apri.addEventListener('click', () => {
    const a = altri.classList.toggle('aperti');
    apri.setAttribute('aria-expanded', a ? 'true' : 'false');
  });
  // se l'indirizzo ha filtri diversi dalla ricerca, apriamo il pannello (sul telefono è chiuso di solito)
  if ([...params.keys()].some(k => k !== 'q' && k !== 'vista')) { altri.classList.add('aperti'); apri.setAttribute('aria-expanded', 'true'); }

  for (const a of document.querySelectorAll('.vista-scelta a')) {
    a.addEventListener('click', ev => {
      ev.preventDefault();
      vista = a.dataset.vista;
      mostraVista();
      if (aggiornaEnoteca && V) { aggiornaEnoteca(); }
      scriviIndirizzo(leggiStato());
    });
  }

  mostraVista();
  if (!aggiornaEnoteca) { const S = filtraStatica(); scriviIndirizzo(S); }
  else scriviIndirizzo(leggiStato());
})();
