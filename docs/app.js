/* Peck Tracker – il poco JavaScript che serve.
   Le pagine sono già complete in HTML: qui ci sono solo
   1. i filtri delle liste (Dispensa, Box, Produttori, Enoteca), con lo stato nell'indirizzo (?q=...&cat=...)
      così "Indietro" riporta alla stessa lista filtrata;
   2. il passaggio Schede / Elenco (?vista=elenco);
   3. l'elenco dei vini dell'enoteca, che si legge da vini.json;
   4. il riquadro al posto di una foto che non si carica. */
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

    function cardVino(w) {
      const pagina = radice + 'vino/' + w.d + '/';
      const fotoUrl = w.ph ? (w.ph.startsWith('http') ? w.ph : V.meta.prefisso_foto + w.ph) : '';
      const alt = 'Bottiglia: ' + w.n + (w.a ? ' ' + w.a : '');
      const foto = fotoUrl
        ? `<div class="foto bottiglia"><img src="${esc(fotoUrl)}" alt="${esc(alt)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-ph="vino"></div>`
        : '<div class="foto bottiglia"><div class="segnaposto vino" role="img" aria-label="Foto non disponibile"></div></div>';
      const formati = w.f.filter(f => f[2] != null);
      const principale = formati.find(f => f[2] === w.pr);
      const altri = formati.filter(f => f !== principale);
      const elencoFormati = altri.length ? '<ul class="formati">' + altri.map(f => `<li>${esc(cap(f[0] || f[1]))}${f[1] && f[0] ? ' ' + esc(f[1]) : ''}: ${euro(f[2])}</li>`).join('') + '</ul>' : '';
      const tipo = w.tipo;
      const chip = `<span class="tipo tipo-${tipo.replace(/[^a-z]+/g, '-')}">${esc(tipo === 'liquoroso/fortificato' ? 'liquoroso' : tipo)}</span>`;
      const ext = (url, t) => `<a class="bottone secondario piccolo" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${t}<span class="sr"> (si apre in una nuova scheda)</span></a>`;
      const tt = w.tt || (w.n);
      return `<li class="it"><article class="scheda vino">${foto}<div class="corpo">` +
        `<div class="col-a"><p class="tipo-riga">${chip}${w.a ? ` <span class="meta">· ${esc(w.a)}</span>` : ''}</p>` +
        `<h2 class="nome"><a class="vai" href="${pagina}">${esc(w.n)}</a></h2></div>` +
        `<p class="meta"><span class="col-b"><a href="${radice}cantina/${esc(w.cantina.id)}/">${esc(w.cantina.nome)}</a></span>` +
        `<span class="col-c">${esc([w.r, w.paese].filter(Boolean).join(' · '))}</span></p>` +
        `<div class="col-d"><p class="prezzo">${w.pr != null ? euro(w.pr) : '<span class="meta">Prezzo non indicato</span>'}</p>${elencoFormati}</div>` +
        `<div class="bottoni">${ext(urlVivino(tt), 'Vivino')}${ext(urlWS(tt, w.a), 'Wine-Searcher')}</div>` +
        `</div></article></li>`;
    }

    function filtraVini(S) {
      const M = V.meta;
      const q = norm(S.q || '').split(/\s+/).filter(Boolean);
      const can = norm(S.can || '').trim();
      const pmin = S.pmin !== '' && S.pmin != null ? Number(S.pmin) : null;
      const pmax = S.pmax !== '' && S.pmax != null ? Number(S.pmax) : null;
      const ti = S.tipo ? M.tipi.indexOf(S.tipo) : -1;
      const pi = S.paese ? M.paesi.indexOf(S.paese) : -1;
      let arr = V.vini.filter(w =>
        (ti < 0 || w.t === ti) && (pi < 0 || w.p === pi) && (!S.reg || w.r === S.reg) &&
        (!can || w.kc.includes(can)) &&
        (pmin == null || (w.pr != null && w.pr >= pmin)) && (pmax == null || (w.pr != null && w.pr <= pmax)) &&
        q.every(t => w.k.includes(t)));
      const senza = (x, y, f) => (x.pr == null) - (y.pr == null) || f(x, y);   // senza prezzo in fondo
      const f = {
        'prezzo-su': (x, y) => senza(x, y, (a, b) => a.pr - b.pr),
        'prezzo-giu': (x, y) => senza(x, y, (a, b) => b.pr - a.pr),
        'annata-giu': (x, y) => (Number(y.a) || 0) - (Number(x.a) || 0),
        'annata-su': (x, y) => (Number(x.a) || 9999) - (Number(y.a) || 9999),
      }[S.ord] || ((x, y) => x.n.localeCompare(y.n, 'it', { numeric: true }));
      return arr.sort(f);
    }

    function disegna(daCapo, quanti) {
      const S = leggiStato();
      elenco = filtraVini(S);
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
  form.addEventListener('change', ev => { clearTimeout(timer); applica(); });
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
