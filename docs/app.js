/* Peck Tracker – catalogo senza server.
   Legge dati.json (cibo) e vini.json (enoteca), costruiti da src/sito.py.
   Le foto si caricano direttamente dai server di Peck e di Winerim: qui non ce ne sono. */
(() => {
  'use strict';

  const REPO = 'https://github.com/AndreottiVIII/peck-tracker';
  const main = document.getElementById('principale');
  const menu = document.getElementById('menu');

  let D = null;       // dati.json
  let V = null;       // vini.json
  const mappe = {};   // indici per id
  const ultimaLista = {};   // ultima lista aperta per ogni sezione (per il link "torna")

  const STATI = {
    certa: 'certa', probabile: 'probabile', 'non trovata': 'non trovata',
    peck: 'Peck stessa', nessuna: 'nessuna indicazione',
  };
  const ORDINE_STATI = ['certa', 'probabile', 'peck', 'non trovata', 'nessuna'];
  const TIPI_CHIAVE = { indirizzo: 'Indirizzo', bollo_ce: 'Bollo CE', produttore: 'Produttore nominato' };

  /* ---------- attrezzi ---------- */

  function h(tag, attrs, ...figli) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'html') el.innerHTML = v;      // solo per piccole immagini fisse scritte qui
        else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const f of figli.flat(Infinity)) {
      if (f == null || f === false) continue;
      el.append(f.nodeType ? f : document.createTextNode(String(f)));
    }
    return el;
  }

  const norm = s => (s || '').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const num = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const cap = s => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

  function urlSicuro(u) {
    try {
      const x = new URL(u, location.href);
      return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : '';
    } catch (e) { return ''; }
  }

  function ext(url, testo, classe) {
    const u = urlSicuro(url);
    if (!u) return null;
    return h('a', { href: u, target: '_blank', rel: 'noopener noreferrer', class: classe },
      testo, h('span', { class: 'sr' }, ' (si apre in una nuova scheda)'));
  }

  const euro = n => (n == null ? '' : new Intl.NumberFormat('it-IT', {
    style: 'currency', currency: 'EUR', minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
  }).format(n));

  const SVG_CIBO = '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M8 44h48M12 44a20 20 0 0 1 40 0M32 24v-5M28 19h8"/><path d="M6 50h52" stroke-linecap="round"/></svg>';
  const SVG_VINO = '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false"><path d="M28 6h8v12c0 4 8 8 8 16v22a2 2 0 0 1-2 2H22a2 2 0 0 1-2-2V34c0-8 8-12 8-16z"/><path d="M20 38h24"/></svg>';

  function segnaposto(tipo) {
    return h('div', { class: 'segnaposto', role: 'img', 'aria-label': 'Foto non disponibile', html: tipo === 'vino' ? SVG_VINO : SVG_CIBO });
  }

  /** Riquadro foto: l'immagine è collegata dal server originale (mai copiata). */
  function foto(url, alt, { tipo = 'cibo', etichetta = '' } = {}) {
    const box = h('div', { class: 'foto' + (tipo === 'vino' ? ' bottiglia' : '') });
    const u = urlSicuro(url);
    if (!u) {
      box.append(segnaposto(tipo));
    } else {
      box.append(h('img', {
        src: u, alt, loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer', 'data-ph': tipo,
      }));
    }
    if (etichetta && u) box.append(h('span', { class: 'etic-foto' }, etichetta));
    return box;
  }

  // se una foto non si carica mettiamo un riquadro neutro (l'evento error non risale: lo prendiamo in cattura)
  document.addEventListener('error', ev => {
    const t = ev.target;
    if (t && t.tagName === 'IMG' && t.dataset.ph) {
      const sp = segnaposto(t.dataset.ph);
      const box = t.parentNode;
      t.replaceWith(sp);
      const e = box && box.querySelector('.etic-foto');
      if (e) e.remove();
    }
  }, true);

  function badge(stato) {
    const k = String(stato).replace(/\s+/g, '-');
    return h('span', { class: 'badge b-' + k, title: 'Quanto siamo sicuri di chi fa il prodotto' }, STATI[stato] || stato);
  }

  const luogo = (comune, prov) => (comune ? comune + (prov ? ` (${prov})` : '') : '');

  /* ---------- stato nella parte dopo ? dell'indirizzo ---------- */

  function leggiQuery(qs) {
    const S = {};
    new URLSearchParams(qs || '').forEach((v, k) => { S[k] = v; });
    return S;
  }
  function scriviQuery(base, S) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(S)) if (v !== '' && v != null && v !== false) p.set(k, v === true ? '1' : v);
    const s = p.toString();
    const nuovo = base + (s ? '?' + s : '');
    history.replaceState(null, '', nuovo);
    return nuovo;
  }

  /* ---------- caricamento dati ---------- */

  async function carica(file) {
    const r = await fetch(file);
    if (!r.ok) throw new Error(file + ': ' + r.status);
    return r.json();
  }

  async function serveDati() {
    if (D) return;
    D = await carica('dati.json');
    mappe.item = new Map(D.dispensa.map(x => [x.id, x]));
    mappe.box = new Map(D.box.map(x => [x.id, x]));
    mappe.az = new Map(D.produttori.map(x => [x.id, x]));
    for (const it of D.dispensa) {
      const pezzi = [it.nome, it.nome_originale, it.categoria, ...(it.regioni || [])];
      it.best = it.origini.slice().sort((a, b) => ORDINE_STATI.indexOf(a.stato) - ORDINE_STATI.indexOf(b.stato))[0] || null;
      it.aziende = [...new Set(it.origini.map(o => o.azienda).filter(Boolean))];
      for (const o of it.origini) {
        const z = mappe.az.get(o.azienda);
        pezzi.push(o.comune, o.provincia, o.bollo, o.nominato, o.frase);
        if (z) pezzi.push(z.nome, z.marchio, z.comune);
      }
      it.k = norm(pezzi.join(' '));
      it.shop = it.aziende.some(id => { const z = mappe.az.get(id); return z && (z.shop_online === 'si' || z.link_shop); });
    }
    for (const z of D.produttori) {
      z.k = norm([z.nome, z.ragione, z.marchio, z.comune, z.provincia, z.regione, ...z.chiavi.map(c => c.chiave)].join(' '));
      z.shop = z.shop_online === 'si' || !!z.link_shop;
    }
    for (const b of D.box) b.k = norm(b.nome);
  }

  async function serveVini() {
    if (V) return;
    V = await carica('vini.json');
    V.cantineId = new Map(V.cantine.map(c => [c.id, c]));
    for (const w of V.vini) {
      const c = V.cantine[w.c];
      w.cantina = c;
      w.paese = V.meta.paesi[w.p];
      w.tipo = V.meta.tipi[w.t];
      w.k = norm([w.n, w.a, c.nome, w.r, w.paese, w.u.join(' ')].join(' '));
      w.kc = norm(c.nome);
    }
    for (const c of V.cantine) c.vini = [];
    for (const w of V.vini) w.cantina.vini.push(w);
  }

  /* ---------- pezzi in comune ---------- */

  function chiFa(it) {
    const o = it.best;
    if (!o) return { riga: 'Nessuna indicazione di dove è fatto', stato: 'nessuna' };
    const z = mappe.az.get(o.azienda);
    const sede = luogo(o.comune || o.comune_azienda || (z && z.comune), o.provincia || (z && z.provincia));
    const altre = it.aziende.length > 1 ? ` e altre ${it.aziende.length - 1}` : '';
    if (o.stato === 'peck') return { riga: ['Peck stessa, in via Spadari 9 (Milano)'], stato: 'peck' };
    if (o.stato === 'nessuna') return { riga: 'Nessuna indicazione di dove è fatto', stato: 'nessuna' };
    if (z && z.trovata) {
      return { riga: [h('strong', null, 'Fatto da ' + z.nome), altre, sede ? ' · ' + sede : ''], stato: o.stato };
    }
    const dove = sede || (o.bollo ? 'codice ' + o.bollo : o.nominato || 'luogo non chiaro');
    return { riga: [h('strong', null, 'Azienda non trovata'), altre, ' · ', dove], stato: o.stato };
  }

  function schedaItem(it) {
    const c = chiFa(it);
    return h('a', { class: 'scheda', href: '#/prodotto/' + it.id },
      foto(it.foto, 'Foto di ' + it.nome + ' dal sito Peck', { etichetta: it.foto_tipo === 'box' ? 'Foto della box' : '' }),
      h('div', { class: 'corpo' },
        h('span', { class: 'cat' }, cap(it.categoria)),
        h('p', { class: 'nome' }, it.nome),
        h('p', { class: 'meta' }, c.riga),
        badge(c.stato)));
  }

  function schedaBox(b) {
    return h('a', { class: 'scheda', href: '#/box/' + b.id },
      foto(b.foto, 'Foto di ' + b.nome + ' dal sito Peck'),
      h('div', { class: 'corpo' },
        h('span', { class: 'cat' }, b.tipo === 'box' ? 'Box regalo' : 'Prodotto singolo'),
        h('p', { class: 'nome' }, b.nome),
        h('p', { class: 'meta' }, h('span', { class: 'prezzo' }, b.prezzo_testo), h('br'),
          b.n_elementi + (b.n_elementi === 1 ? ' prodotto' : ' prodotti'))));
  }

  function schedaAzienda(z) {
    const dove = luogo(z.comune, z.provincia) || z.paese || 'sede non indicata';
    return h('a', { class: 'scheda azienda', href: '#/produttore/' + z.id },
      h('p', { class: 'nome' }, z.trovata ? z.nome : 'Azienda non trovata'),
      z.marchio && z.trovata ? h('p', { class: 'meta' }, 'Marchio: ', z.marchio) : null,
      h('p', { class: 'meta' }, dove, z.regione && z.regione !== z.paese ? ` · ${z.regione}` : ''),
      h('p', { class: 'meta' }, 'Per Peck: ', z.prodotti.length + (z.prodotti.length === 1 ? ' prodotto' : ' prodotti')),
      h('div', null, badge(z.certezza), ' ', z.shop ? h('span', { class: 'badge b-shop' }, 'shop online') : null));
  }

  const URL_FOTO_VINO = w => (w.ph ? (w.ph.startsWith('http') ? w.ph : V.meta.prefisso_foto + w.ph) : '');
  const URL_VINO = w => w.l || (V.meta.prefisso_link + w.id + '/' + w.s);

  function tipoChip(t) {
    return h('span', { class: 'tipo tipo-' + t.replace(/[^a-z]+/g, '-') }, t === 'liquoroso/fortificato' ? 'liquoroso' : t);
  }

  function schedaVino(w) {
    const formati = w.f.filter(f => f[2] != null);
    const altri = formati.filter(f => f !== (formati.find(x => x[2] === w.pr) || null));
    return h('article', { class: 'scheda vino' },
      foto(URL_FOTO_VINO(w), 'Bottiglia: ' + w.n + (w.a ? ' ' + w.a : ''), { tipo: 'vino' }),
      h('div', { class: 'corpo' },
        h('p', null, tipoChip(w.tipo), w.a ? h('span', { class: 'meta' }, ' · ' + w.a) : null),
        h('h3', { class: 'nome' }, w.n),
        h('p', { class: 'meta' }, h('a', { href: '#/cantina/' + w.cantina.id }, w.cantina.nome)),
        h('p', { class: 'meta' }, [w.r, w.paese].filter(Boolean).join(' · ')),
        w.u.length ? h('p', { class: 'meta' }, 'Uve: ', w.u.join(', ')) : null,
        h('p', { class: 'prezzo' }, w.pr != null ? euro(w.pr) : h('span', { class: 'meta' }, 'Prezzo non indicato')),
        altri.length ? h('ul', { class: 'formati' }, altri.map(f => h('li', null, `${cap(f[0] || f[1])}${f[1] && f[0] ? ' ' + f[1] : ''}: ${euro(f[2])}`))) : null,
        ext(URL_VINO(w), 'Scheda in enoteca', 'bottone secondario piccolo')));
  }

  /* ---------- pagina a elenco con filtri (usata da tutte le liste) ---------- */

  function campoSelect(id, etichetta, opzioni, valore, vuoto) {
    const s = h('select', { id }, h('option', { value: '' }, vuoto || 'Tutti'),
      opzioni.map(o => { const [v, t] = Array.isArray(o) ? o : [o, o]; return h('option', { value: v }, t); }));
    s.value = valore || '';
    if (s.value !== (valore || '')) s.value = '';
    return h('div', { class: 'campo' }, h('label', { for: id }, etichetta), s);
  }

  /**
   * cfg: { base: '#/dispensa', params: stringa query, titolo, intro, campi: [{k,tipo,etichetta,opzioni,...}],
   *        filtra(S) -> array, card(x) -> Node, per: schede alla volta, singolare, plurale, ordina(S, arr) }
   */
  function paginaLista(cfg) {
    const S = leggiQuery(cfg.params);
    ultimaLista[cfg.sezione] = cfg.base + (cfg.params ? '?' + cfg.params : '');
    const contatore = h('p', { class: 'conteggio', 'aria-live': 'polite', role: 'status' });
    const risultati = h('div');
    const form = h('form', { class: 'filtri', role: 'search', 'aria-label': 'Filtri: ' + cfg.titolo, onsubmit: e => e.preventDefault() });
    const altri = h('div', { class: 'altri-filtri', id: 'altri-filtri' });
    let mostrati = cfg.per || 48;
    let timer = null;

    const toggle = h('button', { type: 'button', class: 'apri-filtri', 'aria-expanded': 'false', 'aria-controls': 'altri-filtri',
      onclick: () => {
        const a = altri.classList.toggle('aperti');
        toggle.setAttribute('aria-expanded', a ? 'true' : 'false');
      } }, 'Filtri');

    const rigaCampi = h('div', { class: 'riga' });
    const elementi = {};

    function aggiorna(ricostruisciDipendenti) {
      cfg.params = scriviQuery(cfg.base, S).split('?')[1] || '';
      ultimaLista[cfg.sezione] = location.hash;
      mostrati = cfg.per || 48;
      if (ricostruisciDipendenti && cfg.dipendenti) cfg.dipendenti(S, elementi);
      disegna();
    }

    for (const c of cfg.campi) {
      let el;
      if (c.tipo === 'cerca') {
        el = h('input', { type: 'search', id: 'f-' + c.k, value: S[c.k] || '', placeholder: c.segnaposto || '', autocomplete: 'off',
          oninput: e => { S[c.k] = e.target.value; clearTimeout(timer); timer = setTimeout(() => aggiorna(), 150); } });
        const campo = h('div', { class: 'campo cerca' }, h('label', { for: 'f-' + c.k }, c.etichetta), el);
        form.append(campo);
        elementi[c.k] = el;
        continue;
      }
      if (c.tipo === 'select') {
        const campo = campoSelect('f-' + c.k, c.etichetta, c.opzioni(S), S[c.k], c.vuoto);
        el = campo.querySelector('select');
        el.addEventListener('change', e => { S[c.k] = e.target.value; if (c.azzera) c.azzera.forEach(k => { S[k] = ''; }); aggiorna(true); });
        elementi[c.k] = el; elementi[c.k + '_campo'] = campo;
        rigaCampi.append(campo);
      } else if (c.tipo === 'spunta') {
        el = h('input', { type: 'checkbox', id: 'f-' + c.k, checked: S[c.k] ? true : null,
          onchange: e => { S[c.k] = e.target.checked ? '1' : ''; aggiorna(); } });
        rigaCampi.append(h('div', { class: 'campo spunta' }, el, h('label', { for: 'f-' + c.k }, c.etichetta)));
        elementi[c.k] = el;
      } else if (c.tipo === 'num') {
        el = h('input', { type: 'number', id: 'f-' + c.k, min: '0', step: '1', inputmode: 'numeric', value: S[c.k] || '', placeholder: c.segnaposto || '',
          oninput: e => { S[c.k] = e.target.value; clearTimeout(timer); timer = setTimeout(() => aggiorna(), 250); } });
        rigaCampi.append(h('div', { class: 'campo' }, h('label', { for: 'f-' + c.k }, c.etichetta), el));
        elementi[c.k] = el;
      } else if (c.tipo === 'testolista') {   // casella di testo con suggerimenti
        const lid = 'lista-' + c.k;
        el = h('input', { type: 'text', id: 'f-' + c.k, list: lid, value: S[c.k] || '', placeholder: c.segnaposto || '', autocomplete: 'off',
          oninput: e => { S[c.k] = e.target.value; clearTimeout(timer); timer = setTimeout(() => aggiorna(), 200); } });
        rigaCampi.append(h('div', { class: 'campo' }, h('label', { for: 'f-' + c.k }, c.etichetta), el,
          h('datalist', { id: lid }, c.suggerimenti().map(x => h('option', { value: x })))));
        elementi[c.k] = el;
      }
    }
    altri.append(rigaCampi,
      h('button', { type: 'button', class: 'azzera', onclick: () => {
        for (const k of Object.keys(S)) if (k !== 'ord') S[k] = '';
        location.hash = cfg.base;   // ricarica la lista da zero
      } }, 'Azzera i filtri'));
    form.append(toggle, altri);

    function disegna() {
      let arr = cfg.filtra(S);
      if (cfg.ordina) arr = cfg.ordina(S, arr);
      const n = arr.length;
      contatore.textContent = n === 0 ? 'Nessun risultato' : `${num(n)} ${n === 1 ? cfg.singolare : cfg.plurale}`;
      risultati.replaceChildren();
      if (!n) { risultati.append(h('p', { class: 'vuoto' }, 'Nessun risultato. Prova a togliere qualche filtro.')); return; }
      if (cfg.raggruppa && cfg.raggruppa(S)) { cfg.disegnaGruppi(S, arr, risultati); return; }
      const griglia = h('ul', { class: 'griglia' + (cfg.classeGriglia ? ' ' + cfg.classeGriglia : '') });
      const aggiungi = (da, a) => { for (const x of arr.slice(da, a)) griglia.append(h('li', null, cfg.card(x))); };
      aggiungi(0, mostrati);
      risultati.append(griglia);
      if (n > mostrati) {
        const btn = h('button', { type: 'button', class: 'bottone secondario altri', onclick: () => {
          const prima = mostrati;
          mostrati += cfg.per || 48;
          aggiungi(prima, mostrati);
          if (mostrati >= n) btn.remove(); else btn.textContent = `Mostra altri (${n - mostrati})`;
          const primo = griglia.children[prima];
          const a = primo && primo.querySelector('a, h3');
          if (a) a.focus({ preventScroll: true });
        } }, `Mostra altri (${n - mostrati})`);
        risultati.append(btn);
      }
    }

    const radice = h('section', null,
      h('h1', { class: 'titolo-pagina' }, cfg.titolo),
      h('p', { class: 'intro' }, cfg.intro),
      form, contatore, risultati);
    if (cfg.dipendenti) cfg.dipendenti(S, elementi);
    disegna();
    return radice;
  }

  /* ---------- Dispensa ---------- */

  function viewDispensa(params) {
    const regioniTutte = [...new Set(D.dispensa.flatMap(x => x.regioni))].sort((a, b) => a.localeCompare(b, 'it'));
    const provPerRegione = reg => [...new Set(D.dispensa.flatMap(x => x.origini)
      .filter(o => o.provincia && o.regione && (!reg || o.regione === reg)).map(o => o.provincia))].sort();
    return paginaLista({
      sezione: 'dispensa', base: '#/dispensa', params, titolo: 'Dispensa',
      intro: 'Ogni prodotto alimentare che Peck vende online, una volta sola anche se sta in più box. Per ognuno: chi lo fa e dove, e quanto siamo sicuri.',
      singolare: 'prodotto', plurale: 'prodotti', per: 48,
      campi: [
        { k: 'q', tipo: 'cerca', etichetta: 'Cerca un prodotto, un’azienda o un paese', segnaposto: 'per esempio: panettone, Pordenone, tartufo' },
        { k: 'cat', tipo: 'select', etichetta: 'Categoria', opzioni: () => D.meta.categorie.filter(c => D.dispensa.some(x => x.categoria === c)).map(c => [c, cap(c)]) },
        { k: 'reg', tipo: 'select', etichetta: 'Regione o paese', opzioni: () => regioniTutte, azzera: ['prov'] },
        { k: 'prov', tipo: 'select', etichetta: 'Provincia', opzioni: S => provPerRegione(S.reg) },
        { k: 'cert', tipo: 'select', etichetta: 'Quanto siamo sicuri', opzioni: () => ORDINE_STATI.map(s => [s, cap(STATI[s])]) },
        { k: 'shop', tipo: 'spunta', etichetta: 'Il produttore ha uno shop online' },
      ],
      dipendenti: (S, el) => {
        const sel = el.prov; if (!sel) return;
        const cur = S.prov || '';
        sel.replaceChildren(h('option', { value: '' }, 'Tutte'), ...provPerRegione(S.reg).map(p => h('option', { value: p }, p)));
        sel.value = provPerRegione(S.reg).includes(cur) ? cur : '';
        S.prov = sel.value;
      },
      filtra: S => {
        const q = norm(S.q).split(/\s+/).filter(Boolean);
        return D.dispensa.filter(x =>
          (!S.cat || x.categoria === S.cat) &&
          (!S.cert || x.stato === S.cert) &&
          (!S.shop || x.shop) &&
          (!S.reg || x.origini.some(o => o.regione === S.reg)) &&
          (!S.prov || x.origini.some(o => o.provincia === S.prov)) &&
          q.every(t => x.k.includes(t)));
      },
      ordina: (S, a) => a.slice().sort((x, y) => x.nome.localeCompare(y.nome, 'it', { numeric: true })),
      card: schedaItem,
    });
  }

  function linkAzienda(z) {
    const righe = [];
    const sito = ext(z.sito, 'Sito ufficiale', 'bottone secondario piccolo');
    if (sito) righe.push(sito);
    const shop = ext(z.link_shop, 'Compra dal produttore', 'bottone piccolo');
    if (shop) righe.push(shop);
    return righe;
  }

  function testoShop(z) {
    if (z.link_shop) return 'Ha uno shop online (vedi il bottone).';
    if (z.shop_online === 'si') return 'Ha uno shop online.';
    if (z.shop_online === 'no') return 'Sul suo sito non abbiamo trovato un negozio online (non è una prova che non esista).';
    return 'Non abbiamo verificato se ha un negozio online.';
  }

  function viewProdotto(id) {
    const it = mappe.item.get(id);
    if (!it) return nonTrovato();
    document.title = it.nome + ' – Peck Tracker';
    const origini = it.origini.map(o => {
      const z = mappe.az.get(o.azienda);
      const dl = h('dl', { class: 'dati' });
      const riga = (k, v) => { if (v) dl.append(h('dt', null, k), h('dd', null, v)); };
      riga('Indirizzo', [o.indirizzo, o.cap, luogo(o.comune || '', o.provincia)].filter(Boolean).join(', ') || (o.comune_azienda ? `${o.comune_azienda}${o.provincia ? ' (' + o.provincia + ')' : ''} (luogo preso dall’azienda)` : ''));
      riga('Regione o paese', o.regione || o.paese);
      riga('Bollo sanitario / codice', o.bollo);
      riga('Produttore nominato da Peck', o.nominato);
      return h('div', { class: 'origine' },
        o.frase ? h('p', { class: 'etichetta' }, `Come lo scrive Peck${o.ruolo ? ' (' + o.ruolo + ')' : ''}`) : h('p', { class: 'etichetta' }, 'Origine'),
        o.frase ? h('blockquote', { class: 'frase', style: 'margin-left:0;margin-right:0' }, '«' + o.frase + '»') : h('p', null, 'Nella scheda del prodotto Peck non scrive dove è fatto.'),
        dl.children.length ? dl : null,
        o.nota && !/nessuna frase|stessa origine/.test(o.nota) ? h('p', { class: 'meta' }, 'Nota: ', o.nota) : null,
        z ? h('div', { class: 'azienda-riquadro' },
          h('p', { class: 'etichetta' }, o.stato === 'peck' ? 'Chi lo fa' : 'Chi c’è dietro'),
          h('h3', null, z.trovata || z.id === 'peck' ? h('a', { href: '#/produttore/' + z.id }, z.nome) : 'Azienda non trovata'),
          h('p', null, badge(o.stato)),
          z.marchio && z.trovata && z.id !== 'peck' ? h('p', { class: 'meta' }, 'Marchio: ', z.marchio) : null,
          z.id !== 'peck' ? h('p', { class: 'meta' }, testoShop(z)) : null,
          h('div', { class: 'gruppo-bottoni' }, linkAzienda(z)),
          z.fonti && z.fonti.length ? h('p', { class: 'meta' }, 'Fonte: ', ext(z.fonti[0], 'dove l’abbiamo trovato')) : null,
          z.note && z.note.length ? h('details', null, h('summary', null, 'Note della ricerca'), z.note.map(n => h('p', null, n))) : null,
        ) : null);
    });
    const inBox = it.box.map(bid => mappe.box.get(bid)).filter(Boolean);
    return h('article', null,
      h('a', { class: 'torna', href: ultimaLista.dispensa || '#/dispensa' }, '← Torna alla dispensa'),
      h('div', { class: 'dettaglio' },
        foto(it.foto, 'Foto di ' + it.nome + ' dal sito Peck', { etichetta: it.foto_tipo === 'box' ? 'Foto della box' : '' }),
        h('div', null,
          h('p', { class: 'etichetta' }, cap(it.categoria)),
          h('h1', null, it.nome),
          h('p', { class: 'originale' }, 'Nome su Peck: ', it.nome_originale),
          it.foto_tipo === 'box' ? h('p', { class: 'meta' }, `Peck non mostra una foto di questo prodotto da solo: quella a fianco è della box «${it.foto_da}».`) : null,
          h('p', null, badge(it.stato), ' ', h('span', { class: 'meta' }, it.origini.length > 1 ? ' Peck indica più di un luogo: sono tutti qui sotto.' : ''))),
      ),
      h('section', { class: 'sezione' }, h('h2', null, 'Chi lo fa e dove'), origini.length ? origini : h('p', null, 'Nessuna indicazione.')),
      h('section', { class: 'sezione' },
        h('h2', null, inBox.length === 1 ? 'Dove lo trovi su Peck' : `Lo trovi in ${inBox.length} pagine di Peck`),
        h('ul', { class: 'griglia' }, inBox.map(b => h('li', null, schedaBox(b)))),
        h('p', { class: 'meta', style: 'margin-top:1rem' }, 'Le pagine qui sopra sono le nostre; da ognuna puoi andare alla pagina originale di Peck.')));
  }

  /* ---------- Box regalo ---------- */

  function viewBoxLista(params) {
    return paginaLista({
      sezione: 'box', base: '#/box', params, titolo: 'Box regalo',
      intro: 'Le 46 pagine dello shop di Peck: box regalo e qualche prodotto singolo (panettoni, pandoro, salmone). Aprine una per vederla “spacchettata”: ogni prodotto con chi lo fa.',
      singolare: 'pagina', plurale: 'pagine', per: 48,
      campi: [
        { k: 'q', tipo: 'cerca', etichetta: 'Cerca una box', segnaposto: 'per esempio: Krug, tartufo, caffè' },
        { k: 'ord', tipo: 'select', etichetta: 'Ordina', opzioni: () => [['nome', 'Nome'], ['prezzo-su', 'Prezzo: dal più basso'], ['prezzo-giu', 'Prezzo: dal più alto'], ['n', 'Più prodotti']] },
        { k: 'tipo', tipo: 'select', etichetta: 'Tipo', opzioni: () => [['box', 'Box regalo'], ['singolo', 'Prodotto singolo']] },
      ],
      filtra: S => {
        const q = norm(S.q).split(/\s+/).filter(Boolean);
        return D.box.filter(b => (!S.tipo || b.tipo === S.tipo) && q.every(t => b.k.includes(t) ||
          b.elementi.some(id => mappe.item.get(id).k.includes(t))));
      },
      ordina: (S, a) => {
        const f = {
          'prezzo-su': (x, y) => x.prezzo - y.prezzo, 'prezzo-giu': (x, y) => y.prezzo - x.prezzo,
          n: (x, y) => y.n_elementi - x.n_elementi,
        }[S.ord] || ((x, y) => x.nome.localeCompare(y.nome, 'it'));
        return a.slice().sort(f);
      },
      card: schedaBox,
    });
  }

  function viewBox(id) {
    const b = mappe.box.get(id);
    if (!b) return nonTrovato();
    document.title = b.nome + ' – Peck Tracker';
    const items = b.elementi.map(i => mappe.item.get(i)).filter(Boolean);
    const conAzienda = items.filter(i => i.stato === 'certa' || i.stato === 'probabile').length;
    const righe = items.map(it => {
      const c = chiFa(it);
      return h('li', null, h('a', { class: 'riga-el', href: '#/prodotto/' + it.id },
        h('span', null, h('span', { class: 'cat' }, cap(it.categoria)), h('br'), h('span', { class: 'nome' }, it.nome)),
        h('span', { class: 'meta' }, c.riga),
        badge(c.stato)));
    });
    return h('article', null,
      h('a', { class: 'torna', href: ultimaLista.box || '#/box' }, '← Torna alle box'),
      h('div', { class: 'dettaglio' },
        foto(b.foto, 'Foto di ' + b.nome + ' dal sito Peck'),
        h('div', null,
          h('p', { class: 'etichetta' }, b.tipo === 'box' ? 'Box regalo' : 'Prodotto singolo'),
          h('h1', null, b.nome),
          h('p', null, h('span', { class: 'prezzo' }, b.prezzo_testo), h('span', { class: 'meta' }, ' · prezzo scritto da Peck, il giorno della fotografia dei dati')),
          h('p', null, `${items.length} ${items.length === 1 ? 'prodotto' : 'prodotti'}; per ${conAzienda} abbiamo trovato l’azienda (certa o probabile).`),
          h('div', { class: 'gruppo-bottoni' }, ext(b.url, 'Vedi la pagina su Peck', 'bottone secondario piccolo')),
          h('p', { class: 'meta' }, 'Su questo sito non si compra niente: il link porta alla pagina originale di Peck.'))),
      h('section', { class: 'sezione' }, h('h2', null, 'La box spacchettata'),
        h('ul', { class: 'righe' }, righe)));
  }

  /* ---------- Produttori ---------- */

  function viewProduttori(params) {
    const regioni = [...new Set(D.produttori.map(z => z.regione).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'it'));
    return paginaLista({
      sezione: 'produttori', base: '#/produttori', params, titolo: 'Produttori',
      intro: 'Le aziende dietro i prodotti. Una scheda per azienda (o per indirizzo, se non siamo riusciti a risalire a chi sia). Molte fanno il prodotto che Peck poi vende con il suo nome.',
      singolare: 'produttore', plurale: 'produttori', per: 1000, classeGriglia: 'larga',
      campi: [
        { k: 'q', tipo: 'cerca', etichetta: 'Cerca un’azienda, un comune o un marchio', segnaposto: 'per esempio: Follador, Norcia, pasta' },
        { k: 'cert', tipo: 'select', etichetta: 'Quanto siamo sicuri', opzioni: () => ORDINE_STATI.filter(s => s !== 'nessuna').map(s => [s, cap(STATI[s])]) },
        { k: 'reg', tipo: 'select', etichetta: 'Regione o paese', opzioni: () => regioni },
        { k: 'gr', tipo: 'select', etichetta: 'Elenco', vuoto: 'Elenco unico', opzioni: () => [['reg', 'Raggruppato per regione']] },
        { k: 'shop', tipo: 'spunta', etichetta: 'Ha uno shop online' },
      ],
      raggruppa: S => S.gr === 'reg',
      disegnaGruppi: (S, arr, dove) => {
        const gruppi = new Map();
        for (const z of arr) {
          const r = z.regione || 'Sede non indicata';
          if (!gruppi.has(r)) gruppi.set(r, []);
          gruppi.get(r).push(z);
        }
        const chiavi = [...gruppi.keys()].sort((a, b) => (a === 'Sede non indicata') - (b === 'Sede non indicata') || a.localeCompare(b, 'it'));
        for (const r of chiavi) {
          dove.append(h('section', { class: 'gruppo-reg' }, h('h2', null, `${r} (${gruppi.get(r).length})`),
            h('ul', { class: 'griglia larga' }, gruppi.get(r).map(z => h('li', null, schedaAzienda(z))))));
        }
      },
      filtra: S => {
        const q = norm(S.q).split(/\s+/).filter(Boolean);
        return D.produttori.filter(z =>
          (!S.cert || z.certezza === S.cert) && (!S.shop || z.shop) && (!S.reg || z.regione === S.reg) &&
          q.every(t => z.k.includes(t) || z.prodotti.some(id => mappe.item.get(id).k.includes(t))));
      },
      ordina: (S, a) => a,
      card: schedaAzienda,
    });
  }

  function viewProduttore(id) {
    const z = mappe.az.get(id);
    if (!z) return nonTrovato();
    document.title = (z.trovata ? z.nome : 'Azienda non trovata') + ' – Peck Tracker';
    const prod = z.prodotti.map(i => mappe.item.get(i)).filter(Boolean).sort((a, b) => a.nome.localeCompare(b.nome, 'it'));
    const dove = luogo(z.comune, z.provincia);
    const chiavi = z.chiavi.map(c => h('li', null,
      h('strong', null, TIPI_CHIAVE[c.tipo] || c.tipo), ': ', c.chiave, ' ', badge(c.certezza),
      c.fonte ? [' · ', ext(c.fonte, 'fonte')] : ''));
    return h('article', null,
      h('a', { class: 'torna', href: ultimaLista.produttori || '#/produttori' }, '← Torna ai produttori'),
      h('p', { class: 'etichetta' }, z.id === 'peck' ? 'Peck stessa' : 'Produttore'),
      h('h1', null, z.trovata || z.id === 'peck' ? z.nome : 'Azienda non trovata'),
      z.ragione && z.ragione !== z.nome && z.trovata ? h('p', { class: 'originale' }, 'Come risulta nei registri: ', z.ragione) : null,
      h('p', null, badge(z.certezza), ' ', z.shop ? h('span', { class: 'badge b-shop' }, 'shop online') : null),
      h('dl', { class: 'dati' },
        z.marchio && z.id !== 'peck' ? [h('dt', null, 'Marchio'), h('dd', null, z.marchio)] : null,
        dove || z.paese ? [h('dt', null, 'Dove'), h('dd', null, [dove, z.regione && z.regione !== z.paese ? z.regione : '', z.paese && z.paese !== 'Italia' ? z.paese : ''].filter(Boolean).join(' · '))] : [h('dt', null, 'Dove'), h('dd', null, 'sede non indicata nei dati di Peck')],
        z.id !== 'peck' ? [h('dt', null, 'Negozio online'), h('dd', null, testoShop(z))] : null),
      h('div', { class: 'gruppo-bottoni' }, linkAzienda(z)),
      z.chiavi.length ? h('section', { class: 'sezione' }, h('h2', null, 'Come l’abbiamo trovata'),
        h('ul', null, chiavi),
        z.fonti.length > 1 || (z.fonti.length === 1 && !z.chiavi.some(c => c.fonte)) ? h('p', { class: 'meta' }, 'Altre fonti: ', z.fonti.map(f => [ext(f, 'fonte'), ' '])) : null,
        z.note.length ? h('details', null, h('summary', null, 'Note della ricerca'), z.note.map(n => h('p', null, n))) : null) : (z.note.length ? h('details', null, h('summary', null, 'Note'), z.note.map(n => h('p', null, n))) : null),
      h('section', { class: 'sezione' }, h('h2', null, `Cosa fa per Peck (${prod.length})`),
        h('ul', { class: 'righe' }, prod.map(it => h('li', null, h('a', { class: 'riga-el', href: '#/prodotto/' + it.id },
          h('span', null, h('span', { class: 'cat' }, cap(it.categoria)), h('br'), h('span', { class: 'nome' }, it.nome)),
          h('span', { class: 'meta' }, it.box.length === 1 ? 'in 1 pagina di Peck' : `in ${it.box.length} pagine di Peck`), ))))));
  }

  /* ---------- Enoteca ---------- */

  function viewEnoteca(params) {
    const M = V.meta;
    return paginaLista({
      sezione: 'enoteca', base: '#/enoteca', params, titolo: 'Enoteca',
      intro: `${num(M.n_vini)} vini della carta dell’enoteca di Peck, di ${M.n_cantine} cantine. Qui trovi che cosa sono; per la scheda completa c’è il link all’enoteca (Winerim). I prezzi sono quelli della fotografia del ${new Date(M.data).toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' })}.`,
      singolare: 'vino', plurale: 'vini', per: 48,
      campi: [
        { k: 'q', tipo: 'cerca', etichetta: 'Cerca un vino, un’uva o una cantina', segnaposto: 'per esempio: Barolo, Nebbiolo, Gaja' },
        { k: 'tipo', tipo: 'select', etichetta: 'Tipo', opzioni: () => M.tipi.map(t => [t, cap(t)]) },
        { k: 'paese', tipo: 'select', etichetta: 'Paese', opzioni: () => M.paesi, azzera: ['reg'] },
        { k: 'reg', tipo: 'select', etichetta: 'Regione', opzioni: S => M.regioni.filter(r => !S.paese || r[0] === S.paese).map(r => r[1]).filter((x, i, a) => a.indexOf(x) === i).sort((a, b) => a.localeCompare(b, 'it')) },
        { k: 'can', tipo: 'testolista', etichetta: 'Cantina', segnaposto: 'scrivi il nome', suggerimenti: () => V.cantine.map(c => c.nome) },
        { k: 'pmin', tipo: 'num', etichetta: 'Prezzo da (€)', segnaposto: 'da' },
        { k: 'pmax', tipo: 'num', etichetta: 'Prezzo fino a (€)', segnaposto: 'fino a' },
        { k: 'ord', tipo: 'select', etichetta: 'Ordina', opzioni: () => [['nome', 'Nome'], ['prezzo-su', 'Prezzo: dal più basso'], ['prezzo-giu', 'Prezzo: dal più alto'], ['annata-giu', 'Annata: dalla più recente'], ['annata-su', 'Annata: dalla più vecchia']] },
      ],
      dipendenti: (S, el) => {
        const sel = el.reg; if (!sel) return;
        const regs = M.regioni.filter(r => !S.paese || r[0] === S.paese).map(r => r[1]).filter((x, i, a) => a.indexOf(x) === i).sort((a, b) => a.localeCompare(b, 'it'));
        const cur = S.reg || '';
        sel.replaceChildren(h('option', { value: '' }, 'Tutte'), ...regs.map(r => h('option', { value: r }, r)));
        sel.value = regs.includes(cur) ? cur : '';
        S.reg = sel.value;
      },
      filtra: S => {
        const q = norm(S.q).split(/\s+/).filter(Boolean);
        const can = norm(S.can).trim();
        const pmin = S.pmin !== '' && S.pmin != null ? Number(S.pmin) : null;
        const pmax = S.pmax !== '' && S.pmax != null ? Number(S.pmax) : null;
        const ti = S.tipo ? M.tipi.indexOf(S.tipo) : -1;
        const pi = S.paese ? M.paesi.indexOf(S.paese) : -1;
        return V.vini.filter(w =>
          (ti < 0 || w.t === ti) && (pi < 0 || w.p === pi) && (!S.reg || w.r === S.reg) &&
          (!can || w.kc.includes(can)) &&
          (pmin == null || (w.pr != null && w.pr >= pmin)) && (pmax == null || (w.pr != null && w.pr <= pmax)) &&
          q.every(t => w.k.includes(t)));
      },
      ordina: (S, a) => {
        const senza = (x, y, f) => (x.pr == null) - (y.pr == null) || f(x, y);   // senza prezzo in fondo
        const f = {
          'prezzo-su': (x, y) => senza(x, y, (a1, b1) => a1.pr - b1.pr),
          'prezzo-giu': (x, y) => senza(x, y, (a1, b1) => b1.pr - a1.pr),
          'annata-giu': (x, y) => (Number(y.a) || 0) - (Number(x.a) || 0),
          'annata-su': (x, y) => (Number(x.a) || 9999) - (Number(y.a) || 9999),
        }[S.ord] || ((x, y) => x.n.localeCompare(y.n, 'it', { numeric: true }));
        return a.slice().sort(f);
      },
      card: schedaVino,
    });
  }

  function viewCantina(id, params) {
    const c = V.cantineId.get(id);
    if (!c) return nonTrovato();
    document.title = c.nome + ' – Peck Tracker';
    const S = leggiQuery(params);
    let mostrati = 48;
    const vini = c.vini.slice().sort((a, b) => a.n.localeCompare(b.n, 'it', { numeric: true }));
    const elenco = h('ul', { class: 'griglia' });
    const wrap = h('div');
    const agg = (da, a) => vini.slice(da, a).forEach(w => elenco.append(h('li', null, schedaVino(w))));
    agg(0, mostrati);
    wrap.append(elenco);
    if (vini.length > mostrati) {
      const btn = h('button', { type: 'button', class: 'bottone secondario altri', onclick: () => {
        const prima = mostrati; mostrati += 48; agg(prima, mostrati);
        if (mostrati >= vini.length) btn.remove(); else btn.textContent = `Mostra altri (${vini.length - mostrati})`;
      } }, `Mostra altri (${vini.length - mostrati})`);
      wrap.append(btn);
    }
    const tipi = Object.entries(c.tipi).filter(([, n]) => n > 0);
    const inBox = (c.box || []).map(b => mappe.box && mappe.box.get(b)).filter(Boolean);
    return h('article', null,
      h('a', { class: 'torna', href: ultimaLista.enoteca || '#/enoteca' }, '← Torna all’enoteca'),
      h('p', { class: 'etichetta' }, 'Cantina'),
      h('h1', null, c.nome),
      h('p', { class: 'meta' }, [c.paese, c.regioni].filter(Boolean).join(' · ')),
      h('div', { class: 'stat' },
        h('div', null, h('b', null, c.n), c.n === 1 ? 'etichetta in carta' : 'etichette in carta'),
        c.pmin != null ? h('div', null, h('b', null, c.pmin === c.pmax ? euro(c.pmin) : `${euro(c.pmin)} – ${euro(c.pmax)}`), 'prezzi in carta') : null),
      tipi.length ? h('p', null, tipi.map(([t, n], i) => [i ? ' · ' : '', tipoChip(t), ` ${n}`])) : null,
      c.nota ? h('p', { class: 'meta' }, 'Nota: ', c.nota) : null,
      inBox.length ? h('section', { class: 'sezione' }, h('h2', null, 'Compare anche nelle box regalo'),
        h('ul', { class: 'griglia' }, inBox.map(b => h('li', null, schedaBox(b))))) : null,
      h('section', { class: 'sezione' }, h('h2', null, `Tutte le etichette (${vini.length})`), wrap));
  }

  /* ---------- Come funziona ---------- */

  function viewCome() {
    document.title = 'Come funziona – Peck Tracker';
    const M = D.meta;
    const dataLunga = new Date(M.data).toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' });
    const conta = D.dispensa.reduce((a, x) => { a[x.stato] = (a[x.stato] || 0) + 1; return a; }, {});
    const nomiCsv = ['prodotti', 'elementi', 'indirizzi', 'altre_origini', 'aziende', 'vini', 'cantine', 'vini_nelle_box'];
    const parole = M.categorie.filter(c => M.categorie_parole[c]).map(c => h('tr', null,
      h('td', null, cap(c)),
      h('td', null, M.categorie_parole[c].map(p => p.startsWith('^') ? `inizia con «${p.slice(1).trim()}»` : `«${p.trim()}»`).join(', '))));
    return h('article', { class: 'testo-lungo' },
      h('h1', null, 'Come funziona'),
      h('p', { class: 'intro' }, 'Peck Tracker è un progetto di appassionati. Sembra un catalogo, ma non vende niente: dice chi fa i prodotti che Peck Milano vende online e che cosa c’è nella carta dei vini della sua enoteca.'),
      h('p', null, h('strong', null, 'Progetto indipendente di appassionati, non affiliato a Peck. Nessun prodotto in vendita.')),

      h('h2', null, 'Da dove vengono i dati'),
      h('ul', null,
        h('li', null, h('strong', null, 'Lo shop. '), `Abbiamo letto le ${M.n_box} pagine dello shop online di Peck e, di ogni prodotto, solo la frase in cui Peck scrive dove è prodotto o confezionato ("Prodotto in via…", "Confezionato da…", il bollo CE degli stabilimenti). Non copiamo ingredienti né descrizioni.`),
        h('li', null, h('strong', null, 'Le aziende. '), 'Per ogni indirizzo, bollo CE o produttore nominato abbiamo cercato a mano, sul web, chi c’è dietro. Ogni riga ha la sua fonte (registri delle imprese, siti ufficiali, gli elenchi europei degli stabilimenti riconosciuti). Non è un lavoro fatto da un programma.'),
        h('li', null, h('strong', null, 'L’enoteca. '), `La carta dei vini è quella che l’enoteca di Peck pubblica su Winerim: ${V ? num(V.meta.n_vini) : num(M.n_vini)} vini di ${M.n_cantine} cantine.`)),

      h('h2', null, 'Quanto siamo sicuri'),
      h('p', null, 'Ogni azienda ha un’etichetta:'),
      h('ul', null,
        h('li', null, badge('certa'), ' una fonte mostra proprio quell’indirizzo o quel codice con quell’azienda.'),
        h('li', null, badge('probabile'), ' l’indizio è forte ma indiretto.'),
        h('li', null, badge('non trovata'), ' non siamo riusciti a risalire all’azienda.'),
        h('li', null, badge('peck'), ' Peck scrive di aver fatto o confezionato il prodotto nella sua sede di via Spadari 9, a Milano.'),
        h('li', null, badge('nessuna'), ' nella scheda del prodotto Peck non scrive dove è fatto.')),
      h('p', null, `Sui ${M.n_elementi} prodotti della dispensa: ${conta.certa || 0} hanno un’azienda certa, ${conta.probabile || 0} probabile, ${conta['non trovata'] || 0} non trovata, ${conta.peck || 0} sono fatti da Peck stessa e per ${conta.nessuna || 0} Peck non indica nulla. Se un prodotto ha più luoghi, l’etichetta mostra quella più sicura.`),

      h('h2', null, 'I limiti, detti chiaramente'),
      h('ul', null,
        h('li', null, `È una fotografia del ${dataLunga}. Prezzi, box e vini cambiano: oggi il catalogo è quello delle “Selezioni Natalizie”.`),
        h('li', null, 'Contiamo solo quello che Peck vende online, non quello che c’è nei suoi negozi.'),
        h('li', null, 'L’indirizzo che Peck scrive può essere quello di chi confeziona, non di chi fabbrica. Peck usa “prodotto in”, “prodotto e confezionato in”, “confezionato da” senza spiegare la differenza: noi teniamo la parola e la frase esatta.'),
        h('li', null, 'Molte aziende lavorano per conto terzi: fanno il prodotto che Peck vende con il suo nome. Non vuol dire che Peck non c’entri: dice solo chi lo fabbrica.'),
        h('li', null, 'Il bollo CE dice dove sta lo stabilimento, non di chi è: l’azienda va cercata negli elenchi. Alcuni codici non sono bolli sanitari.'),
        h('li', null, 'Le righe “non trovata” sono dove la ricerca non è arrivata; si possono riprovare. “Nessuno shop online” vuol dire solo che non l’abbiamo trovato sul sito ufficiale.'),
        h('li', null, 'I testi di Peck hanno refusi (per esempio “Ortobello” per “Orbetello”). Le frasi sono copiate com’erano; dove due scritture indicano chiaramente lo stesso posto, le abbiamo unite.'),
        h('li', null, 'Alcuni prodotti non hanno una foto tutta loro: usiamo quella della box più piccola in cui compaiono e lo scriviamo sulla foto.'),
        h('li', null, 'Nell’enoteca l’intestazione della carta parla di 1.005 cantine, ma l’elenco pubblico ne mostra 820 (3.071 vini). Non sappiamo perché: forse sono vini archiviati o nascosti.'),
        h('li', null, 'I vini senza prezzo nella carta compaiono con “prezzo non indicato”.')),

      h('h2', null, 'Come sono scelte le categorie'),
      h('p', null, 'Le categorie dei prodotti sono decise da un programma che cerca alcune parole nel nome del prodotto: la prima categoria che trova vince. Non è una classificazione ufficiale e qualche prodotto può finire nella categoria sbagliata. Le parole sono queste (il resto va in «altro»):'),
      h('div', { class: 'tab-scorri' }, h('table', { class: 'tab' }, h('thead', null, h('tr', null, h('th', null, 'Categoria'), h('th', null, 'Parole cercate nel nome'))), h('tbody', null, parole))),

      h('h2', null, 'Foto e riservatezza'),
      h('p', null, 'Le foto non sono copiate su questo sito: il tuo browser le carica dai server di Peck (shop.peck.it) e di Winerim. Per questo quei server vedono la tua visita, e se cambiano o tolgono una foto qui compare un riquadro vuoto. I caratteri del sito vengono da Google Fonts. Questo sito non usa cookie né statistiche.'),

      h('h2', null, 'Dati e codice'),
      h('p', null, 'Tutto è pubblico: le tabelle (si aprono bene anche con Excel) e i programmi che le costruiscono.'),
      h('ul', null,
        h('li', null, ext(M.repo, 'Il progetto su GitHub')),
        nomiCsv.map((n, i) => h('li', null, ext(M.csv[i], `data/${n}.csv`)))),
      h('p', null, 'Hai trovato un errore o sai chi fa un prodotto “non trovato”? Apri una segnalazione su GitHub: ', ext(M.repo + '/issues', 'segnalazioni'), '.'));
  }

  function nonTrovato() {
    document.title = 'Pagina non trovata – Peck Tracker';
    return h('div', { class: 'vuoto' }, h('h1', null, 'Pagina non trovata'),
      h('p', null, 'Questo indirizzo non esiste (o i dati sono stati aggiornati).'), h('a', { class: 'bottone', href: '#/dispensa' }, 'Vai alla dispensa'));
  }

  /* ---------- percorsi ---------- */

  const TITOLI = { dispensa: 'Dispensa', box: 'Box regalo', produttori: 'Produttori', enoteca: 'Enoteca', 'come-funziona': 'Come funziona' };
  let ultimoPercorso = '';

  async function percorso() {
    const hash = location.hash && location.hash.length > 2 ? location.hash : '#/dispensa';
    const [pathStr, qs] = hash.slice(2).split('?');
    const parti = pathStr.split('/').filter(Boolean).map(decodeURIComponent);
    const sez = { prodotto: 'dispensa', produttore: 'produttori', cantina: 'enoteca', vino: 'enoteca' }[parti[0]] || parti[0] || 'dispensa';
    for (const a of menu.querySelectorAll('a')) {
      if (a.dataset.sez === sez) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    }
    const chiave = pathStr;
    const stessaLista = chiave === ultimoPercorso && parti.length === 1;
    ultimoPercorso = chiave;
    let nodo;
    try {
      if (sez === 'enoteca') { await Promise.all([serveDati(), serveVini()]); } else { await serveDati(); }
      const [p0, p1] = parti;
      if (p0 === 'dispensa' || !p0) { document.title = 'Dispensa – Peck Tracker'; nodo = viewDispensa(qs); }
      else if (p0 === 'prodotto') nodo = viewProdotto(p1);
      else if (p0 === 'box') { if (p1) nodo = viewBox(p1); else { document.title = 'Box regalo – Peck Tracker'; nodo = viewBoxLista(qs); } }
      else if (p0 === 'produttori') { document.title = 'Produttori – Peck Tracker'; nodo = viewProduttori(qs); }
      else if (p0 === 'produttore') nodo = viewProduttore(p1);
      else if (p0 === 'enoteca') { document.title = 'Enoteca – Peck Tracker'; nodo = viewEnoteca(qs); }
      else if (p0 === 'cantina') { await serveVini(); nodo = viewCantina(p1, qs); }
      else if (p0 === 'come-funziona') { await serveVini().catch(() => {}); nodo = viewCome(); }
      else nodo = nonTrovato();
    } catch (e) {
      console.error(e);
      nodo = h('div', { class: 'vuoto' }, h('p', null, 'Non sono riuscito a caricare i dati. Controlla la connessione e riprova.'),
        h('button', { class: 'bottone', type: 'button', onclick: () => location.reload() }, 'Riprova'));
    }
    main.replaceChildren(nodo);
    if (!stessaLista) {
      window.scrollTo(0, 0);
      main.focus({ preventScroll: true });
    }
  }

  window.addEventListener('hashchange', percorso);
  percorso();
})();
