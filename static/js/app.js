/* DeadCodeX shared front-end helpers (no dependencies). */
(function () {
  'use strict';
  var dcx = window.dcx = {};
  dcx.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  };
  dcx.csrf = function () { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ''; };
  dcx.size = function (n) {
    n = Number(n) || 0; var u = ['B', 'KB', 'MB', 'GB'], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(n < 100 ? 1 : 0)) + ' ' + u[i];
  };
  dcx.api = function (url, opts) {
    opts = opts || {};
    var init = {method: opts.method || 'GET', headers: {'Accept': 'application/json', 'X-CSRFToken': dcx.csrf()}, credentials: 'same-origin'};
    if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    return fetch(url, init).then(function (r) {
      return r.text().then(function (t) {
        var data = {}; try { data = t ? JSON.parse(t) : {}; } catch (e) { data = {error: 'Unexpected server response (HTTP ' + r.status + ')'}; }
        if (!r.ok) { var err = new Error(data.error || ('Request failed (HTTP ' + r.status + ')')); err.status = r.status; err.data = data; throw err; }
        return data;
      });
    });
  };
  dcx.toast = function (msg, kind) {
    var box = document.getElementById('toasts'); if (!box) return;
    var el = document.createElement('div');
    el.className = 'px-4 py-3 rounded-lg text-sm shadow-xl border max-w-sm ' + (kind === 'error' ? 'bg-red-900/80 border-red-500/40 text-red-100' : 'bg-emerald-900/80 border-emerald-500/40 text-emerald-100');
    el.textContent = msg; box.appendChild(el);
    setTimeout(function () { el.remove(); }, 6000);
  };
  dcx.notifyEnabled = function (key) { return !window.DCX_SETTINGS || window.DCX_SETTINGS[key] !== false; };
  var btn = document.getElementById('menu-btn'), sb = document.getElementById('sidebar');
  if (btn && sb) btn.addEventListener('click', function () { sb.classList.toggle('-translate-x-full'); });
  dcx.modal = function (id, show) {
    var m = document.getElementById(id); if (!m) return;
    m.classList.toggle('hidden', !show); m.classList.toggle('flex', show);
    if (show) { var f = m.querySelector('button,[href],input'); if (f) f.focus(); }
  };
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') document.querySelectorAll('[data-modal]:not(.hidden)').forEach(function (m) { dcx.modal(m.id, false); });
  });
})();
