/* Peck Tracker – la pagina «Mappa» (/mappa/). Scritto a mano: src/sito.py non lo tocca.
   Legge mappa.json (scritto da sito.py) e disegna con Leaflet + Leaflet.markercluster (da cdnjs, caricati dalla pagina):
   - strato «Dispensa»: un segno per fornitore, colore = categoria principale, grandezza = prodotti per Peck,
     contorno tratteggiato se la posizione è solo il comune; i segni vicini si raggruppano;
   - strato «Enoteca»: un cerchio per regione del vino, raggio = etichette.
   L'indirizzo #<id> apre il segno di quel fornitore (o #v-<paese>-<regione> la regione del vino, #enoteca lo strato).
   Se Leaflet o i dati non si caricano, la pagina resta utile: l'elenco sotto la mappa è HTML normale. */
(() => {
  'use strict';
  const cont = document.getElementById('mappa');
  if (!cont) return;
  const radice = document.body.dataset.radice || './';
  const msgEl = document.getElementById('mappa-msg');
  const msg = t => { if (msgEl) { msgEl.textContent = t; msgEl.hidden = false; } };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const ridotto = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (!window.L || !L.markerClusterGroup) {
    msg('La mappa non si è caricata (le librerie arrivano da cdnjs). L’elenco qui sotto funziona lo stesso.');
    return;
  }
  fetch(radice + 'mappa.json').then(r => (r.ok ? r.json() : Promise.reject(new Error('mappa.json')))).then(avvia)
    .catch(() => msg('I dati della mappa non si sono caricati. L’elenco qui sotto funziona lo stesso.'));

  function avvia(D) {
    const colore = {};
    for (const c of D.meta.categorie) colore[c[0]] = c[2];

    const mappa = L.map(cont, { scrollWheelZoom: false, minZoom: 2, worldCopyJump: true, zoomSnap: 0.5 });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      referrerPolicy: 'strict-origin-when-cross-origin',
      attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
    }).addTo(mappa);
    // la rotella zooma solo dopo un clic sulla mappa, così non blocca lo scorrimento della pagina
    mappa.on('click focus', () => mappa.scrollWheelZoom.enable());
    cont.addEventListener('mouseleave', () => mappa.scrollWheelZoom.disable());

    /* ---------- strato Dispensa ---------- */
    const marcatori = {};
    const gruppoD = L.markerClusterGroup({
      showCoverageOnHover: false, maxClusterRadius: 32, spiderfyOnMaxZoom: true,
      iconCreateFunction: c => {
        const n = c.getChildCount(), d = n < 10 ? 34 : n < 30 ? 42 : 50;
        return L.divIcon({ html: '<span>' + n + '</span>', className: 'cluster-icona', iconSize: [d, d] });
      }
    });
    const popupFornitore = f => {
      const prod = f.pd.map(p => '<li><a href="' + radice + 'prodotto/' + esc(p[0]) + '/">' + esc(p[1]) + '</a></li>').join('');
      const piu = f.np > f.pd.length ? '<li class="meta">e altri ' + (f.np - f.pd.length) + '</li>' : '';
      const dove = esc(f.c) + (f.pv ? ' (' + esc(f.pv) + ')' : '') + (f.rg && f.rg !== f.pa ? ' · ' + esc(f.rg) : '') + (f.pa !== 'Italia' ? ' · ' + esc(f.pa) : '');
      return '<div class="pop"><p class="pop-nome"><a href="' + radice + 'produttore/' + esc(f.i) + '/">' + esc(f.n) + '</a></p>' +
        '<p class="pop-dove">' + dove + '</p>' +
        (f.np ? '<p class="pop-t">Fa per Peck ' + f.np + (f.np === 1 ? ' prodotto' : ' prodotti') + ':</p><ul>' + prod + piu + '</ul>'
          : '<p class="meta">Fuori dallo shop online del 2026.</p>') +
        '<p class="meta">Quanto siamo sicuri: ' + esc(f.ce) + '. ' +
        (f.pr === 'via' ? 'Posizione trovata a livello di via.' : '<strong>Posizione approssimata al comune.</strong>') + '</p>' +
        (f.no ? '<p class="meta">' + esc(f.no) + '</p>' : '') + '</div>';
    };
    for (const f of D.fornitori) {
      const d = Math.round(14 + 5 * Math.sqrt(Math.max(f.np, 1)));
      const icona = L.divIcon({
        className: 'pin-icona', iconSize: [d, d], iconAnchor: [d / 2, d / 2], popupAnchor: [0, -d / 2],
        html: '<span class="pin' + (f.pr === 'via' ? '' : ' appr') + '" style="--c:' + (colore[f.ct] || '#8a8a8a') + '"></span>'
      });
      const m = L.marker([f.la, f.lo], { icon: icona, title: f.n, alt: f.n + ', ' + f.c, riseOnHover: true })
        .bindPopup(() => popupFornitore(f), { maxWidth: 280, autoPanPaddingTopLeft: [12, 70], autoPanPaddingBottomRight: [12, 12] });
      marcatori[f.i] = m;
      gruppoD.addLayer(m);
    }

    /* ---------- strato Enoteca ---------- */
    const regioni = {};
    const gruppoV = L.layerGroup();
    const popupRegione = v => '<div class="pop"><p class="pop-nome">' + esc(v.r) + ' <span class="meta">(' + esc(v.p) + ')</span></p>' +
      '<p>' + v.nc + (v.nc === 1 ? ' cantina' : ' cantine') + ' · circa ' + num(v.ne) + (v.ne === 1 ? ' etichetta' : ' etichette') + '</p>' +
      '<p><a href="' + radice + 'enoteca/' + esc(v.q) + '">Vedi i vini di questa regione nell’Enoteca</a></p>' +
      '<p class="meta">Punto approssimato: il centro della regione' + (v.ma ? ' (scelto a mano)' : '') + ', non una cantina.</p></div>';
    for (const v of D.vini) {   // già in ordine dal più grande: i piccoli restano sopra
      const c = L.circleMarker([v.la, v.lo], {
        radius: Math.min(40, 4 + 1.15 * Math.sqrt(v.ne)), color: '#6b1f43', weight: 1.5, fillColor: '#8e2c5a', fillOpacity: 0.35
      }).bindPopup(() => popupRegione(v), { maxWidth: 280, autoPanPaddingTopLeft: [12, 70] })
        .bindTooltip(v.r + ' · ' + num(v.ne) + ' etichette', { sticky: true });
      regioni[v.i] = c;
      gruppoV.addLayer(c);
    }

    /* ---------- strati e comandi ---------- */
    const bottoni = [...document.querySelectorAll('.strato')];
    const legD = document.getElementById('leg-dispensa'), legV = document.getElementById('leg-enoteca');
    const europa = L.latLngBounds([[35, -11], [56, 20]]);
    const confiniD = L.latLngBounds(D.fornitori.map(f => [f.la, f.lo])).pad(0.08);   // calcolati dai dati, non dal gruppo dei segni
    let corrente = null;
    function mostra(strato, adatta) {
      if (strato === corrente) return;
      corrente = strato;
      if (strato === 'enoteca') { mappa.removeLayer(gruppoD); gruppoV.addTo(mappa); } else { mappa.removeLayer(gruppoV); gruppoD.addTo(mappa); }
      for (const b of bottoni) b.setAttribute('aria-pressed', String(b.dataset.strato === strato));
      if (legD) legD.hidden = strato === 'enoteca';
      if (legV) legV.hidden = strato !== 'enoteca';
      if (adatta !== false) mappa.fitBounds(strato === 'enoteca' ? europa : confiniD, { animate: !ridotto });
    }
    for (const b of bottoni) {
      b.addEventListener('click', () => {
        mostra(b.dataset.strato);
        try { history.replaceState(null, '', b.dataset.strato === 'enoteca' ? '#enoteca' : location.pathname + location.search); } catch (e) { /* niente */ }
      });
    }

    const vaiAllaMappa = () => cont.scrollIntoView({ behavior: ridotto ? 'auto' : 'smooth', block: 'center' });
    function daIndirizzo(scorri) {
      let h = '';
      try { h = decodeURIComponent(location.hash.slice(1)); } catch (e) { return false; }
      if (!h) return false;
      if (h === 'enoteca') { mostra('enoteca'); return true; }
      if (regioni[h]) {
        mostra('enoteca', false);
        mappa.setView(regioni[h].getLatLng(), 6, { animate: false });
        regioni[h].openPopup();
        if (scorri) vaiAllaMappa();
        return true;
      }
      if (marcatori[h]) {
        mostra('dispensa', false);
        gruppoD.zoomToShowLayer(marcatori[h], () => marcatori[h].openPopup());
        if (scorri) vaiAllaMappa();
        return true;
      }
      return false;
    }

    cont.hidden = false;
    const strati = document.getElementById('strati');
    if (strati) strati.hidden = false;
    for (const a of document.querySelectorAll('a.sulla-mappa')) a.hidden = false;
    mappa.invalidateSize();
    mappa.fitBounds(confiniD, { animate: false });
    gruppoD.addTo(mappa);
    corrente = 'dispensa';
    if (legV) legV.hidden = true;
    setTimeout(() => daIndirizzo(true), 50);   // chi arriva da «vedi sulla mappa» trova la mappa in vista
    window.addEventListener('hashchange', () => daIndirizzo(true));
    window.ptMappa = mappa;   // per chi vuole provare dalla console
  }
})();
