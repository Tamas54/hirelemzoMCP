/**
 * echolot-yt-transcript.js — YouTube transcript inline-expand
 *
 * Minden `.yt-transcript-btn` kattintásra:
 *   1. ha a kártya `.yt-transcript-panel`-je [hidden] → fetch + render +
 *      hidden eltávolítása + gomb feliratának frissítése
 *   2. ha már nyitva van → bezárás (hidden visszatétele)
 *
 * Cache: a panel data-fetched="1"-et kap a sikeres betöltés után, így
 * többszöri ki-be klikkelés nem trigger-el újabb fetch-et.
 */
(function () {
  'use strict';

  var API_PREFIX = '/api/echolot';

  function findPanelFor(btn) {
    // A gomb a .yt-card-on belül van; a panel ugyanazon .yt-card-on belüli
    // .yt-transcript-panel a data-for-video attribútummal egyező.
    var card = btn.closest('.yt-card');
    if (!card) return null;
    var videoId = btn.dataset.videoId;
    if (!videoId) return null;
    return card.querySelector('.yt-transcript-panel[data-for-video="' + videoId + '"]');
  }

  function renderTranscript(panel, payload) {
    if (!payload || !payload.segments || payload.segments.length === 0) {
      panel.classList.add('is-error');
      panel.textContent = 'A transcript üres vagy nem érhető el.';
      return;
    }
    panel.classList.remove('is-error', 'is-loading');
    // Time-stamp + text format: "00:12  Szöveg sora"
    var lines = payload.segments.map(function (s) {
      var ts = formatTimestamp(s.start || 0);
      return ts + '  ' + (s.text || '');
    });
    panel.textContent = lines.join('\n');
  }

  function formatTimestamp(seconds) {
    var s = Math.floor(seconds);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    if (h > 0) return h + ':' + pad(m) + ':' + pad(sec);
    return pad(m) + ':' + pad(sec);
  }

  function clearPanelStates(panel) {
    panel.classList.remove('is-loading', 'is-error', 'is-unavailable');
  }

  async function fetchAndRender(panel, videoId) {
    clearPanelStates(panel);
    panel.classList.add('is-loading');
    panel.textContent = 'Leirat betöltése…';
    panel.removeAttribute('hidden');
    try {
      var url = API_PREFIX + '/yt-transcript/' + encodeURIComponent(videoId) + '?lang=hu';
      var r = await fetch(url);
      if (r.status === 404) {
        // Normál eset — sok YT-videónak nincs felirata. Nem hiba, csak info.
        clearPanelStates(panel);
        panel.classList.add('is-unavailable');
        panel.textContent = '— nincs leirat ehhez a videóhoz';
        panel.dataset.fetched = 'unavailable';
        return;
      }
      if (r.status === 503) {
        // Backend timeout — Railway egress lassú vagy YT-blokk
        clearPanelStates(panel);
        panel.classList.add('is-error');
        panel.textContent = '⊘ A leirat-szerver nem válaszolt időben — próbáld újra később.';
        panel.dataset.fetched = 'error';
        return;
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      var payload = await r.json();
      renderTranscript(panel, payload);
      panel.dataset.fetched = '1';
    } catch (e) {
      clearPanelStates(panel);
      panel.classList.add('is-error');
      var msg = (e && e.message) || 'ismeretlen';
      panel.textContent = '⊘ Hiba a betöltéskor: ' + msg;
      panel.dataset.fetched = 'error';
    }
  }

  function onTranscriptBtnClick(e) {
    var btn = e.currentTarget;
    var panel = findPanelFor(btn);
    if (!panel) return;
    var isOpen = !panel.hasAttribute('hidden');

    if (isOpen) {
      // Bezárás
      panel.setAttribute('hidden', '');
      btn.classList.remove('is-expanded');
      btn.textContent = '▽ Leirat';
    } else {
      // Megnyitás — ha még nem fetcheltünk, indítjuk; ha igen, csak láthatóvá
      btn.classList.add('is-expanded');
      btn.textContent = '△ Bezár';
      if (panel.dataset.fetched === '1' || panel.dataset.fetched === 'unavailable' || panel.dataset.fetched === 'error') {
        panel.removeAttribute('hidden');
      } else {
        fetchAndRender(panel, btn.dataset.videoId);
      }
    }
  }

  function init() {
    var btns = document.querySelectorAll('.yt-transcript-btn');
    btns.forEach(function (b) {
      b.addEventListener('click', onTranscriptBtnClick);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
