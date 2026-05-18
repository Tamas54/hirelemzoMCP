/**
 * echolot-tv.js — Live TV viewer panel, vanilla JS port of
 * worldmonitor/src/components/LiveNewsPanel.ts (minimal Phase-1 subset).
 *
 * DOM-contract az index.html-ben:
 *   .echolot-tv > .tv-tabs#tv-tabs
 *                .tv-player-wrap > video#tv-video, iframe#tv-iframe,
 *                                  .tv-offline#tv-offline
 *                .tv-meta > span#tv-channel-name, span#tv-source-badge,
 *                           button#tv-mute-btn
 *
 * API endpoint-ok (server.py):
 *   GET /api/echolot/channels           → [{id, name, handle, has_direct_hls}, ...]
 *   GET /api/echolot/live/{channel_id}  → {name, video_id, hls_url, is_live, source}
 */
(function () {
  'use strict';

  // ─── Konfig + DOM ref-ek ────────────────────────────────────────────
  var HLS_CDN = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js';
  var API_PREFIX = '/api/echolot';  // integration-ready: a fő echolot app prefix
  var $tabs = document.getElementById('tv-tabs');
  var $video = /** @type {HTMLVideoElement} */ (document.getElementById('tv-video'));
  var $iframe = /** @type {HTMLIFrameElement} */ (document.getElementById('tv-iframe'));
  var $offline = document.getElementById('tv-offline');
  var $name = document.getElementById('tv-channel-name');
  var $badge = document.getElementById('tv-source-badge');
  var $muteBtn = document.getElementById('tv-mute-btn');

  var state = {
    currentChannelId: null,
    hlsInstance: null,          // Aktív Hls.js példány (memory leak elkerülés)
    isMuted: true,              // Browser autoplay policy: default mute
    hlsReady: false,            // hls.js CDN betöltődött-e
    currentVideoId: null,       // Aktuálisan YT-iframeben futó video-id
  };

  // ─── hls.js async betöltés (CDN-ről) ───────────────────────────────
  function loadHlsJs() {
    return new Promise(function (resolve) {
      if (window.Hls) {
        state.hlsReady = true;
        resolve();
        return;
      }
      var s = document.createElement('script');
      s.src = HLS_CDN;
      s.async = true;
      s.onload = function () {
        state.hlsReady = true;
        console.log('[echolot-tv] hls.js loaded, version', window.Hls && window.Hls.version);
        resolve();
      };
      s.onerror = function () {
        console.warn('[echolot-tv] hls.js CDN load failed — Safari/native fallback only');
        resolve(); // continue without it
      };
      document.head.appendChild(s);
    });
  }

  // ─── Csatorna-tab strip render ──────────────────────────────────────
  function renderTabs(channels) {
    $tabs.innerHTML = '';
    channels.forEach(function (ch) {
      var btn = document.createElement('button');
      btn.className = 'tv-tab';
      btn.type = 'button';
      btn.dataset.channelId = ch.id;
      btn.textContent = ch.name;
      btn.addEventListener('click', function () {
        loadChannel(ch.id);
      });
      $tabs.appendChild(btn);
    });
  }

  function markActiveTab(channelId) {
    var btns = $tabs.querySelectorAll('.tv-tab');
    btns.forEach(function (b) {
      if (b.dataset.channelId === channelId) b.classList.add('is-active');
      else b.classList.remove('is-active');
    });
  }

  // ─── Player swap (HLS / YT iframe / offline) ────────────────────────
  function clearHls() {
    if (state.hlsInstance) {
      try { state.hlsInstance.destroy(); } catch (e) { /* ignore */ }
      state.hlsInstance = null;
    }
    $video.removeAttribute('src');
    try { $video.load(); } catch (e) { /* ignore */ }
  }

  function showElement(el) {
    el.classList.add('is-active');
  }
  function hideElement(el) {
    el.classList.remove('is-active');
  }

  function setOffline(visible) {
    if (!$offline) return;
    if (visible) $offline.removeAttribute('hidden');
    else $offline.setAttribute('hidden', '');
  }

  function attachHls(hlsUrl) {
    clearHls();
    hideElement($iframe);
    setOffline(false);
    showElement($video);

    if (window.Hls && window.Hls.isSupported()) {
      var hls = new window.Hls({ enableWorker: true, lowLatencyMode: false });
      hls.loadSource(hlsUrl);
      hls.attachMedia($video);
      hls.on(window.Hls.Events.ERROR, function (_evt, data) {
        if (data && data.fatal) {
          console.warn('[echolot-tv] HLS fatal error', data);
        }
      });
      state.hlsInstance = hls;
    } else {
      // Safari + iOS támogatja a m3u8-at natívan
      $video.src = hlsUrl;
    }
    $video.muted = state.isMuted;
    $video.play().catch(function (e) {
      console.warn('[echolot-tv] video.play() blocked:', e && e.message);
    });
  }

  function attachIframe(videoId) {
    clearHls();
    hideElement($video);
    setOffline(false);
    state.currentVideoId = videoId;
    var mute = state.isMuted ? 1 : 0;
    $iframe.src =
      'https://www.youtube.com/embed/' + encodeURIComponent(videoId) +
      '?autoplay=1&mute=' + mute + '&playsinline=1&rel=0&modestbranding=1';
    showElement($iframe);
  }

  function attachOffline() {
    clearHls();
    hideElement($video);
    hideElement($iframe);
    setOffline(true);
  }

  function setBadge(source, isLive) {
    if (!$badge) return;
    var label = 'OFFLINE';
    var cls = 'tv-source-badge';
    if (source === 'direct') { label = 'HLS'; cls += ' badge-hls'; }
    else if (source === 'yt_live') { label = 'YT LIVE'; cls += ' badge-yt'; }
    else if (source === 'fallback') { label = 'FALLBACK'; cls += ' badge-fb'; }
    else if (!isLive) { cls += ' badge-off'; }
    $badge.className = cls;
    $badge.textContent = label;
  }

  // ─── Csatorna-betöltő ───────────────────────────────────────────────
  async function loadChannel(channelId) {
    if (!channelId) return;
    state.currentChannelId = channelId;
    markActiveTab(channelId);

    var info;
    try {
      var r = await fetch(API_PREFIX + '/live/' + encodeURIComponent(channelId));
      if (!r.ok) throw new Error('HTTP ' + r.status);
      info = await r.json();
    } catch (e) {
      console.warn('[echolot-tv] live fetch failed:', e && e.message);
      attachOffline();
      if ($name) $name.textContent = channelId;
      setBadge(null, false);
      return;
    }

    if ($name) $name.textContent = info.name || channelId;

    // Forrás-szerinti player-választás:
    //  - source=direct → HLS.js (közvetlen CDN, böngészőből elérhető)
    //  - source=yt_live → IFRAME (a YT-hosztolt HLS signed/IP-binding-elt,
    //    böngészőből CORS-blokk — csak server-side proxy tudja használni)
    //  - source=fallback → IFRAME a statikus fallback video_id-vel
    //  - source=none/unknown → offline
    if (info.source === 'direct' && info.hls_url) {
      try { attachHls(info.hls_url); }
      catch (e) {
        console.warn('[echolot-tv] HLS attach failed:', e);
        if (info.video_id) attachIframe(info.video_id);
        else attachOffline();
      }
    } else if (info.video_id) {
      attachIframe(info.video_id);
    } else {
      attachOffline();
    }
    setBadge(info.source, !!info.is_live);
  }

  // ─── Mute toggle ────────────────────────────────────────────────────
  function setMuted(muted) {
    state.isMuted = !!muted;
    if ($muteBtn) $muteBtn.textContent = state.isMuted ? '🔇' : '🔊';
    // Video element: in-place
    $video.muted = state.isMuted;
    // YT iframe: reload with új mute param (postMessage API-t mellőzzük az MVP-ben)
    if ($iframe.classList.contains('is-active') && state.currentVideoId) {
      var mute = state.isMuted ? 1 : 0;
      $iframe.src =
        'https://www.youtube.com/embed/' + encodeURIComponent(state.currentVideoId) +
        '?autoplay=1&mute=' + mute + '&playsinline=1&rel=0&modestbranding=1';
    }
  }

  // ─── Collapse / kibont állapot ─────────────────────────────────────
  var LS_COLLAPSED_KEY = 'echolot-tv-collapsed';
  var LS_POPOUT_KEY = 'echolot-tv-popout';  // JSON: {top, left, width, height} when popped
  var $panelWrap = null;          // ".tv-panel-wrap" — toggleable parent
  var $collapseBtn = null;
  var $popoutBtn = null;
  var $fullscreenBtn = null;
  var $sectionHeader = null;

  function isCollapsed() {
    return $panelWrap && $panelWrap.classList.contains('is-collapsed');
  }

  function setCollapsed(collapsed) {
    if (!$panelWrap || !$collapseBtn) return;
    if (collapsed) {
      $panelWrap.classList.add('is-collapsed');
      $collapseBtn.textContent = '▷';
      $collapseBtn.setAttribute('aria-label', 'TV panel kibontása');
      // Streamet megállítjuk — bandwidth + CPU spórolás
      try { $video.pause(); } catch (e) { /* ignore */ }
      if ($iframe.src) { $iframe.src = 'about:blank'; }
      try { localStorage.setItem(LS_COLLAPSED_KEY, '1'); } catch (e) { /* ignore */ }
    } else {
      $panelWrap.classList.remove('is-collapsed');
      $collapseBtn.textContent = '▽';
      $collapseBtn.setAttribute('aria-label', 'TV panel lekicsinyítése');
      try { localStorage.removeItem(LS_COLLAPSED_KEY); } catch (e) { /* ignore */ }
      // Aktuális csatorna újratöltése (a stream pause-olt / iframe lecserélődött)
      if (state.currentChannelId) {
        loadChannel(state.currentChannelId);
      }
    }
  }

  function toggleCollapsed() {
    setCollapsed(!isCollapsed());
  }

  // ─── Pop-out / dock-back állapot ───────────────────────────────────
  function isPoppedOut() {
    return $panelWrap && $panelWrap.classList.contains('is-popped-out');
  }

  function savePopoutState() {
    if (!$panelWrap) return;
    try {
      var rect = $panelWrap.getBoundingClientRect();
      localStorage.setItem(LS_POPOUT_KEY, JSON.stringify({
        top: rect.top + 'px',
        left: rect.left + 'px',
        width: rect.width + 'px',
        height: rect.height + 'px',
      }));
    } catch (e) { /* ignore */ }
  }

  function setPoppedOut(out) {
    if (!$panelWrap) return;
    if (out) {
      // Collapse-ot kapcsoljuk ki, hogy lássuk a playert
      if (isCollapsed()) setCollapsed(false);
      $panelWrap.classList.add('is-popped-out');
      // Mentett pozíció + méret visszaállítása localStorage-ból
      try {
        var saved = JSON.parse(localStorage.getItem(LS_POPOUT_KEY) || 'null');
        if (saved) {
          $panelWrap.style.top = saved.top || '';
          $panelWrap.style.left = saved.left || '';
          $panelWrap.style.right = 'auto';
          $panelWrap.style.width = saved.width || '';
          $panelWrap.style.height = saved.height || '';
        } else {
          // Default position: top-right corner with margin
          $panelWrap.style.right = 'auto';
          $panelWrap.style.left = Math.max(40, window.innerWidth - 520) + 'px';
        }
      } catch (e) { /* ignore */ }
      // ResizeObserver: ha a felhasználó a sarokból átméretezi, mentjük
      if (window.ResizeObserver && !$panelWrap._resizeObserver) {
        var ro = new ResizeObserver(function () {
          if (isPoppedOut()) savePopoutState();
        });
        ro.observe($panelWrap);
        $panelWrap._resizeObserver = ro;
      }
      if ($popoutBtn) {
        $popoutBtn.textContent = '↘';
        $popoutBtn.setAttribute('aria-label', 'TV panel visszadokkolása');
        $popoutBtn.title = 'Vissza a jobb oszlopba';
      }
    } else {
      $panelWrap.classList.remove('is-popped-out');
      // Inline-stílusok eltávolítása, hogy a CSS-grid pozíciója visszaálljon
      $panelWrap.style.top = '';
      $panelWrap.style.left = '';
      $panelWrap.style.right = '';
      $panelWrap.style.width = '';
      $panelWrap.style.height = '';
      try { localStorage.removeItem(LS_POPOUT_KEY); } catch (e) { /* ignore */ }
      if ($popoutBtn) {
        $popoutBtn.textContent = '↗';
        $popoutBtn.setAttribute('aria-label', 'TV panel kiemelése floating ablakba');
        $popoutBtn.title = 'Kiemelés (drag-able, resizable)';
      }
    }
  }

  function togglePoppedOut() {
    setPoppedOut(!isPoppedOut());
  }

  // ─── Drag-to-move a section-header-től ─────────────────────────────
  var dragState = null;

  function onHeaderMouseDown(e) {
    if (!isPoppedOut()) return;
    // Ne drag-eljünk ha a gombokat klikkeli a felhasználó
    if (e.target.closest('button')) return;
    var rect = $panelWrap.getBoundingClientRect();
    dragState = {
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
    e.preventDefault();
  }
  function onDragMove(e) {
    if (!dragState) return;
    var nx = e.clientX - dragState.offsetX;
    var ny = e.clientY - dragState.offsetY;
    // A viewportban tartjuk — ne tűnjön el teljesen
    nx = Math.max(-100, Math.min(window.innerWidth - 100, nx));
    ny = Math.max(0, Math.min(window.innerHeight - 40, ny));
    $panelWrap.style.left = nx + 'px';
    $panelWrap.style.top = ny + 'px';
    $panelWrap.style.right = 'auto';
  }
  function onDragEnd() {
    if (!dragState) return;
    dragState = null;
    document.removeEventListener('mousemove', onDragMove);
    document.removeEventListener('mouseup', onDragEnd);
    savePopoutState();
  }

  // ─── Fullscreen (natív Fullscreen API) ─────────────────────────────
  function isFullscreen() {
    var el = document.fullscreenElement || document.webkitFullscreenElement;
    return el === $panelWrap;
  }
  function toggleFullscreen() {
    if (!$panelWrap) {
      console.warn('[echolot-tv] fullscreen: $panelWrap is null');
      return;
    }
    if (isFullscreen()) {
      console.log('[echolot-tv] fullscreen: exiting…');
      var exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (typeof exit === 'function') {
        var p = exit.call(document);
        if (p && p.catch) p.catch(function (e) {
          console.warn('[echolot-tv] exit-fullscreen failed:', e && e.message);
        });
      }
    } else {
      console.log('[echolot-tv] fullscreen: requesting on', $panelWrap);
      var req = $panelWrap.requestFullscreen
        || $panelWrap.webkitRequestFullscreen
        || $panelWrap.mozRequestFullScreen
        || $panelWrap.msRequestFullscreen;
      if (typeof req !== 'function') {
        console.warn('[echolot-tv] fullscreen: no requestFullscreen API on element');
        return;
      }
      try {
        var result = req.call($panelWrap);
        if (result && typeof result.then === 'function') {
          result.then(
            function () { console.log('[echolot-tv] fullscreen entered'); },
            function (e) { console.warn('[echolot-tv] fullscreen request denied:', e && e.message); }
          );
        }
      } catch (e) {
        console.warn('[echolot-tv] fullscreen sync error:', e && e.message);
      }
    }
  }
  function onFullscreenChange() {
    if (!$fullscreenBtn) return;
    var fs = isFullscreen();
    if (fs) {
      $fullscreenBtn.textContent = '⛻ Vissza';
      $fullscreenBtn.setAttribute('aria-label', 'Vissza a normál nézethez');
      $fullscreenBtn.title = 'Vissza a normál nézethez (Esc)';
    } else {
      $fullscreenBtn.textContent = '⛶';
      $fullscreenBtn.setAttribute('aria-label', 'Teljes képernyő');
      $fullscreenBtn.title = 'Teljes képernyő (Esc kilép)';
    }
  }

  // ─── Bootstrap ──────────────────────────────────────────────────────
  async function init() {
    $panelWrap = document.querySelector('.tv-panel-wrap');
    $collapseBtn = document.getElementById('tv-collapse-btn');
    $popoutBtn = document.getElementById('tv-popout-btn');
    $fullscreenBtn = document.getElementById('tv-fullscreen-btn');
    $sectionHeader = $panelWrap ? $panelWrap.querySelector('.ts-section-header') : null;

    // Lekicsinyített állapot visszaállítása localStorage-ból, MIELŐTT a
    // streamet elindítjuk — így auto-play sem zavar collapse-olt módban.
    var savedCollapsed = false;
    try { savedCollapsed = localStorage.getItem(LS_COLLAPSED_KEY) === '1'; } catch (e) { /* ignore */ }
    if (savedCollapsed && $panelWrap) {
      $panelWrap.classList.add('is-collapsed');
      if ($collapseBtn) { $collapseBtn.textContent = '▷'; }
    }

    // Popout-állapot visszaállítása (ha a felhasználó kiemelve hagyta)
    var savedPopout = null;
    try { savedPopout = JSON.parse(localStorage.getItem(LS_POPOUT_KEY) || 'null'); } catch (e) { /* ignore */ }
    if (savedPopout && $panelWrap) {
      setPoppedOut(true);
    }

    if ($collapseBtn) {
      $collapseBtn.addEventListener('click', toggleCollapsed);
    }
    if ($popoutBtn) {
      $popoutBtn.addEventListener('click', togglePoppedOut);
    }
    if ($fullscreenBtn) {
      $fullscreenBtn.addEventListener('click', toggleFullscreen);
    }
    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('webkitfullscreenchange', onFullscreenChange);
    if ($sectionHeader) {
      $sectionHeader.addEventListener('mousedown', onHeaderMouseDown);
    }

    await loadHlsJs();
    try {
      var r = await fetch(API_PREFIX + '/channels');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      var channels = await r.json();
      if (!Array.isArray(channels) || channels.length === 0) {
        console.warn('[echolot-tv] no channels returned');
        return;
      }
      renderTabs(channels);
      // Csak akkor indítsuk auto-play-jel, ha NEM collapsed állapotból nyitott
      if (!savedCollapsed) {
        loadChannel(channels[0].id);
      } else {
        // Collapsed: jelöljük az első tabot aktívnak az újranyitáshoz, de
        // ne töltsünk be streamet.
        state.currentChannelId = channels[0].id;
        markActiveTab(channels[0].id);
      }
    } catch (e) {
      console.error('[echolot-tv] bootstrap failed:', e && e.message);
    }
    if ($muteBtn) {
      $muteBtn.addEventListener('click', function () { setMuted(!state.isMuted); });
      $muteBtn.textContent = state.isMuted ? '🔇' : '🔊';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Debug handle (DevTools-ban: EcholotTV.state, EcholotTV.loadChannel(...))
  window.EcholotTV = {
    state: state,
    loadChannel: loadChannel,
    setMuted: setMuted,
    setCollapsed: setCollapsed,
    toggleCollapsed: toggleCollapsed,
    setPoppedOut: setPoppedOut,
    togglePoppedOut: togglePoppedOut,
    toggleFullscreen: toggleFullscreen,
  };
})();
