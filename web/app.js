/* BOB web app: routing, state, API calls, and views. */
(function () {
  'use strict';

  var P = window.BOBPlot;
  var SVGNS = 'http://www.w3.org/2000/svg';

  var VIEWER_REASON = 'You have view access to this workspace. Ask a workspace owner for editor access to make changes.';
  var OWNER_REASON = 'Only workspace owners can do this.';
  var OUTSIDER_REASON = 'You are not a member of the workspace that owns this study, so it is read only.';
  var COMPONENT_ROLES = ['strain', 'plasmid', 'inducer', 'supplement', 'medium', 'design', 'other'];
  var IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  var LICENSE_NAMES = { 'CC-BY-4.0': 'CC BY 4.0', 'CC0-1.0': 'CC0 1.0' };
  var SAMPLE_TYPES = [
    { value: 'sample', label: 'Sample' },
    { value: 'medium', label: 'Medium (control)' },
    { value: 'untransformed', label: 'Untransformed (control)' }
  ];

  var state = {
    me: null,
    wsId: null,
    health: null,
    mappings: null,
    invCache: new Map(),
    leaveGuard: null,
    foreign: false
  };

  /* ===================================================================
     DOM helpers
     =================================================================== */

  function $(sel, root) { return (root || document).querySelector(sel); }

  function h(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
        else if (k === 'dataset') Object.assign(node.dataset, v);
        else if (k === 'value') node.value = v;
        else if (k === 'checked') node.checked = !!v;
        else if (k === 'selected') node.selected = !!v;
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
        else if (v === true) node.setAttribute(k, '');
        else node.setAttribute(k, v);
      });
    }
    appendKids(node, Array.prototype.slice.call(arguments, 2));
    return node;
  }

  function appendKids(node, kids) {
    kids.forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      if (Array.isArray(c)) appendKids(node, c);
      else node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    });
    return node;
  }

  var uidN = 0;
  function uid(prefix) { uidN += 1; return (prefix || 'id') + '-' + uidN; }

  var ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    pencil: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    upload: '<path d="M12 16V5M7 10l5-5 5 5M5 20h14"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 5H7a2 2 0 0 0-2 2v8"/>',
    star: '<path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/>',
    chevronRight: '<path d="M9 6l6 6-6 6"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    warning: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.2v.3"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.3"/>',
    folder: '<path d="M3 7.5A2 2 0 0 1 5 5.5h4l2 2h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    flask: '<path d="M9 3h6M10 3v6.2L4.6 18.4A1.7 1.7 0 0 0 6.1 21h11.8a1.7 1.7 0 0 0 1.5-2.6L14 9.2V3"/><path d="M7.2 15h9.6"/>',
    plate: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="8" cy="10" r="1.3"/><circle cx="12" cy="10" r="1.3"/><circle cx="16" cy="10" r="1.3"/><circle cx="8" cy="14.5" r="1.3"/><circle cx="12" cy="14.5" r="1.3"/><circle cx="16" cy="14.5" r="1.3"/>',
    users: '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18 13.8c2 .9 3.5 3.2 3.5 6.2"/>',
    key: '<circle cx="8" cy="15" r="4.5"/><path d="M11.3 11.7L20 3M16.5 6.5l3 3M14.5 8.5l2 2"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    link: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    layers: '<path d="M12 3l9 4.5-9 4.5-9-4.5z"/><path d="M3 12l9 4.5 9-4.5M3 16.5L12 21l9-4.5"/>',
    beaker: '<path d="M6 3h12M7 3v15a3 3 0 0 0 3 3h4a3 3 0 0 0 3-3V3"/><path d="M7 11h10"/>',
    lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    chart: '<path d="M4 4v16h16"/><path d="M7 15l4-5 3 3 5-7"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    arrowUp: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    arrowDown: '<path d="M12 5v14M6 13l6 6 6-6"/>',
    person: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>',
    signOut: '<path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/><path d="M9 8l-4 4 4 4"/><path d="M5 12h11"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>'
  };

  function icon(name, cls) {
    var s = document.createElementNS(SVGNS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('class', 'ico' + (cls ? ' ' + cls : ''));
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    s.innerHTML = ICONS[name] || '';
    return s;
  }

  function helpIcon(text) {
    return h('span', { class: 'help', tabindex: '0', role: 'img', 'aria-label': 'Help: ' + text, 'data-help': text });
  }

  function setHelp(el, text) {
    if (!el) return;
    el.setAttribute('data-help', text);
    el.setAttribute('aria-label', 'Help: ' + text);
  }

  function field(label, control, opts) {
    opts = opts || {};
    if (!control.id) control.id = uid('f');
    return h('div', { class: 'form-row' + (opts.cls ? ' ' + opts.cls : '') },
      h('label', { class: 'form-label', for: control.id }, label, opts.help ? helpIcon(opts.help) : null),
      control,
      opts.hint ? h('div', { class: 'hint' }, opts.hint) : null);
  }

  function toggleSwitch(label, checked, opts) {
    opts = opts || {};
    var input = h('input', { type: 'checkbox', role: 'switch', checked: checked });
    var row = h('label', { class: 'toggle-row' },
      h('span', { class: 'toggle' }, input, h('span', { class: 'toggle-track' })),
      h('span', { class: 'toggle-label' }, label, opts.help ? helpIcon(opts.help) : null));
    if (opts.onChange) input.addEventListener('change', function () { opts.onChange(input.checked); });
    return { row: row, input: input };
  }

  function selectEl(options, value, attrs) {
    var s = h('select', attrs || null);
    options.forEach(function (o) {
      var opt = h('option', { value: o.value, disabled: o.disabled }, o.label);
      if (String(o.value) === String(value)) opt.selected = true;
      s.appendChild(opt);
    });
    return s;
  }

  /* A write control that stays visible for readers who lack the role, and
     says why on hover and on click instead of doing nothing. */
  function button(label, opts) {
    opts = opts || {};
    var b = h('button', { type: opts.type || 'button', class: 'btn ' + (opts.cls || ''), title: opts.title || null, 'aria-label': opts.ariaLabel || null },
      opts.icon ? icon(opts.icon) : null, label);
    if (opts.locked) {
      b.setAttribute('aria-disabled', 'true');
      b.setAttribute('data-help', opts.locked);
      b.addEventListener('click', function (e) {
        e.preventDefault();
        toast(opts.locked, 'info');
      });
    } else if (opts.onClick) {
      b.addEventListener('click', opts.onClick);
    }
    return b;
  }

  function iconButton(iconName, label, onClick, opts) {
    opts = opts || {};
    var b = h('button', { type: 'button', class: 'btn btn-icon-only' + (opts.danger ? ' danger' : ''), 'aria-label': label, 'data-help': label }, icon(iconName));
    b.addEventListener('click', function (e) { e.stopPropagation(); onClick(e); });
    return b;
  }

  function setBusy(btn, busy, label) {
    if (!btn) return;
    if (busy) {
      if (btn._orig) return;
      btn._orig = Array.prototype.slice.call(btn.childNodes);
      btn._wasDisabled = btn.disabled;
      btn.textContent = '';
      btn.appendChild(h('span', { class: 'spinner', 'aria-hidden': 'true' }));
      btn.appendChild(document.createTextNode(label || 'Working…'));
      btn.disabled = true;
      btn.classList.add('is-busy');
      btn.setAttribute('aria-busy', 'true');
    } else if (btn._orig) {
      btn.textContent = '';
      btn._orig.forEach(function (n) { btn.appendChild(n); });
      btn._orig = null;
      btn.disabled = !!btn._wasDisabled;
      btn.classList.remove('is-busy');
      btn.removeAttribute('aria-busy');
    }
  }

  function skeleton(n) {
    var box = h('div', { class: 'skeleton', 'aria-hidden': 'true' });
    for (var i = 0; i < (n || 3); i++) box.appendChild(h('div', { class: 'skeleton-row', style: { opacity: String(1 - i * 0.22) } }));
    return h('div', { role: 'status' }, h('span', { class: 'sr-only' }, 'Loading'), box);
  }

  function loadingLine(text) {
    return h('div', { class: 'loading', role: 'status' }, h('span', { class: 'spinner lg', 'aria-hidden': 'true' }), text || 'Loading…');
  }

  function emptyState(iconName, title, text, action) {
    return h('div', { class: 'empty' },
      /^bob(:|$)/.test(iconName)
        ? h('img', { class: 'empty-bob', src: 'bob/' + (iconName.split(':')[1] || 'bob') + '.svg', alt: '', height: 129 })
        : h('div', { class: 'empty-glyph' }, icon(iconName)),
      h('div', { class: 'empty-title' }, title),
      text ? h('div', { class: 'empty-text' }, text) : null,
      action || null);
  }

  function callout(kind, title, body, extra) {
    var ic = kind === 'error' ? 'warning' : kind === 'warn' ? 'warning' : kind === 'ok' ? 'check' : 'info';
    return h('div', { class: 'callout callout-' + kind, role: kind === 'error' ? 'alert' : null },
      icon(ic),
      h('div', { class: 'callout-body' },
        title ? h('div', { class: 'callout-title' }, title) : null,
        body || null,
        extra || null));
  }

  function warningsCallout(title, list) {
    if (!list || !list.length) return null;
    return callout('warn', title, h('ul', null, list.map(function (w) { return h('li', null, String(w)); })));
  }

  function errorCallout(err, retry, title) {
    var msg = err && err.message ? err.message : String(err);
    return callout('error', title || 'Something went wrong', h('div', null, msg),
      retry ? button('Try again', { cls: 'btn-sm', icon: 'refresh', onClick: retry }) : null);
  }

  function badge(text, cls, attrs) {
    return h('span', Object.assign({ class: 'badge ' + (cls || '') }, attrs || {}), text);
  }

  function typeBadge(type) {
    var label = type === 'untransformed' ? 'Untransformed' : type === 'medium' ? 'Medium' : 'Sample';
    return badge(label, 'type-badge t-' + (type || 'sample'));
  }

  function roleLabel(role) {
    return role ? role.charAt(0).toUpperCase() + role.slice(1) : '';
  }

  function roleBadge(role) {
    return badge(roleLabel(role), 'role-badge r-' + role);
  }

  function withHelp(el, text) {
    el.setAttribute('data-help', text);
    el.setAttribute('tabindex', '0');
    return el;
  }

  function crumbs(items) {
    var nav = h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' });
    items.forEach(function (it, i) {
      if (i > 0) nav.appendChild(icon('chevronRight'));
      if (it.href) nav.appendChild(h('a', { href: it.href }, it.label));
      else if (i === items.length - 1) nav.appendChild(h('span', { class: 'here', 'aria-current': 'page' }, it.label));
      else nav.appendChild(h('span', null, it.label));
    });
    return nav;
  }

  function listRow(o) {
    var meta = (o.meta || []).filter(Boolean);
    var actions = (o.actions || []).filter(Boolean);
    var glyph = o.emoji
      ? h('span', { class: 'row-glyph emoji', 'aria-hidden': 'true' }, o.emoji)
      : o.glyph ? h('span', { class: 'row-glyph' }, icon(o.glyph)) : null;
    return h('div', { class: 'row' },
      h(o.href ? 'a' : 'div', { class: 'row-main', href: o.href || null },
        glyph,
        h('span', { class: 'row-text' },
          h('span', { class: 'row-title' }, h('span', null, o.title), o.badges || null),
          o.sub ? h('span', { class: 'row-sub' }, o.sub) : null,
          meta.length ? h('span', { class: 'row-meta' }, meta.map(function (m) { return typeof m === 'string' ? h('span', null, m) : m; })) : null),
        o.href ? icon('chevronRight', 'row-chevron') : null),
      actions.length ? h('div', { class: 'row-actions' }, actions) : null);
  }

  function pageHero(kicker, title, parts, actions) {
    return h('section', { class: 'card' },
      h('div', { class: 'hero-head' },
        h('div', null,
          h('div', { class: 'card-title hero-kicker' }, kicker),
          title ? h('h1', { class: 'page-title' }, title) : null,
          parts || null),
        actions && actions.length ? h('div', { class: 'card-actions' }, actions) : null));
  }

  function cardCount() {
    return h('span', { class: 'card-count' });
  }

  /* ===================================================================
     Formatting
     =================================================================== */

  function parseDate(s) {
    if (!s) return null;
    var str = String(s);
    // Naive timestamps from the server are UTC.
    if (/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(str)) str += 'Z';
    var d = new Date(str);
    return isNaN(d.getTime()) ? null : d;
  }

  function fmtDate(s) {
    var d = parseDate(s);
    return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : (s ? String(s) : '');
  }

  function fmtDateTime(s) {
    var d = parseDate(s);
    return d ? d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }) : (s ? String(s) : '');
  }

  function fmtBytes(n) {
    if (n === null || n === undefined) return '';
    if (n < 1024) return n + ' bytes';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }

  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : (many || one + 's'));
  }

  function shortHash(s) {
    if (!s) return '';
    return s.length > 18 ? s.slice(0, 10) + '…' + s.slice(-6) : s;
  }

  function humanize(s) {
    if (!s) return '';
    var t = String(s).replace(/[_-]+/g, ' ');
    return t.charAt(0).toUpperCase() + t.slice(1);
  }

  function initials(name) {
    var parts = String(name || '?').trim().split(/\s+/);
    var first = function (part) { return Array.from(part)[0] || ''; };
    var s = first(parts[0]) + (parts.length > 1 ? first(parts[parts.length - 1]) : '');
    return s.toUpperCase();
  }

  function slugify(s) {
    return String(s || 'study').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'study';
  }

  /* ===================================================================
     API
     =================================================================== */

  function ApiError(status, message, detail) {
    this.name = 'ApiError';
    this.status = status;
    this.message = message;
    this.detail = detail;
  }
  ApiError.prototype = Object.create(Error.prototype);

  function detailText(data) {
    if (data === null || data === undefined) return '';
    if (typeof data === 'string') return data.trim().slice(0, 600);
    var d = data.detail;
    if (typeof d === 'string') return d;
    if (d && typeof d.message === 'string') return d.message;
    if (Array.isArray(d)) {
      return d.map(function (x) {
        if (!x || typeof x !== 'object') return String(x);
        var loc = Array.isArray(x.loc) ? x.loc.filter(function (p) { return p !== 'body'; }).join('.') : '';
        return (loc ? loc + ': ' : '') + (x.msg ? x.msg.replace(/^Value error, /, '') : JSON.stringify(x));
      }).join('\n');
    }
    if (d) return JSON.stringify(d, null, 2);
    return '';
  }

  function statusMessage(status) {
    if (status === 403) return 'You do not have permission to do that.';
    if (status === 404) return 'Not found. It may have been deleted.';
    if (status === 413) return 'The file is too large for the server.';
    if (status >= 500) return 'The server ran into an error (' + status + '). Try again, and check the server log if it keeps happening.';
    return 'Request failed (' + status + ').';
  }

  var UNREACHABLE = 'Cannot reach the BOB server. Check that it is running and try again.';
  var SESSION_ENDED = 'Your session has ended. Sign in to continue.';

  function sessionEnded() {
    signedOut(SESSION_ENDED);
    return new ApiError(401, SESSION_ENDED);
  }

  function failure(status, data) {
    return new ApiError(status, detailText(data) || statusMessage(status), data && typeof data === 'object' ? data.detail : data);
  }

  async function readBody(res) {
    var ct = res.headers.get('content-type') || '';
    try {
      if (ct.indexOf('json') >= 0) return await res.json();
      return await res.text();
    } catch (e) {
      return null;
    }
  }

  async function api(method, path, body, opts) {
    opts = opts || {};
    var init = { method: method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    var res;
    try {
      res = await fetch(path, init);
    } catch (e) {
      throw new ApiError(0, UNREACHABLE);
    }
    if (res.status === 401 && !opts.authCall) throw sessionEnded();
    if (res.status === 204) return null;
    var data = await readBody(res);
    if (!res.ok) throw failure(res.status, data);
    return data;
  }

  function uploadWithProgress(path, form, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', path);
      xhr.setRequestHeader('Accept', 'application/json');
      xhr.upload.addEventListener('progress', function (e) {
        if (e.lengthComputable) onProgress('upload', e.loaded / e.total);
      });
      xhr.upload.addEventListener('load', function () { onProgress('processing', 1); });
      xhr.addEventListener('error', function () { reject(new ApiError(0, 'The upload failed. Check the connection to the server and try again.')); });
      xhr.addEventListener('abort', function () { reject(new ApiError(0, 'The upload was canceled.')); });
      xhr.addEventListener('load', function () {
        var data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = xhr.responseText; }
        if (xhr.status === 401) reject(sessionEnded());
        else if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(failure(xhr.status, data));
      });
      xhr.send(form);
    });
  }

  async function downloadFile(path, fallbackName) {
    var res;
    try {
      res = await fetch(path, { credentials: 'same-origin' });
    } catch (e) {
      throw new ApiError(0, UNREACHABLE);
    }
    if (res.status === 401) throw sessionEnded();
    if (!res.ok) throw failure(res.status, await readBody(res));
    var blob = await res.blob();
    var cd = res.headers.get('content-disposition') || '';
    var m = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
    var name = fallbackName;
    if (m) {
      try { name = decodeURIComponent(m[1].trim().replace(/^"|"$/g, '')); } catch (e) { name = m[1]; }
    }
    var url = URL.createObjectURL(blob);
    var a = h('a', { href: url, download: name, style: { display: 'none' } });
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 2000);
    return name;
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* fall through to the legacy path */ }
    var ta = h('textarea', { style: { position: 'fixed', top: '-1000px', opacity: '0' } });
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  function copyButton(text, label) {
    var b = h('button', { type: 'button', class: 'copy-btn', 'aria-label': 'Copy ' + (label || 'value') }, icon('copy'), 'Copy');
    b.addEventListener('click', async function () {
      var ok = await copyText(text);
      if (ok) {
        b.textContent = '';
        b.appendChild(icon('check'));
        b.appendChild(document.createTextNode('Copied'));
        setTimeout(function () {
          b.textContent = '';
          b.appendChild(icon('copy'));
          b.appendChild(document.createTextNode('Copy'));
        }, 1600);
      } else {
        toast('Copy failed. Select the text and copy it by hand.', 'error');
      }
    });
    return b;
  }

  /* Downloads `path`; the server's file name wins over `fileName`. */
  function downloadButton(label, path, fileName, help) {
    var btn = button(label, {
      cls: 'btn-sm', icon: 'download',
      onClick: async function () {
        setBusy(btn, true, 'Downloading…');
        try {
          toast('Downloaded ' + await downloadFile(path, fileName));
        } catch (e) {
          if (e.status !== 401) toast('Download failed: ' + e.message, 'error');
        } finally {
          setBusy(btn, false);
        }
      }
    });
    if (help) btn.setAttribute('data-help', help);
    return btn;
  }

  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(localStorage.getItem(key));
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { return null; }
    return value;
  }

  /* ===================================================================
     Toasts, tooltips, modals, menus
     =================================================================== */

  function toast(message, kind) {
    kind = kind || 'ok';
    var box = $('#toasts');
    var t = h('div', { class: 'toast ' + kind, role: kind === 'error' ? 'alert' : 'status' },
      icon(kind === 'error' ? 'warning' : kind === 'info' ? 'info' : 'check'),
      h('span', null, message));
    var close = h('button', { type: 'button', class: 'toast-close', 'aria-label': 'Dismiss' }, icon('x'));
    t.appendChild(close);
    var gone = false;
    function dismiss() {
      if (gone) return;
      gone = true;
      t.classList.add('leaving');
      setTimeout(function () { t.remove(); }, 200);
    }
    close.addEventListener('click', dismiss);
    box.appendChild(t);
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(dismiss, kind === 'error' ? 7000 : 3600);
  }

  var tipEl = null;
  function ensureTip() {
    if (!tipEl) {
      tipEl = h('div', { class: 'help-tip', role: 'tooltip', id: 'help-tip' });
      document.body.appendChild(tipEl);
    }
    return tipEl;
  }

  function showTip(marker) {
    var text = marker.getAttribute('data-help');
    if (!text) return;
    var t = ensureTip();
    t.textContent = text;
    t.classList.add('visible');
    var m = marker.getBoundingClientRect();
    var r = t.getBoundingClientRect();
    var top = m.top - r.height - 9;
    if (top < 10) top = m.bottom + 9;
    var left = m.left + m.width / 2 - r.width / 2;
    left = Math.max(10, Math.min(left, window.innerWidth - r.width - 10));
    t.style.top = Math.round(top) + 'px';
    t.style.left = Math.round(left) + 'px';
  }

  function hideTip() {
    if (tipEl) tipEl.classList.remove('visible');
  }

  function bindTooltips() {
    ensureTip();
    document.addEventListener('mouseover', function (e) {
      var m = e.target.closest ? e.target.closest('[data-help]') : null;
      if (m) showTip(m);
    });
    document.addEventListener('mouseout', function (e) {
      var m = e.target.closest ? e.target.closest('[data-help]') : null;
      if (m && !(e.relatedTarget && m.contains(e.relatedTarget))) hideTip();
    });
    document.addEventListener('focusin', function (e) {
      var m = e.target.closest ? e.target.closest('[data-help]') : null;
      if (m) showTip(m); else hideTip();
    });
    document.addEventListener('focusout', hideTip);
    window.addEventListener('scroll', hideTip, true);
    window.addEventListener('resize', hideTip);
  }

  var openModals = [];

  /* actions: [{label, cls, primary, busyLabel, onClick(ctl) -> false keeps it open}] */
  function openModal(opts) {
    var prevFocus = document.activeElement;
    var titleId = uid('modal-title');
    var errorBox = h('div', { class: 'field-error', role: 'alert', hidden: true });
    var errorPre = h('pre', { class: 'error-view', hidden: true });
    var footer = h('div', { class: 'modal-actions' });
    var box = h('div', { class: 'modal' + (opts.wide ? ' wide' : ''), role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId },
      h('div', { class: 'modal-title', id: titleId }, opts.icon ? icon(opts.icon) : null, opts.title),
      opts.body, errorBox, errorPre, footer);
    var overlay = h('div', { class: 'modal-overlay' }, box);
    var busy = false, closed = false, resolveDone;
    var done = new Promise(function (r) { resolveDone = r; });
    var primaryBtn = null;

    var ctl = {
      box: box,
      done: done,
      close: close,
      setError: function (msg, verbatim) {
        errorBox.hidden = true;
        errorPre.hidden = true;
        if (!msg) return;
        if (verbatim) { errorPre.textContent = msg; errorPre.hidden = false; }
        else { errorBox.textContent = msg; errorBox.hidden = false; }
      },
      primary: function () { return primaryBtn; }
    };

    (opts.actions || [{ label: 'Close', cls: 'btn-quiet' }]).forEach(function (a) {
      var b = h('button', { type: 'button', class: 'btn ' + (a.cls || '') }, a.icon ? icon(a.icon) : null, a.label);
      if (a.primary) primaryBtn = b;
      b.addEventListener('click', async function () {
        if (busy) return;
        if (!a.onClick) { close(a.value === undefined ? null : a.value); return; }
        ctl.setError(null);
        busy = true;
        setBusy(b, true, a.busyLabel || 'Working…');
        var result;
        try {
          result = await a.onClick(ctl);
        } catch (e) {
          busy = false;
          setBusy(b, false);
          if (e && e.status === 401) { close(null); return; }
          ctl.setError(e && e.message ? e.message : String(e), a.verbatimErrors);
          return;
        }
        busy = false;
        setBusy(b, false);
        if (result !== false) close(result === undefined ? true : result);
      });
      footer.appendChild(b);
    });

    function onKey(e) {
      if (openModals[openModals.length - 1] !== ctl) return;
      if (e.key === 'Escape' && !busy) {
        e.preventDefault();
        close(null);
      } else if (e.key === 'Enter' && primaryBtn && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox' && !e.isComposing) {
        e.preventDefault();
        primaryBtn.click();
      } else if (e.key === 'Tab') {
        var f = Array.prototype.filter.call(box.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'), function (n) {
          return !n.disabled && n.offsetParent !== null;
        });
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }

    function close(value) {
      if (closed) return;
      closed = true;
      document.removeEventListener('keydown', onKey, true);
      openModals.splice(openModals.indexOf(ctl), 1);
      hideTip();
      overlay.classList.add('closing');
      var finish = function () {
        overlay.remove();
        if (prevFocus && prevFocus.focus && document.contains(prevFocus)) prevFocus.focus();
      };
      overlay.addEventListener('animationend', finish, { once: true });
      setTimeout(finish, 260);
      if (opts.onClose) opts.onClose(value);
      resolveDone(value);
    }

    overlay.addEventListener('mousedown', function (e) {
      if (e.target === overlay && !busy && opts.dismissable !== false) close(null);
    });
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(overlay);
    openModals.push(ctl);
    var focusTarget = box.querySelector('[autofocus], input:not([type="hidden"]):not([readonly]), textarea, select') || primaryBtn || footer.querySelector('button');
    if (focusTarget) setTimeout(function () { focusTarget.focus(); }, 30);
    return ctl;
  }

  function confirmDialog(opts) {
    var body = h('div', null,
      h('p', { class: 'modal-text' }, opts.message),
      opts.extra || null);
    var ctl = openModal({
      title: opts.title,
      icon: opts.danger === false ? null : 'warning',
      body: body,
      actions: [
        { label: 'Cancel', cls: 'btn-quiet', value: false },
        {
          label: opts.confirmLabel || 'Delete',
          cls: opts.danger === false ? 'btn-accent' : 'btn-danger-solid',
          primary: true,
          busyLabel: opts.busyLabel || 'Deleting…',
          onClick: async function (m) {
            if (opts.action) await opts.action(m);
            return true;
          }
        }
      ]
    });
    return ctl.done.then(function (v) { return v === true; });
  }

  var menus = [];

  /* A popover menu under `btn`; `fill(menu)` builds its items each time it opens. */
  function bindMenu(btn, menu, fill) {
    menus.push({ btn: btn, menu: menu });
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var opening = menu.hidden;
      closeMenus();
      if (!opening) return;
      menu.textContent = '';
      fill(menu);
      menu.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
      var first = menu.querySelector('.menu-item');
      if (first) setTimeout(function () { first.focus(); }, 20);
    });
    menu.addEventListener('keydown', function (e) {
      var items = Array.prototype.slice.call(menu.querySelectorAll('.menu-item'));
      var i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      else if (e.key === 'Escape') { closeMenus(); btn.focus(); }
    });
    menu.addEventListener('click', function (e) { if (e.target.closest('.menu-item')) closeMenus(); });
  }

  function closeMenus() {
    menus.forEach(function (m) {
      if (m.menu.hidden) return;
      m.menu.hidden = true;
      m.btn.setAttribute('aria-expanded', 'false');
    });
  }

  function menuHead(title, sub) {
    return h('div', { class: 'menu-head' }, h('div', { class: 'menu-name' }, title), sub ? h('div', { class: 'menu-email' }, sub) : null);
  }

  function menuItem(label, opts) {
    var el = opts.href
      ? h('a', { class: 'menu-item', role: 'menuitem', href: opts.href })
      : h('button', { type: 'button', class: 'menu-item', role: 'menuitem' });
    if (opts.checked !== undefined) {
      el.setAttribute('role', 'menuitemradio');
      el.setAttribute('aria-checked', opts.checked ? 'true' : 'false');
    }
    appendKids(el, [icon(opts.icon), h('span', { class: 'menu-label' }, label), opts.extra || null]);
    if (opts.onClick) el.addEventListener('click', opts.onClick);
    return el;
  }

  function menuSep() {
    return h('div', { class: 'menu-sep', role: 'separator' });
  }

  /* ===================================================================
     Workspaces and roles
     =================================================================== */

  function workspaces() {
    return (state.me && state.me.workspaces) || [];
  }

  function wsById(id) {
    return workspaces().find(function (w) { return String(w.id) === String(id); }) || null;
  }

  function currentWs() {
    return wsById(state.wsId);
  }

  function roleIn(wsId) {
    var w = wsById(wsId);
    return w ? w.role : null;
  }

  function writeLock(wsId) {
    var r = roleIn(wsId);
    if (r === 'owner' || r === 'editor') return null;
    return r === 'viewer' ? VIEWER_REASON : OUTSIDER_REASON;
  }

  /* After the workspace changes, a page about one item belongs to the old one, so it goes home. */
  function showWorkspace(home) {
    var r = parseRoute();
    if (home || !r || r.item) {
      if (location.hash !== '#/home') { location.hash = '#/home'; return; }
    }
    route(true);
  }

  async function switchWorkspace(w) {
    if (String(w.id) === String(state.wsId) && !state.foreign) return;
    if (!(await confirmLeave())) return;
    setWorkspace(w.id, true);
    showWorkspace();
    toast('Switched to ' + w.name, 'info');
  }

  function setWorkspace(id, silent) {
    state.wsId = id;
    store('bob.workspace', id);
    renderHeader();
    if (!silent) route(true);
  }

  async function refreshMe() {
    var me = await api('GET', '/api/auth/me');
    state.me = me;
    if (!wsById(state.wsId)) {
      var saved = store('bob.workspace');
      state.wsId = wsById(saved) ? saved : (workspaces()[0] ? workspaces()[0].id : null);
    }
    renderHeader();
    return me;
  }

  /* ===================================================================
     Chrome: auth screen, header, tabs
     =================================================================== */

  function moveIndicator(bar, animate) {
    if (!bar) return;
    var ind = bar.querySelector('.tab-indicator');
    var active = bar.querySelector('.tab.active');
    if (!ind) return;
    if (!animate) ind.classList.add('no-anim');
    if (active) {
      ind.style.opacity = '1';
      ind.style.width = active.offsetWidth + 'px';
      ind.style.transform = 'translateX(' + active.offsetLeft + 'px)';
    } else {
      ind.style.opacity = '0';
    }
    if (!animate) {
      void ind.offsetWidth;
      ind.classList.remove('no-anim');
    }
  }

  function show(el, on) { el.hidden = !on; }

  var LANDING_FEATURES = [
    ['file', 'Your instrument\u2019s own files', 'Gen5 Excel and text exports go in as they are. BOB keeps each raw file with its SHA-256 checksum and reads it with a mapping you can open and edit.'],
    ['beaker', 'Samples linked to their designs', 'Each sample points at its design on SynBioHub, with the medium, strain, plasmids, and supplement amounts read from that design.'],
    ['layers', 'Citable, versioned studies', 'Publish a study with a license and its authors. Every later change makes a new version, and a cited version never changes.'],
    ['download', 'Standard exports', 'Download any study as SBOL 2.3, ISA-JSON, or an RO-Crate that holds its raw files.']
  ];
  var LANDING_STEPS = [
    ['Create an account', 'You get a personal workspace, and you can invite colleagues into a shared one.'],
    ['Bring in your data', 'Import a plate-reader export, or an Excel-to-SBOL assay workbook with its plates. SynBioSuite can send them for you.'],
    ['Analyze and publish', 'Correct for background, normalize by OD, and compare samples; publish the study when it is ready.']
  ];
  var LANDING_TOOLS = ['SBOL 2.3', 'ISA-JSON', 'RO-Crate', 'SynBioHub', 'SynBioSuite'];

  function landingSection(title, body) {
    return h('section', { class: 'landing-section' }, h('h2', { class: 'landing-h2' }, title), body);
  }

  function renderLanding() {
    var openAs = function (mode) { return function () { openAuth(mode); }; };
    $('#landing').appendChild(h('div', null,
      h('section', { class: 'landing-hero' },
        h('div', { class: 'landing-pitch' },
          h('div', { class: 'landing-kicker' }, 'Biological Omnimodal Bank'),
          h('h1', { class: 'landing-h1' }, 'Your lab\u2019s measurements, kept with the designs behind them'),
          h('p', { class: 'landing-lead' }, 'BOB stores instrument data exactly as it left the machine, turns it into curves you can correct and compare, and links every sample to its SBOL design.'),
          h('div', { class: 'landing-cta' },
            button('Create account', { cls: 'btn-accent btn-lg', onClick: openAs('signup') }),
            button('Sign in', { cls: 'btn-quiet btn-lg', onClick: openAs('signin') }))),
        h('figure', { class: 'landing-bob' },
          h('img', { src: 'bob/plot.svg', alt: 'Bob the platypus pointing at a chart', width: '300', height: '210' }),
          h('figcaption', null, 'Why a platypus? It is built from parts of several kinds of animal, and BOB is built to hold data from several kinds of instrument.'))),
      landingSection('What BOB does', h('div', { class: 'landing-grid' }, LANDING_FEATURES.map(function (f) {
        return h('article', { class: 'card landing-card' }, h('div', { class: 'landing-icon' }, icon(f[0])), h('h3', null, f[1]), h('p', null, f[2]));
      }))),
      landingSection('How to start', h('ol', { class: 'landing-steps' }, LANDING_STEPS.map(function (s, i) {
        return h('li', null, h('span', { class: 'landing-step-n', 'aria-hidden': 'true' }, String(i + 1)), h('div', null, h('h3', null, s[0]), h('p', null, s[1])));
      }))),
      landingSection('Works with', h('ul', { class: 'landing-tools' }, LANDING_TOOLS.map(function (n) { return h('li', null, n); }))),
      h('footer', { class: 'landing-foot' }, h('a', { href: '/docs' }, 'API documentation'), h('span', { id: 'landing-version' }))));
  }

  var authPanel = null;
  var authDialog = null;

  /* The sign-in panel lives in index.html and moves into a dialog when one opens. */
  function openAuth(mode, note, isError) {
    if (!authDialog) {
      authDialog = openModal({ title: 'Welcome to BOB', body: authPanel, actions: [], onClose: function () { authDialog = null; } });
    }
    var foot = $('#auth-foot', authPanel);
    formError(foot, note || null);
    foot.classList.toggle('error', !!isError);
    setAuthMode(mode || 'signin', false);
  }

  function showAuth(note, isError) {
    state.me = null;
    show($('#boot'), false);
    show($('#app'), false);
    show($('#auth-screen'), true);
    closeMenus();
    openModals.slice().forEach(function (m) { m.close(null); });
    $('#landing-version').textContent = serverLine();
    if (isError || deepLink()) openAuth('signin', note, isError);
    else if (note) toast(note);
  }

  // Someone following a link to a study came to sign in, not to read about BOB.
  function deepLink() {
    return !/^(#\/?(home)?)?$/.test(location.hash);
  }

  function serverLine() {
    if (!state.health) return '';
    return 'BOB ' + (state.health.version || '') + (state.health.mode === 'api' ? ', API only' : '');
  }

  function signedOut(note) {
    if (!state.me) return;
    state.leaveGuard = null;
    showAuth(note);
  }

  function setAuthMode(mode, animate) {
    var signup = mode === 'signup';
    Array.prototype.forEach.call(authPanel.querySelectorAll('#auth-tabs .tab'), function (t) {
      var on = t.dataset.auth === mode;
      t.classList.toggle('active', on);
      t.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    $('#form-signin', authPanel).hidden = signup;
    $('#form-signup', authPanel).hidden = !signup;
    $('#si-error', authPanel).hidden = true;
    $('#su-error', authPanel).hidden = true;
    requestAnimationFrame(function () { moveIndicator($('#auth-tabs', authPanel), animate !== false); });
    var email = signup ? $('#su-email', authPanel) : $('#si-email', authPanel);
    setTimeout(function () { email.focus(); }, 40);
  }

  function formError(el, msg) {
    el.textContent = msg || '';
    el.hidden = !msg;
  }

  function validEmail(s) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
  }

  function bindAuth() {
    authPanel = $('#auth-panel');
    renderLanding();
    Array.prototype.forEach.call(document.querySelectorAll('[data-open-auth]'), function (b) {
      b.addEventListener('click', function () { openAuth(b.dataset.openAuth); });
    });
    Array.prototype.forEach.call(authPanel.querySelectorAll('#auth-tabs .tab'), function (t) {
      t.addEventListener('click', function () { setAuthMode(t.dataset.auth); });
    });

    $('#form-signin', authPanel).addEventListener('submit', async function (e) {
      e.preventDefault();
      var err = $('#si-error', authPanel);
      var email = $('#si-email', authPanel).value.trim();
      var password = $('#si-password', authPanel).value;
      if (!validEmail(email)) return formError(err, 'Enter the email address you signed up with.');
      if (!password) return formError(err, 'Enter your password.');
      formError(err, null);
      var btn = e.target.querySelector('button[type="submit"]');
      setBusy(btn, true, 'Signing in…');
      try {
        await api('POST', '/api/auth/login', { email: email, password: password }, { authCall: true });
        $('#si-password', authPanel).value = '';
        await enterApp();
      } catch (ex) {
        formError(err, ex.status === 401 ? 'That email and password do not match an account.' : ex.message);
      } finally {
        setBusy(btn, false);
      }
    });

    $('#form-signup', authPanel).addEventListener('submit', async function (e) {
      e.preventDefault();
      var err = $('#su-error', authPanel);
      var email = $('#su-email', authPanel).value.trim();
      var name = $('#su-name', authPanel).value.trim();
      var password = $('#su-password', authPanel).value;
      if (!validEmail(email)) return formError(err, 'Enter a valid email address.');
      if (!name) return formError(err, 'Enter your name as colleagues should see it.');
      if (password.length < 8) return formError(err, 'Use a password of at least 8 characters.');
      formError(err, null);
      var btn = e.target.querySelector('button[type="submit"]');
      setBusy(btn, true, 'Creating account…');
      try {
        await api('POST', '/api/auth/signup', { email: email, name: name, password: password }, { authCall: true });
        $('#su-password', authPanel).value = '';
        await enterApp();
        toast('Welcome to BOB, ' + name + '. Your personal workspace is ready.');
      } catch (ex) {
        formError(err, ex.message);
      } finally {
        setBusy(btn, false);
      }
    });
  }

  var FOREIGN_HELP = 'This study belongs to a workspace you are not in. Its owners made it public, so you can read and download it but not change it.';
  var VIEWER_HELP = 'You can read everything in this workspace but not change it. Ask an owner for editor access.';

  function renderHeader() {
    if (!state.me) return;
    var user = state.me.user || {};
    var w = currentWs();
    $('#avatar').textContent = initials(user.name || user.email);
    $('#account-name').textContent = user.name || user.email || '';
    $('#ws-name').textContent = w ? w.name : 'No workspace';
    var slot = $('#role-slot');
    slot.textContent = '';
    if (state.foreign) slot.appendChild(withHelp(badge('Public study', 'role-badge r-viewer'), FOREIGN_HELP));
    else if (w) slot.appendChild(w.role === 'viewer' ? withHelp(roleBadge(w.role), VIEWER_HELP) : roleBadge(w.role));
    $('#app-foot').textContent = serverLine();
  }

  function fillWorkspaceMenu(menu) {
    var list = workspaces();
    menu.appendChild(menuHead('Workspaces', list.length ? null : 'You are not in a workspace yet.'));
    list.forEach(function (w) {
      var here = String(w.id) === String(state.wsId) && !state.foreign;
      menu.appendChild(menuItem(w.name, { icon: here ? 'check' : null, checked: here, extra: roleBadge(w.role), onClick: function () { switchWorkspace(w); } }));
    });
    if (state.me.invitations) menu.appendChild(menuItem(plural(state.me.invitations, 'invitation') + ' waiting', { icon: 'users', href: '#/home' }));
    menu.appendChild(menuSep());
    if (currentWs()) menu.appendChild(menuItem('Workspace settings', { icon: 'gear', href: '#/workspace' }));
    menu.appendChild(menuItem('New workspace…', { icon: 'plus', onClick: newWorkspaceModal }));
  }

  function fillAccountMenu(menu) {
    var user = state.me.user || {};
    menu.appendChild(menuHead(user.name || '', user.email || ''));
    menu.appendChild(menuItem('Account settings', { icon: 'person', href: '#/account' }));
    menu.appendChild(menuItem('Sign out', { icon: 'signOut', onClick: signOut }));
  }

  function endSession(note) {
    state.invCache.clear();
    state.mappings = null;
    showAuth(note);
  }

  async function signOut() {
    if (!(await confirmLeave())) return;
    try {
      await api('POST', '/api/auth/logout', undefined, { authCall: true });
    } catch (e) { /* signing out locally is still correct */ }
    endSession('You are signed out.');
  }

  function bindHeader() {
    bindMenu($('#ws-btn'), $('#ws-menu'), fillWorkspaceMenu);
    bindMenu($('#account-btn'), $('#account-menu'), fillAccountMenu);
    document.addEventListener('click', function (e) {
      if (!menus.some(function (m) { return m.menu.contains(e.target); })) closeMenus();
    });

    window.addEventListener('resize', function () {
      moveIndicator($('#tab-bar'), false);
      if (authDialog) moveIndicator($('#auth-tabs', authPanel), false);
    });
  }

  function newWorkspaceModal() {
    var name = h('input', { type: 'text', placeholder: 'e.g. Synthetic Biology Lab', maxlength: '120' });
    openModal({
      title: 'New workspace',
      icon: 'users',
      body: h('div', null,
        h('p', { class: 'modal-text' }, 'A workspace holds investigations, members, and mappings. You will be its owner.'),
        field('Name', name)),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: 'Create workspace', cls: 'btn-accent', primary: true, busyLabel: 'Creating…',
          onClick: async function (m) {
            var n = name.value.trim();
            if (!n) { m.setError('Give the workspace a name.'); name.focus(); return false; }
            var ws = await api('POST', '/api/workspaces', { name: n });
            await refreshMe();
            setWorkspace(ws.id, true);
            toast('Workspace ' + ws.name + ' created');
            showWorkspace(true);
          }
        }
      ]
    });
  }

  async function enterApp() {
    await refreshMe();
    if (authDialog) authDialog.close(null);
    show($('#boot'), false);
    show($('#auth-screen'), false);
    show($('#app'), true);
    renderHeader();
    if (!location.hash || location.hash === '#' || location.hash === '#/') history.replaceState(null, '', '#/home');
    route(true);
    requestAnimationFrame(function () { moveIndicator($('#tab-bar'), false); });
  }

  /* ===================================================================
     Router
     =================================================================== */

  /* `item` marks pages about one thing in one workspace. */
  var ROUTES = [
    { name: 'home', re: /^\/home\/?$/, tab: 'home', view: viewHome },
    { name: 'projects', re: /^\/projects\/?$/, tab: 'projects', view: viewProjects },
    { name: 'investigation', re: /^\/projects\/([^/]+)$/, tab: 'projects', item: true, view: viewInvestigation },
    { name: 'study', re: /^\/study\/([^/]+)(?:\/v\/(\d+))?$/, tab: 'projects', item: true, view: viewStudy },
    { name: 'assay', re: /^\/assay\/([^/]+)(?:\/v\/(\d+))?$/, tab: 'projects', item: true, view: viewAssay },
    { name: 'mappings', re: /^\/mappings\/?$/, tab: 'mappings', view: viewMappings },
    { name: 'workspace', re: /^\/workspace\/?$/, tab: null, view: viewWorkspace },
    { name: 'account', re: /^\/account\/?$/, tab: null, view: viewAccount }
  ];

  function parseRoute() {
    var raw = (location.hash || '').replace(/^#/, '');
    var path;
    try { path = decodeURIComponent(raw); } catch (e) { return null; }
    if (!path || path === '/') path = '/home';
    for (var i = 0; i < ROUTES.length; i++) {
      var m = ROUTES[i].re.exec(path);
      if (m) return { name: ROUTES[i].name, tab: ROUTES[i].tab, item: !!ROUTES[i].item, view: ROUTES[i].view, params: m.slice(1), path: path };
    }
    return null;
  }

  var renderSeq = 0;
  var cleanups = [];
  var lastPath = null;
  var currentHash = location.hash;
  var ignoreHash = false;

  async function route(force) {
    if (!state.me) return;
    var r = parseRoute() || { name: 'notfound', tab: null, view: viewNotFound, params: [], path: location.hash };
    currentHash = location.hash;
    if (state.foreign && r.name !== 'study' && r.name !== 'assay') { state.foreign = false; renderHeader(); }
    closeMenus();
    hideTip();
    cleanups.forEach(function (f) { try { f(); } catch (e) { /* a failed cleanup must not block the next view */ } });
    cleanups = [];
    state.leaveGuard = null;
    var seq = ++renderSeq;
    var ctx = {
      alive: function () { return seq === renderSeq; },
      onCleanup: function (f) { cleanups.push(f); }
    };

    Array.prototype.forEach.call(document.querySelectorAll('#tab-bar .tab'), function (t) {
      var on = t.dataset.tab === r.tab;
      t.classList.toggle('active', on);
      if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
    });
    moveIndicator($('#tab-bar'), true);

    var view = $('#view');
    var samePath = lastPath === r.path;
    lastPath = r.path;
    view.textContent = '';
    if (!samePath || force) {
      view.classList.remove('view-enter');
      void view.offsetWidth;
      view.classList.add('view-enter');
    }
    if (!samePath) window.scrollTo(0, 0);
    try {
      await r.view.apply(null, [view, ctx].concat(r.params));
    } catch (e) {
      if (!ctx.alive() || (e && e.status === 401)) return;
      view.textContent = '';
      view.appendChild(h('section', { class: 'card' }, errorCallout(e, function () { route(true); })));
    }
  }

  async function confirmLeave() {
    if (!(state.leaveGuard && state.leaveGuard())) return true;
    var ok = await confirmDialog({
      title: 'Discard layout changes?',
      message: 'The plate layout has changes that are not saved. Leaving now discards them.',
      confirmLabel: 'Discard changes',
      busyLabel: 'Leaving…'
    });
    if (ok) state.leaveGuard = null;
    return ok;
  }

  function bindRouter() {
    window.addEventListener('hashchange', async function () {
      if (ignoreHash) { ignoreHash = false; return; }
      if (!state.me) {
        if (!$('#auth-screen').hidden && deepLink()) openAuth('signin');
        return;
      }
      if (state.leaveGuard && state.leaveGuard()) {
        var target = location.hash;
        ignoreHash = true;
        location.hash = currentHash;
        if (await confirmLeave()) location.hash = target;
        return;
      }
      route();
    });
    window.addEventListener('beforeunload', function (e) {
      if (state.leaveGuard && state.leaveGuard()) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  /* ===================================================================
     Shared loaders
     =================================================================== */

  async function listInvestigations(wsId) {
    var list = await api('GET', '/api/workspaces/' + wsId + '/investigations');
    list.forEach(function (inv) { state.invCache.set(String(inv.id), inv); });
    return list;
  }

  async function findInvestigation(id, wsHint) {
    var key = String(id);
    if (state.invCache.has(key)) return state.invCache.get(key);
    try {
      var inv = await api('GET', '/api/investigations/' + encodeURIComponent(id));
      if (inv && inv.id !== undefined) {
        state.invCache.set(key, inv);
        return inv;
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403 || e.status === 404) {
        if (e.status === 401) throw e;
        return null;
      }
      /* Older servers lack the single-item route; fall back to the lists. */
    }
    var order = [];
    if (wsHint !== undefined && wsHint !== null) order.push(wsHint);
    if (state.wsId !== null && state.wsId !== undefined) order.push(state.wsId);
    workspaces().forEach(function (w) { order.push(w.id); });
    var seen = new Set();
    for (var i = 0; i < order.length; i++) {
      var w = String(order[i]);
      if (seen.has(w)) continue;
      seen.add(w);
      try {
        await listInvestigations(w);
      } catch (e) {
        if (e.status === 401) throw e;
      }
      if (state.invCache.has(key)) return state.invCache.get(key);
    }
    return null;
  }

  async function loadMappings(force) {
    if (!state.mappings || force) state.mappings = await api('GET', '/api/mappings');
    return state.mappings;
  }

  /* Opening a study or assay from another workspace makes that workspace
     current, so the switcher and role badge describe what is on screen. */
  function adoptWorkspace(wsId) {
    if (wsId === null || wsId === undefined) return;
    if (String(wsId) !== String(state.wsId) && wsById(wsId)) setWorkspace(wsById(wsId).id, true);
    var foreign = !wsById(wsId);
    if (foreign !== state.foreign) { state.foreign = foreign; renderHeader(); }
  }

  /* The trail above a study or assay. A public study from another workspace
     has no investigation the reader can open, so it gets no link there. */
  function studyTrail(study, ws, inv) {
    if (!ws) return [{ label: 'Public study' }];
    return [
      { label: ws.name, href: '#/projects' },
      { label: inv ? inv.title : 'Investigation', href: '#/projects/' + study.investigation_id }
    ];
  }

  /* The trail above a study or assay, drawn again once the investigation's title is known. */
  function studyCrumbs(ctx, study, tail) {
    var box = h('div');
    var ws = wsById(study.workspace_id);
    function draw(inv) {
      box.textContent = '';
      box.appendChild(crumbs(studyTrail(study, ws, inv).concat(tail.filter(Boolean))));
    }
    draw(state.invCache.get(String(study.investigation_id)));
    if (ws) findInvestigation(study.investigation_id, study.workspace_id).then(function (inv) { if (ctx.alive() && inv) draw(inv); }).catch(function () { });
    return box;
  }

  function versionNotice(study, version, text, citable) {
    var old = version !== study.latest_version;
    return callout(old ? 'warn' : 'info', old ? 'An earlier version' : 'The latest version',
      h('div', null, text,
        citable ? h('div', { class: 'token-row', style: { marginTop: '8px' } },
          h('input', { type: 'text', readonly: true, value: citableLink(study.id, version), 'aria-label': 'Link to this version' }),
          copyButton(citableLink(study.id, version), 'link')) : null),
      old ? h('a', { class: 'btn btn-sm', href: '#/study/' + study.id, style: { marginTop: '8px' } }, 'Go to the latest version', icon('chevronRight')) : null);
  }

  /* Invitations addressed to the signed-in email. Shown only when /me reports some. */
  function invitationsCard(ctx) {
    if (!state.me || !state.me.invitations) return null;
    var list = h('div', { class: 'list' }, skeleton(1));
    var card = h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Invitations', helpIcon('A workspace owner invited this email address. Accepting adds the workspace to your switcher with the role shown.')),
      list);

    async function answer(inv, accept) {
      try {
        var ws = await api('POST', '/api/invitations/' + inv.id + (accept ? '/accept' : '/decline'));
        await refreshMe();
        if (accept) {
          toast('You joined ' + inv.workspace_name);
          setWorkspace(ws.id, true);
          showWorkspace();
        } else {
          toast('Invitation to ' + inv.workspace_name + ' declined', 'info');
          load();
        }
      } catch (e) {
        if (e.status !== 401) toast('That did not work: ' + e.message, 'error');
      }
    }

    async function load() {
      var invs;
      try {
        invs = await api('GET', '/api/invitations');
      } catch (e) {
        if (!ctx.alive()) return;
        list.textContent = '';
        list.appendChild(errorCallout(e, load));
        return;
      }
      if (!ctx.alive()) return;
      state.me.invitations = invs.length;
      if (!invs.length) { card.remove(); return; }
      list.textContent = '';
      invs.forEach(function (inv) {
        list.appendChild(listRow({
          glyph: 'users', title: inv.workspace_name, badges: roleBadge(inv.role),
          meta: [(inv.invited_by ? 'From ' + inv.invited_by + ', ' : '') + fmtDate(inv.created_at)],
          actions: [
            button('Decline', { cls: 'btn-sm btn-quiet', onClick: function () { answer(inv, false); } }),
            button('Accept', { cls: 'btn-sm btn-accent', icon: 'check', onClick: function () { answer(inv, true); } })]
        }));
      });
    }
    load();
    return card;
  }

  /* ===================================================================
     SynBioHub: sign-in, design search, sending studies
     =================================================================== */

  async function synbiohubStatus() {
    return (await api('GET', '/api/synbiohub')).instances || [];
  }

  function hostOf(url) {
    try { return new URL(url).host; } catch (e) { return url; }
  }

  /* Calls onPick({iri, label, sbol_class, sbol_version}) with the design chosen. */
  function designSearchModal(onPick) {
    var instSel = h('select', { 'aria-label': 'SynBioHub' });
    var note = h('div', { class: 'hint' });
    var q = h('input', { type: 'search', placeholder: 'Name, ID, or description, e.g. pTet', maxlength: '200' });
    var go = button('Search', { cls: 'btn-accent', icon: 'search' });
    var results = h('div', { class: 'list', style: { marginTop: '12px' } });
    var instances = [];

    function sync() {
      var inst = instances.find(function (i) { return i.instance === instSel.value; });
      note.textContent = inst && inst.signed_in ? 'Signed in as ' + inst.username + '. Private designs you can see are included.' : 'Not signed in to this SynBioHub. synbiohub.org needs a sign-in even for public designs; sign in under Account settings.';
    }
    instSel.addEventListener('change', sync);

    async function run() {
      var text = q.value.trim();
      if (!text) { q.focus(); return; }
      results.textContent = '';
      results.appendChild(loadingLine('Searching ' + hostOf(instSel.value) + '…'));
      setBusy(go, true, 'Searching…');
      try {
        var found = /^https?:\/\//i.test(text)
          ? [await api('GET', '/api/synbiohub/resolve?iri=' + encodeURIComponent(text))]
          : await api('GET', '/api/synbiohub/search?instance=' + encodeURIComponent(instSel.value) + '&q=' + encodeURIComponent(text));
        results.textContent = '';
        if (!found.length) { results.appendChild(h('p', { class: 'muted' }, 'Nothing found. Try fewer or different words.')); return; }
        found.forEach(function (d) {
          results.appendChild(listRow({
            title: d.name || d.display_id, badges: d.sbol_class ? badge(d.sbol_class, 'badge-muted') : null,
            sub: d.description, meta: [d.uri],
            actions: [button('Use', {
              cls: 'btn-sm btn-accent', onClick: function () {
                onPick({ iri: d.uri, label: d.name || d.display_id, sbol_class: d.sbol_class || null, sbol_version: '2' });
                ctl.close(null);
              }
            })]
          }));
        });
      } catch (e) {
        results.textContent = '';
        if (e.status !== 401) results.appendChild(errorCallout(e));
      } finally {
        setBusy(go, false);
      }
    }
    go.addEventListener('click', run);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); run(); } });

    var ctl = openModal({
      title: 'Find a design on SynBioHub',
      icon: 'search',
      wide: true,
      body: h('div', null,
        field('SynBioHub', instSel),
        note,
        h('div', { class: 'inline-form', style: { marginTop: '10px' } }, field('Search', q, { hint: 'Or paste a design IRI to look it up.' }), go),
        results),
      actions: [{ label: 'Close', cls: 'btn-quiet' }]
    });
    synbiohubStatus().then(function (list) {
      instances = list;
      list.forEach(function (i) { instSel.appendChild(h('option', { value: i.instance }, hostOf(i.instance))); });
      sync();
      q.focus();
    }).catch(function (e) { results.appendChild(errorCallout(e)); });
  }

  function sendToSynBioHubModal(study) {
    var instSel = h('select', { 'aria-label': 'SynBioHub' });
    var where = selectEl([
      { value: 'new', label: study.latest_version ? 'Its own collection, as version ' + study.latest_version : 'Its own collection (draft, as version 0)' },
      { value: 'existing', label: 'One of my collections' }
    ], 'new');
    var collSel = h('select', { 'aria-label': 'Collection', disabled: true }, h('option', { value: '' }, 'Choose SynBioHub first'));
    var collRow = field('Collection', collSel);
    var replace = toggleSwitch('Replace what is already there', false, { help: 'SynBioHub refuses to overwrite an upload unless you ask. Leave this off unless you mean to replace an earlier upload.' });
    var result = h('div');
    var instances = [];
    collRow.hidden = true;

    async function loadCollections() {
      collSel.textContent = '';
      collSel.disabled = true;
      collSel.appendChild(h('option', { value: '' }, 'Loading…'));
      try {
        var list = await api('GET', '/api/synbiohub/collections?instance=' + encodeURIComponent(instSel.value));
        collSel.textContent = '';
        if (!list.length) { collSel.appendChild(h('option', { value: '' }, 'You have no collections there yet')); return; }
        list.forEach(function (c) { collSel.appendChild(h('option', { value: c.uri }, (c.name || c.display_id) + ' (version ' + c.version + ')')); });
        collSel.disabled = false;
      } catch (e) {
        collSel.textContent = '';
        collSel.appendChild(h('option', { value: '' }, 'Could not load collections'));
        if (e.status !== 401) result.appendChild(errorCallout(e));
      }
    }
    function sync() {
      collRow.hidden = where.value !== 'existing';
      var inst = instances.find(function (i) { return i.instance === instSel.value; });
      result.textContent = '';
      if (inst && !inst.signed_in) result.appendChild(callout('warn', 'Not signed in to ' + hostOf(inst.instance), h('div', null, 'Sign in under Account settings, then come back. ', h('a', { href: '#/account' }, 'Go to Account settings'))));
      if (where.value === 'existing' && inst && inst.signed_in) loadCollections();
    }
    where.addEventListener('change', sync);
    instSel.addEventListener('change', sync);

    var ctl = openModal({
      title: 'Send to SynBioHub',
      icon: 'upload',
      body: h('div', null,
        h('p', { class: 'modal-text' }, 'Sends this study as SBOL 2.3 to your SynBioHub account: the experiment, its data with links to the raw files here, and its samples linked to their designs. SynBioHub keeps it private to you until you share it there.'),
        field('SynBioHub', instSel),
        field('Into', where),
        collRow,
        replace.row,
        result),
      actions: [
        { label: 'Close', cls: 'btn-quiet' },
        {
          label: 'Send', cls: 'btn-accent', primary: true, busyLabel: 'Sending…',
          onClick: async function (m) {
            var body = { instance: instSel.value, overwrite: replace.input.checked };
            if (where.value === 'existing') {
              if (!collSel.value) { m.setError('Choose a collection.'); return false; }
              body.collection = collSel.value;
            }
            var res = await api('POST', '/api/studies/' + study.id + '/synbiohub', body);
            result.textContent = '';
            result.appendChild(callout('ok', 'Sent to ' + hostOf(res.instance),
              h('div', null, /^https?:/.test(res.collection) ? h('a', { href: res.collection, target: '_blank', rel: 'noopener noreferrer' }, res.collection) : res.collection)));
            toast('Sent to SynBioHub');
            return false;
          }
        }
      ]
    });
    synbiohubStatus().then(function (list) {
      instances = list;
      list.forEach(function (i) { instSel.appendChild(h('option', { value: i.instance }, hostOf(i.instance) + (i.signed_in ? ' (' + i.username + ')' : ''))); });
      sync();
    }).catch(function (e) { result.appendChild(errorCallout(e)); });
    return ctl;
  }

  function synbiohubCard(ctx) {
    var box = h('div', null, skeleton(1));
    var card = h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'SynBioHub', helpIcon('Sign in to look up designs and send studies to your SynBioHub account. BOB keeps the token SynBioHub returns, encrypted; your SynBioHub password is not stored.')),
      box);

    async function load() {
      var list;
      try {
        list = await synbiohubStatus();
      } catch (e) {
        if (!ctx.alive()) return;
        box.textContent = '';
        box.appendChild(errorCallout(e, load));
        return;
      }
      if (!ctx.alive()) return;
      box.textContent = '';
      list.forEach(function (inst) {
        if (inst.signed_in) {
          box.appendChild(listRow({
            title: hostOf(inst.instance), badges: badge('Signed in', 'badge-accent'), sub: inst.username,
            actions: [button('Sign out', {
              cls: 'btn-sm btn-quiet', onClick: async function () {
                await api('POST', '/api/synbiohub/logout', { instance: inst.instance });
                toast('Signed out of ' + hostOf(inst.instance), 'info');
                load();
              }
            })]
          }));
          return;
        }
        var email = h('input', { type: 'text', autocomplete: 'off', placeholder: 'you@lab.org or user name' });
        var pw = h('input', { type: 'password', autocomplete: 'off' });
        var err = h('div', { class: 'field-error', role: 'alert', hidden: true });
        var go = button('Sign in', { cls: 'btn-accent' });
        var submit = async function () {
          formError(err, null);
          if (!email.value.trim() || !pw.value) { formError(err, 'Enter your SynBioHub email or user name and password.'); return; }
          setBusy(go, true, 'Signing in…');
          try {
            await api('POST', '/api/synbiohub/login', { instance: inst.instance, email: email.value.trim(), password: pw.value });
            pw.value = '';
            toast('Signed in to ' + hostOf(inst.instance));
            load();
          } catch (e) {
            if (e.status !== 401) formError(err, e.message);
          } finally {
            setBusy(go, false);
          }
        };
        go.addEventListener('click', submit);
        pw.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
        box.appendChild(h('div', { class: 'synbiohub-signin' },
          h('div', { class: 'form-label' }, hostOf(inst.instance)),
          h('div', { class: 'inline-form' }, field('Email or user name', email), field('Password', pw), go),
          err));
      });
    }
    load();
    return card;
  }

  function noWorkspaceCard() {
    return h('section', { class: 'card' }, emptyState('bob', 'No workspace yet',
      'Workspaces hold your investigations, members, and mappings. Create one to start.',
      button('New workspace', { cls: 'btn-accent', icon: 'plus', onClick: newWorkspaceModal })));
  }

  function firstName(s) {
    return String(s || '').trim().split(/\s+/)[0];
  }

  function stat(n, one, many) {
    return h('div', { class: 'stat' }, h('div', { class: 'stat-value' }, String(n)), h('div', { class: 'stat-label' }, n === 1 ? one : many));
  }

  async function viewHome(view, ctx) {
    var user = state.me.user || {};
    var ws = currentWs();
    var stats = h('div', { class: 'stat-grid' });
    view.appendChild(pageHero('Home', 'Welcome back, ' + firstName(user.name || user.email), [
      h('p', { class: 'page-desc' }, ws ? ws.name + ' at a glance, and what has been published on this server.' : 'Create a workspace, or accept an invitation to one, to start.'),
      ws ? stats : null
    ]));
    var invitations = invitationsCard(ctx);
    if (invitations) view.appendChild(invitations);
    if (!ws) view.appendChild(noWorkspaceCard());

    var recentList = h('div', { class: 'list' }, skeleton(2));
    if (ws) {
      view.appendChild(h('section', { class: 'card' },
        h('div', { class: 'card-title' }, 'Recent studies', helpIcon('Studies of this workspace, the most recently active first: created, given an assay, or published as a new version.')),
        recentList));
    }
    var publishedList = h('div', { class: 'list' }, skeleton(2));
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Published on this server', helpIcon('Studies whose owners published them. Anyone with an account here can read and download them, and each version has its own citable link.')),
      publishedList));

    async function loadOverview() {
      var o;
      try {
        o = await api('GET', '/api/workspaces/' + ws.id + '/overview');
      } catch (e) {
        if (!ctx.alive()) return;
        recentList.textContent = '';
        recentList.appendChild(errorCallout(e, loadOverview));
        return;
      }
      if (!ctx.alive()) return;
      stats.textContent = '';
      appendKids(stats, [stat(o.investigations, 'investigation', 'investigations'), stat(o.studies, 'study', 'studies'), stat(o.assays, 'assay', 'assays'), stat(o.published, 'published', 'published')]);
      recentList.textContent = '';
      if (!o.recent.length) {
        recentList.appendChild(emptyState('bob:flask', 'No studies yet', writeLock(ws.id) ? 'Nothing has been added to this workspace yet.' : 'Create an investigation under Projects, then add a study to it.'));
        return;
      }
      o.recent.forEach(function (s) {
        recentList.appendChild(listRow({
          href: '#/study/' + s.id, glyph: 'flask', title: s.title, badges: visibilityBadge(s.visibility), sub: s.investigation_title,
          meta: [plural(s.assay_count || 0, 'assay'), 'Last activity ' + fmtDate(s.last_activity)]
        }));
      });
    }

    async function loadPublished() {
      var list;
      try {
        list = await api('GET', '/api/published');
      } catch (e) {
        if (!ctx.alive()) return;
        publishedList.textContent = '';
        publishedList.appendChild(errorCallout(e, loadPublished));
        return;
      }
      if (!ctx.alive()) return;
      publishedList.textContent = '';
      if (!list.length) {
        publishedList.appendChild(emptyState('eye', 'Nothing published yet', 'A workspace owner publishes a study from its page. Published studies appear here for everyone with an account.'));
        return;
      }
      list.forEach(function (s) {
        publishedList.appendChild(listRow({
          href: '#/study/' + s.id, glyph: 'layers', title: s.title, badges: s.license ? badge(LICENSE_NAMES[s.license] || s.license, 'badge-muted') : null,
          sub: (s.authors || []).map(authorName).join(', '),
          meta: ['Version ' + s.latest_version, 'Published ' + fmtDate(s.published_at), s.version_created_at && s.latest_version > 1 ? 'Updated ' + fmtDate(s.version_created_at) : null]
        }));
      });
    }

    await Promise.all([ws ? loadOverview() : null, loadPublished()]);
  }

  /* ===================================================================
     Projects: investigations
     =================================================================== */

  function investigationModal(ws, inv, onDone) {
    var title = h('input', { type: 'text', value: inv ? inv.title : '', placeholder: 'e.g. Inducible promoter characterization', maxlength: '200' });
    var desc = h('textarea', { rows: '3', placeholder: 'What this investigation is about (optional)' });
    desc.value = inv ? (inv.description || '') : '';
    openModal({
      title: inv ? 'Edit investigation' : 'New investigation',
      icon: 'folder',
      body: h('div', null, field('Title', title), field('Description', desc)),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: inv ? 'Save' : 'Create', cls: 'btn-accent', primary: true, busyLabel: 'Saving…',
          onClick: async function (m) {
            var t = title.value.trim();
            if (!t) { m.setError('Give the investigation a title.'); title.focus(); return false; }
            var body = { title: t, description: desc.value.trim() };
            var res = inv
              ? await api('PATCH', '/api/investigations/' + inv.id, body)
              : await api('POST', '/api/workspaces/' + ws.id + '/investigations', body);
            if (res && res.id !== undefined) state.invCache.set(String(res.id), res);
            toast(inv ? 'Investigation saved' : 'Investigation created');
            onDone(res);
          }
        }
      ]
    });
  }

  function deleteInvestigation(inv, onDone) {
    var studies = inv.study_count || 0;
    return confirmDialog({
      title: 'Delete investigation?',
      message: 'This permanently deletes “' + inv.title + '”' + (studies ? ' and its ' + plural(studies, 'study', 'studies') + ', with their samples, assays, and raw files.' : '.') + ' This cannot be undone.',
      confirmLabel: 'Delete investigation',
      action: async function () {
        await api('DELETE', '/api/investigations/' + inv.id);
        state.invCache.delete(String(inv.id));
        toast('Investigation deleted');
        onDone();
      }
    });
  }

  async function viewProjects(view, ctx) {
    var ws = currentWs();
    if (!ws) { view.appendChild(noWorkspaceCard()); return; }
    var lock = writeLock(ws.id);
    var list = h('div', { class: 'list' }, skeleton(3));
    var count = cardCount();
    var card = h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Investigations', helpIcon('An investigation groups related studies, for example one project or one paper. Each study holds samples, assays, and their analysis.'), count),
        button('New investigation', {
          cls: 'btn-accent btn-sm', icon: 'plus', locked: lock,
          onClick: function () { investigationModal(ws, null, function (inv) { location.hash = '#/projects/' + inv.id; }); }
        })),
      list);
    view.appendChild(card);

    async function load() {
      list.textContent = '';
      list.appendChild(skeleton(3));
      var invs;
      try {
        invs = await listInvestigations(ws.id);
      } catch (e) {
        if (!ctx.alive()) return;
        list.textContent = '';
        list.appendChild(errorCallout(e, load));
        return;
      }
      if (!ctx.alive()) return;
      list.textContent = '';
      count.textContent = invs.length ? String(invs.length) : '';
      if (!invs.length) {
        list.appendChild(emptyState('bob:database', 'No investigations yet',
          lock ? 'Nothing has been added to this workspace yet.' : 'An investigation groups the studies of one project. Studies hold your samples and plate-reader assays.'));
        return;
      }
      invs.forEach(function (inv) {
        list.appendChild(listRow({
          href: '#/projects/' + inv.id, glyph: 'folder', title: inv.title, sub: inv.description,
          meta: [plural(inv.study_count || 0, 'study', 'studies'), 'Created ' + fmtDate(inv.created_at)],
          actions: lock ? null : [
            iconButton('pencil', 'Rename or describe', function () { investigationModal(ws, inv, load); }),
            iconButton('trash', 'Delete investigation', function () { deleteInvestigation(inv, load); }, { danger: true })]
        }));
      });
    }
    await load();
  }

  /* ===================================================================
     Projects: studies of one investigation
     =================================================================== */

  function studyModal(inv, study, onDone) {
    var title = h('input', { type: 'text', value: study ? study.title : '', placeholder: 'e.g. pTet dose response, 24 h kinetic', maxlength: '200' });
    var desc = h('textarea', { rows: '3', placeholder: 'Conditions, protocol notes, or aims (optional)' });
    desc.value = study ? (study.description || '') : '';
    var authors = study ? authorsEditor(study.authors) : null;
    openModal({
      title: study ? 'Edit study' : 'New study',
      icon: 'flask',
      wide: !!study,
      body: h('div', null,
        field('Title', title),
        field('Description', desc),
        study ? h('div', { class: 'form-label' }, 'Authors', helpIcon('The people to cite for this study once it is published, in citation order.')) : null,
        authors ? authors.el : null,
        study ? versionHint(study) : h('div', { class: 'hint' }, 'A new study is private to this workspace. A workspace owner can publish it later.')),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: study ? 'Save' : 'Create study', cls: 'btn-accent', primary: true, busyLabel: 'Saving…',
          onClick: async function (m) {
            var t = title.value.trim();
            if (!t) { m.setError('Give the study a title.'); title.focus(); return false; }
            var body = { title: t, description: desc.value.trim() };
            if (authors) {
              var got = authors.get();
              if (got.error) { m.setError(got.error); got.focus.focus(); return false; }
              if (!got.authors.length && study.visibility === 'public') { m.setError('A published study needs at least one author.'); return false; }
              body.authors = got.authors;
            }
            var res = study
              ? await api('PATCH', '/api/studies/' + study.id, body)
              : await api('POST', '/api/investigations/' + inv.id + '/studies', body);
            toast(study ? 'Study saved' : 'Study created');
            onDone(res);
          }
        }
      ]
    });
  }

  function authorName(a) {
    return [a.given_name, a.family_name].filter(Boolean).join(' ');
  }

  /* Rows of inputs under a header line, with an add button. `build(data)` returns {cells, get, focus, tools}. */
  function rowEditor(o) {
    var rows = h('div');
    var head = h('div', { class: 'comp-head ' + o.cls + '-head', 'aria-hidden': 'true' }, o.columns.map(function (c) { return h('span', null, c); }), h('span'));
    function sync() { head.hidden = !rows.children.length; }
    function add(data) {
      var r = o.build(data || {});
      var row = h('div', { class: o.cls + '-row' }, r.cells);
      var tools = (r.tools || []).slice();
      if (o.reorder) {
        tools.push(iconButton('arrowUp', 'Move up', function () { if (row.previousSibling) rows.insertBefore(row, row.previousSibling); }));
        tools.push(iconButton('arrowDown', 'Move down', function () { if (row.nextSibling) rows.insertBefore(row.nextSibling, row); }));
      }
      tools.push(iconButton('x', o.removeLabel, function () { row.remove(); sync(); }, { danger: true }));
      row.appendChild(h('div', { class: 'row-tools' }, tools));
      row._entry = r;
      rows.appendChild(row);
      sync();
      return r;
    }
    (o.initial || []).forEach(add);
    sync();
    var addBtn = h('button', { type: 'button', class: 'add-row-btn' }, icon('plus'), o.addLabel);
    addBtn.addEventListener('click', function () { add().focus.focus(); });
    return {
      el: h('div', null, head, rows, addBtn),
      entries: function () { return Array.prototype.map.call(rows.children, function (row) { return row._entry; }); }
    };
  }

  /* The citation order matters, so author rows can be moved up and down. */
  function authorsEditor(initial) {
    var editor = rowEditor({
      cls: 'author', columns: ['Given name', 'Family name', 'ORCID iD', 'Affiliation'], addLabel: 'Add author', removeLabel: 'Remove author', reorder: true, initial: initial,
      build: function (a) {
        var given = h('input', { type: 'text', value: a.given_name || '', placeholder: 'Given name', 'aria-label': 'Given name', maxlength: '120' });
        var family = h('input', { type: 'text', value: a.family_name || '', placeholder: 'Family name', 'aria-label': 'Family name', maxlength: '200' });
        var orcid = h('input', { type: 'text', value: a.orcid || '', placeholder: '0000-0000-0000-0000', 'aria-label': 'ORCID iD', spellcheck: 'false', maxlength: '60' });
        var aff = h('input', { type: 'text', value: a.affiliation || '', placeholder: 'Affiliation', 'aria-label': 'Affiliation', maxlength: '200' });
        return {
          cells: [given, family, orcid, aff], focus: given, orcid: orcid,
          get: function () { return { given_name: given.value.trim(), family_name: family.value.trim(), orcid: orcid.value.trim(), affiliation: aff.value.trim() }; }
        };
      }
    });
    return {
      el: editor.el,
      /* {authors} when every row is usable, {error, focus} otherwise. Empty rows are skipped. */
      get: function () {
        var out = [];
        var entries = editor.entries();
        for (var i = 0; i < entries.length; i++) {
          var a = entries[i].get();
          if (!a.given_name && !a.family_name && !a.orcid && !a.affiliation) continue;
          if (!a.given_name) return { error: 'Each author needs a given name.', focus: entries[i].focus };
          if (a.orcid && !/^(https?:\/\/orcid\.org\/)?\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/.test(a.orcid)) return { error: 'An ORCID iD looks like 0000-0002-1825-0097.', focus: entries[i].orcid };
          out.push(a);
        }
        return { authors: out };
      }
    };
  }

  function meAsAuthor() {
    var parts = ((state.me && state.me.user && state.me.user.name) || '').trim().split(/\s+/);
    if (!parts[0]) return [];
    return [{ given_name: parts.length > 1 ? parts.slice(0, -1).join(' ') : parts[0], family_name: parts.length > 1 ? parts[parts.length - 1] : '' }];
  }

  function publishModal(study, onDone) {
    var license = selectEl([
      { value: 'CC-BY-4.0', label: 'CC BY 4.0: anyone may reuse the data, crediting the study' },
      { value: 'CC0-1.0', label: 'CC0 1.0: anyone may reuse the data without conditions' }
    ], study.license || 'CC-BY-4.0');
    var again = study.visibility === 'withdrawn';
    var authors = authorsEditor((study.authors && study.authors.length) ? study.authors : meAsAuthor());
    openModal({
      title: study.visibility === 'public' ? 'Choose a license' : (again ? 'Publish again?' : 'Publish this study?'),
      icon: 'eye',
      wide: true,
      body: h('div', null,
        h('p', { class: 'modal-text' }, 'Anyone with an account on this BOB server will be able to find, read, and download this study: its samples, assays, plate layouts, and raw files. Members of other workspaces cannot change it.'),
        h('p', { class: 'modal-text' }, 'From then on, every saved change creates a new version. Earlier versions stay readable, each with its own link, so a result can always be checked against the data it came from.'),
        h('p', { class: 'modal-text' }, 'You can withdraw the study later but not delete it: readers who follow its link then see a withdrawal notice, and copies already downloaded remain.'),
        field('License', license, { help: 'The terms under which others may reuse the published data. CC BY 4.0 asks for credit; CC0 1.0 places the data in the public domain.' }),
        h('div', { class: 'form-label' }, 'Authors', helpIcon('The people to cite for this dataset, in citation order. They need not have a BOB account. An ORCID iD links each one to their record.')),
        authors.el),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: study.visibility === 'public' ? 'Set license' : 'Publish', cls: 'btn-accent', primary: true, busyLabel: 'Publishing…',
          onClick: async function (m) {
            var got = authors.get();
            if (got.error) { m.setError(got.error); got.focus.focus(); return false; }
            if (!got.authors.length) { m.setError('Add at least one author, so the dataset can be cited.'); return false; }
            var res = await api('POST', '/api/studies/' + study.id + '/publish', { license: license.value, authors: got.authors });
            toast(study.visibility === 'public' ? 'License set' : 'Study published as version ' + res.latest_version);
            onDone(res);
          }
        }
      ]
    });
  }

  function withdrawModal(study, onDone) {
    var reason = h('textarea', { rows: '3', placeholder: 'e.g. The plate reader was miscalibrated; corrected data are in study …' });
    openModal({
      title: 'Withdraw this study?',
      icon: 'warning',
      body: h('div', null,
        h('p', { class: 'modal-text' }, 'Readers outside this workspace will no longer see the study. Anyone who follows a link to it, including links in papers, sees that it was withdrawn, when, and the reason you give below.'),
        h('p', { class: 'modal-text' }, 'Members of this workspace keep full access, and an owner can publish it again later.'),
        field('Reason', reason, { hint: 'Shown to readers. Say what was wrong and where corrected data are, if anywhere.' })),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: 'Withdraw study', cls: 'btn-danger-solid', primary: true, busyLabel: 'Withdrawing…',
          onClick: async function (m) {
            var r = reason.value.trim();
            if (!r) { m.setError('Give readers a reason.'); reason.focus(); return false; }
            var res = await api('POST', '/api/studies/' + study.id + '/withdraw', { reason: r });
            toast('Study withdrawn', 'info');
            onDone(res);
          }
        }
      ]
    });
  }

  function deadEndPage(view, crumb, illustration, title, text) {
    view.textContent = '';
    view.appendChild(crumbs([{ label: 'Home', href: '#/home' }, { label: crumb }]));
    view.appendChild(h('section', { class: 'card' }, emptyState(illustration, title, text, h('a', { class: 'btn', href: '#/home' }, 'Back home'))));
  }

  function withdrawnPage(view, info) {
    var when = info.withdrawn_at ? fmtDate(info.withdrawn_at) : 'an earlier date';
    deadEndPage(view, 'Withdrawn', 'bob:confused', 'This study was withdrawn',
      '“' + info.title + '” was withdrawn on ' + when + ' after ' + plural(info.versions || 0, 'published version') + '. The reason given: ' + (info.reason || 'none') + '.');
  }

  function deleteStudy(study, onDone) {
    return confirmDialog({
      title: 'Delete study?',
      message: 'This permanently deletes “' + study.title + '” with its ' + plural(study.sample_count || 0, 'sample') + ' and ' + plural(study.assay_count || 0, 'assay') + ', including the raw files. This cannot be undone.',
      confirmLabel: 'Delete study',
      action: async function () {
        await api('DELETE', '/api/studies/' + study.id);
        toast('Study deleted');
        onDone();
      }
    });
  }

  function visibilityBadge(v) {
    if (v === 'public') return badge('Public', 'badge-accent', { title: 'Readable by anyone with an account on this server' });
    if (v === 'withdrawn') return badge('Withdrawn', 'badge-warn', { title: 'Readers who follow its link see a withdrawal notice' });
    return badge('Private', 'badge-muted', { title: 'Visible to workspace members only' });
  }

  /* Next to every save on a public study: each save there becomes a citable version. */
  function versionHint(study, verb) {
    if (!study || study.visibility !== 'public') return null;
    var next = (study.latest_version || 0) + 1;
    return h('div', { class: 'hint version-hint' }, icon('layers'),
      (verb || 'Saving') + ' creates version ' + next + ' of this public study. Make all your changes first to keep its history short.');
  }

  function versionReason(n) {
    return 'This is version ' + n + ' of a published study. A published version never changes.';
  }

  function citableLink(studyId, n) {
    return location.origin + '/#/study/' + studyId + '/v/' + n;
  }

  function notFoundPage(view, what, text) {
    deadEndPage(view, 'Not found', 'bob:confused', what + ' not found', text || 'It may have been deleted, or it belongs to a workspace you are not a member of.');
  }

  function viewNotFound(view) {
    notFoundPage(view, 'Page', 'There is no page at this address. Check the link, or go back home.');
  }

  async function viewInvestigation(view, ctx, invId) {
    view.appendChild(skeleton(2));
    state.invCache.delete(String(invId));
    var inv = await findInvestigation(invId);
    if (!ctx.alive()) return;
    view.textContent = '';
    if (!inv) {
      notFoundPage(view, 'Investigation');
      return;
    }
    adoptWorkspace(inv.workspace_id);
    var ws = wsById(inv.workspace_id) || currentWs();
    var lock = writeLock(inv.workspace_id);

    view.appendChild(crumbs([{ label: ws ? ws.name : 'Projects', href: '#/projects' }, { label: inv.title }]));
    view.appendChild(pageHero('Investigation', inv.title, [
      inv.description ? h('p', { class: 'page-desc' }, inv.description) : null,
      h('div', { class: 'page-meta' }, h('span', null, 'Created ' + fmtDate(inv.created_at)))
    ], [
      downloadButton('ISA-JSON', '/api/investigations/' + inv.id + '/isa', slugify(inv.title) + '.isa.json', 'Download this investigation with its studies and assays as an ISA-JSON document.'),
      button('Edit', { cls: 'btn-sm', icon: 'pencil', locked: lock, onClick: function () { investigationModal(ws, inv, function () { route(true); }); } }),
      button('Delete', { cls: 'btn-sm btn-danger', icon: 'trash', locked: lock, onClick: function () { deleteInvestigation(inv, function () { location.hash = '#/projects'; }); } })
    ]));

    var list = h('div', { class: 'list' }, skeleton(2));
    var newStudy = function () { studyModal(inv, null, function (s) { location.hash = '#/study/' + s.id; }); };
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Studies', helpIcon('A study is one experiment: its samples, the plate-reader assays measured on them, and their analysis. Export a study as SBOL 2.3 from its page.')),
        button('New study', { cls: 'btn-accent btn-sm', icon: 'plus', locked: lock, onClick: newStudy })),
      list));

    async function load() {
      list.textContent = '';
      list.appendChild(skeleton(2));
      var studies;
      try {
        studies = await api('GET', '/api/investigations/' + inv.id + '/studies');
      } catch (e) {
        if (!ctx.alive()) return;
        list.textContent = '';
        list.appendChild(errorCallout(e, load));
        return;
      }
      if (!ctx.alive()) return;
      list.textContent = '';
      if (!studies.length) {
        list.appendChild(emptyState('bob:flask', 'No studies yet',
          lock ? 'This investigation has no studies yet.' : 'A study holds the samples of one experiment and the plate-reader files measured on them.'));
        return;
      }
      studies.forEach(function (s) {
        list.appendChild(listRow({
          href: '#/study/' + s.id, glyph: 'flask', title: s.title, badges: visibilityBadge(s.visibility), sub: s.description,
          meta: [plural(s.sample_count || 0, 'sample'), plural(s.assay_count || 0, 'assay'), 'Created ' + fmtDate(s.created_at)],
          actions: lock ? null : [
            iconButton('pencil', 'Edit study', function () { studyModal(inv, s, load); }),
            s.visibility === 'private' ? iconButton('trash', 'Delete study', function () { deleteStudy(s, load); }, { danger: true }) : null]
        }));
      });
    }
    await load();
  }

  /* ===================================================================
     Study view: samples, assays, import, export
     =================================================================== */

  function isHttp(s) {
    return /^https?:\/\//i.test(s || '');
  }

  function componentChip(c) {
    var text = c.label || c.iri || '(no IRI)';
    var target = isHttp(c.iri)
      ? h('a', { href: c.iri, target: '_blank', rel: 'noopener noreferrer', title: c.iri }, text)
      : h('span', { title: c.iri || '' }, text);
    var amount = c.amount != null ? h('span', { class: 'chip-amount' }, String(c.amount) + (c.unit ? ' ' + c.unit : '')) : null;
    return h('span', { class: 'chip' }, h('span', { class: 'chip-role' }, c.role || 'other'), target, amount);
  }

  function sampleModal(study, sample, onDone) {
    var name = h('input', { type: 'text', value: sample ? sample.name : '', placeholder: 'e.g. pTet-YFP + 10 ng/mL aTc', maxlength: '200' });
    var type = selectEl(SAMPLE_TYPES, sample ? sample.sample_type : 'sample');
    var desc = h('textarea', { rows: '2', placeholder: 'Optional notes' });
    desc.value = sample ? (sample.description || '') : '';
    var components = rowEditor({
      cls: 'comp', columns: ['Role', 'IRI', 'Label', 'Amount', 'Unit'], addLabel: 'Add component', removeLabel: 'Remove component', initial: sample && sample.components,
      build: function (c) {
        var role = selectEl(COMPONENT_ROLES.map(function (r) { return { value: r, label: humanize(r) }; }), c.role || 'strain', { 'aria-label': 'Component role' });
        var iri = h('input', { type: 'text', class: 'comp-iri', value: c.iri || '', placeholder: 'https://synbiohub.org/…', 'aria-label': 'Component IRI', spellcheck: 'false' });
        var label = h('input', { type: 'text', value: c.label || '', placeholder: 'Display name', 'aria-label': 'Component label' });
        var amount = h('input', { type: 'number', class: 'comp-amount', min: '0', step: 'any', value: c.amount != null ? String(c.amount) : '', placeholder: 'Amount', 'aria-label': 'Component amount' });
        var unit = h('input', { type: 'text', class: 'comp-unit', value: c.unit || '', placeholder: 'Unit', maxlength: '40', 'aria-label': 'Component unit' });
        // A design's SBOL version and class stay with it unless the IRI is changed by hand.
        var meta = { iri: c.iri || '', sbol_version: c.sbol_version || null, sbol_class: c.sbol_class || null };
        return {
          cells: [role, iri, label, amount, unit], focus: iri,
          tools: [iconButton('search', 'Find on SynBioHub', function () {
            designSearchModal(function (d) {
              iri.value = d.iri;
              if (!label.value.trim()) label.value = d.label;
              meta = { iri: d.iri, sbol_version: d.sbol_version, sbol_class: d.sbol_class };
            });
          })],
          get: function () {
            var same = iri.value.trim() === meta.iri;
            return {
              role: role.value, iri: iri.value.trim(), label: label.value.trim(), amount: amount.value === '' ? null : Number(amount.value),
              unit: unit.value.trim() || null, sbol_version: same ? meta.sbol_version : null, sbol_class: same ? meta.sbol_class : null
            };
          }
        };
      }
    });

    openModal({
      title: sample ? 'Edit sample' : 'New sample',
      icon: 'beaker',
      wide: true,
      body: h('div', null,
        h('div', { class: 'form-grid' },
          field('Name', name),
          field('Type', type, { help: 'Sample: cells you measured. Medium: wells with medium only. Untransformed: cells without the construct. Medium and untransformed wells are the controls for background correction.' }),
          field('Description', desc, { cls: 'span-2' })),
        h('div', { class: 'divider' }),
        h('div', { class: 'form-label' }, 'Components', helpIcon('Link what is in the sample to its design by IRI, for example a strain or plasmid on SynBioHub. The design stays where it is; BOB stores the link.')),
        h('div', { class: 'hint', style: { marginTop: '0', marginBottom: '10px' } }, 'A sample with several strains is a consortium.'),
        components.el,
        versionHint(study)),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: sample ? 'Save sample' : 'Add sample', cls: 'btn-accent', primary: true, busyLabel: 'Saving…',
          onClick: async function (m) {
            var n = name.value.trim();
            if (!n) { m.setError('Give the sample a name.'); name.focus(); return false; }
            var comps = [];
            var bad = null;
            components.entries().forEach(function (r) {
              var c = r.get();
              if (!c.iri && !c.label) return;
              if (!c.iri && !bad) bad = r;
              comps.push(c);
            });
            if (bad) {
              m.setError('Each component needs an IRI. Add one or remove the row.');
              bad.focus.focus();
              return false;
            }
            var body = { name: n, sample_type: type.value, description: desc.value.trim(), components: comps };
            var res = sample
              ? await api('PATCH', '/api/samples/' + sample.id, body)
              : await api('POST', '/api/studies/' + study.id + '/samples', body);
            toast(sample ? 'Sample saved' : 'Sample added');
            onDone(res);
          }
        }
      ]
    });
  }

  function deleteSample(sample, onDone, study) {
    return confirmDialog({
      title: 'Delete sample?',
      message: 'This deletes “' + sample.name + '” and unassigns it from every well it occupies in this study’s plate layouts.',
      extra: versionHint(study, 'Deleting'),
      confirmLabel: 'Delete sample',
      action: async function () {
        await api('DELETE', '/api/samples/' + sample.id);
        toast('Sample deleted');
        onDone();
      }
    });
  }

  function deleteAssay(assay, onDone, study) {
    var published = study && study.visibility !== 'private';
    return confirmDialog({
      title: 'Delete assay?',
      message: published
        ? 'This removes “' + assay.name + '” from the study. Earlier published versions keep it, with its measurements and raw file.'
        : 'This permanently deletes “' + assay.name + '”, its measurements, its plate layout, and the stored raw file unless another assay uses the same file.',
      extra: versionHint(study, 'Deleting'),
      confirmLabel: 'Delete assay',
      action: async function () {
        await api('DELETE', '/api/assays/' + assay.id);
        toast('Assay deleted');
        onDone();
      }
    });
  }

  var PLATE_FILE_TYPES = '.xlsx,.txt,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/plain,text/csv';
  var PLATE_FILE_PROMPT = 'Choose a .xlsx, .txt, or .csv file or drop it here';

  function fileFormat(name) {
    return /\.(txt|csv|tsv)$/i.test(name) ? 'delimited' : 'xlsx';
  }

  function mappingLabel(m) {
    return (m.emoji ? m.emoji + ' ' : '') + m.name + (m.version !== undefined && m.version !== null ? ' (v' + m.version + ')' : '');
  }

  function mappingRank(a, b) {
    return (b.builtin ? 1 : 0) - (a.builtin ? 1 : 0) || (b.stars || 0) - (a.stars || 0) || String(a.name).localeCompare(String(b.name)) || (b.version || 0) - (a.version || 0);
  }

  /* The mappings a study can read plate files with: built in or its workspace's, latest version of each. */
  function usableMappings(maps, wsId) {
    var latest = new Map();
    maps.forEach(function (m) {
      if (!(m.builtin || m.workspace_id === wsId)) return;
      if (m.modality && m.modality !== 'plate_reader') return;
      var prev = latest.get(m.key);
      if (!prev || (m.version || 0) > (prev.version || 0)) latest.set(m.key, m);
    });
    return Array.from(latest.values()).sort(mappingRank);
  }

  /* A mapping select for one study; `fit` switches to a mapping that reads the chosen file's type. */
  function mappingPicker(study, ctx, onError) {
    var select = h('select', { disabled: true }, h('option', null, 'Loading mappings…'));
    var formats = {};
    var lastFile = null;
    function fit() {
      if (!lastFile || !select.value || (formats[select.value] || 'xlsx') === fileFormat(lastFile)) return;
      var match = Array.prototype.find.call(select.options, function (o) { return (formats[o.value] || 'xlsx') === fileFormat(lastFile); });
      if (match) select.value = match.value;
    }
    loadMappings().then(function (maps) {
      if (!ctx.alive()) return;
      select.textContent = '';
      var usable = usableMappings(maps, study.workspace_id);
      if (!usable.length) { select.appendChild(h('option', { value: '' }, 'No mappings available')); return; }
      usable.forEach(function (m) {
        formats[m.key] = m.source_format;
        select.appendChild(h('option', { value: m.key }, mappingLabel(m)));
      });
      select.disabled = false;
      fit();
    }).catch(function (e) {
      if (!ctx.alive()) return;
      select.textContent = '';
      select.appendChild(h('option', { value: '' }, 'Mappings could not be loaded'));
      onError(e);
    });
    return {
      select: select,
      fit: function (fileName) { lastFile = fileName; fit(); },
      mismatch: function (fileName) {
        if (!select.value || fileFormat(fileName) === (formats[select.value] || 'xlsx')) return null;
        return (formats[select.value] === 'delimited' ? 'This mapping reads text exports (.txt or .csv).' : 'This mapping reads Excel .xlsx exports.') + ' The chosen file is ' + fileName + '.';
      }
    };
  }

  /* A drop zone around a file input; `onFiles` gets the chosen files as an array. */
  function fileDrop(o) {
    var input = h('input', { type: 'file', accept: o.accept, multiple: !!o.multiple, 'aria-label': o.label });
    var text = h('div', { class: 'dropzone-text' }, o.prompt);
    var sub = h('div', { class: 'dropzone-sub' }, o.sub || '');
    var zone = h('label', { class: 'dropzone' }, icon('upload'), h('div', null, text, sub), input);
    var files = [];
    function set(list) {
      files = Array.prototype.slice.call(list || []);
      if (!files.length) {
        input.value = '';
        text.textContent = o.prompt;
        sub.textContent = o.sub || '';
      } else {
        text.textContent = files.map(function (f) { return f.name; }).join(', ');
        sub.textContent = fmtBytes(files.reduce(function (n, f) { return n + f.size; }, 0)) + '. Choose again to replace ' + (files.length > 1 ? 'them.' : 'it.');
      }
      if (o.onFiles) o.onFiles(files);
    }
    input.addEventListener('change', function () { set(input.files); });
    ['dragenter', 'dragover'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add('drag'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      zone.addEventListener(ev, function () { zone.classList.remove('drag'); });
    });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      var dropped = e.dataTransfer && e.dataTransfer.files;
      if (dropped && dropped.length) set(o.multiple ? dropped : [dropped[0]]);
    });
    return { el: zone, files: function () { return files; }, clear: function () { set([]); } };
  }

  function uploadProgress() {
    var fill = h('div', { class: 'progress-bar-fill' });
    var status = h('div', { class: 'status-text', role: 'status', 'aria-live': 'polite' });
    var el = h('div', { hidden: true }, h('div', { class: 'progress-bar-track' }, fill), status);
    return {
      el: el,
      send: function (path, form, what, reading) {
        el.hidden = false;
        fill.classList.remove('indeterminate');
        fill.style.width = '0%';
        status.textContent = 'Uploading ' + what + '…';
        return uploadWithProgress(path, form, function (phase, frac) {
          if (phase === 'upload') {
            fill.style.width = Math.round(frac * 100) + '%';
            status.textContent = 'Uploading ' + what + ', ' + Math.round(frac * 100) + '%';
          } else {
            fill.classList.add('indeterminate');
            status.textContent = reading;
          }
        }).finally(function () { el.hidden = true; });
      }
    };
  }

  function importFailed(box, title, e) {
    if (e.status === 401) return;
    box.appendChild(callout('error', title, h('div', { style: { whiteSpace: 'pre-wrap' } }, e.message)));
  }

  function dropField(label, drop) {
    return h('div', { class: 'form-row' }, h('div', { class: 'form-label' }, label), drop.el);
  }

  async function viewStudy(view, ctx, studyId, versionParam) {
    var version = versionParam ? parseInt(versionParam, 10) : null;
    var q = version ? '?version=' + version : '';
    view.appendChild(skeleton(3));
    var study;
    try {
      study = await api('GET', '/api/studies/' + studyId + q);
    } catch (e) {
      if (e.status === 404 && !version) { if (ctx.alive()) notFoundPage(view, 'Study'); return; }
      if (e.status === 404) { if (ctx.alive()) notFoundPage(view, 'Version', 'This study has no version ' + version + '.'); return; }
      if (e.status === 410 && e.detail && e.detail.withdrawn) { if (ctx.alive()) withdrawnPage(view, e.detail.withdrawn); return; }
      throw e;
    }
    if (!ctx.alive()) return;
    adoptWorkspace(study.workspace_id);
    var lock = version ? versionReason(version) : writeLock(study.workspace_id);
    var owner = roleIn(study.workspace_id) === 'owner';
    var reload = function () { route(true); };
    var assayHref = function (id) { return '#/assay/' + id + (version ? '/v/' + version : ''); };
    view.textContent = '';

    view.appendChild(studyCrumbs(ctx, study, version ? [{ label: study.title, href: '#/study/' + study.id }, { label: 'Version ' + version }] : [{ label: study.title }]));
    if (version) {
      view.appendChild(versionNotice(study, version,
        'Version ' + version + ' of ' + study.latest_version + ', saved ' + fmtDateTime(study.version_created_at) + (study.version_note ? ': ' + study.version_note : '') + '. It never changes, so results can be checked against it.', true));
    }
    if (!version && owner && study.visibility === 'public' && !study.license) {
      view.appendChild(callout('warn', 'Choose a license for this public study',
        h('div', null, 'It was made public before BOB asked for a license and kept versions. Choose a license to confirm the publication, or withdraw it with Withdraw… below.'),
        h('div', { class: 'form-actions', style: { justifyContent: 'flex-start', marginTop: '8px' } },
          button('Choose license…', { cls: 'btn-sm btn-accent', onClick: function () { publishModal(study, reload); } }))));
    }
    if (!version && study.visibility === 'withdrawn') {
      view.appendChild(callout('warn', 'Withdrawn ' + fmtDate(study.withdrawn_at),
        h('div', null, 'Readers outside this workspace see a withdrawal notice with this reason: ' + study.withdraw_reason)));
    }

    function exporter(label, path, ext, help) {
      return downloadButton(label, '/api/studies/' + study.id + path + q, slugify(study.title) + (version ? '-v' + version : '') + ext, help);
    }
    var sbolBtn = exporter('SBOL 2.3', '/sbol', '.sbol.xml', 'Download this study as an SBOL 2.3 RDF/XML document: the study, its assays, and its samples, linked to their designs by IRI.' + (study.latest_version ? ' Its IRIs carry the version number.' : ''));
    var isaBtn = exporter('ISA-JSON', '/isa', '.isa.json', 'Download this study as an ISA-JSON document: its samples, assays, and raw-file checksums.');
    var crateBtn = exporter('RO-Crate', '/ro-crate', '.ro-crate.zip', 'Download the whole study as an RO-Crate: one zip with the raw files, the ISA-JSON and SBOL documents, and metadata that repositories such as Zenodo and WorkflowHub read.');

    var actions = [sbolBtn, isaBtn, crateBtn];
    if (!version && roleIn(study.workspace_id)) actions.push(button('SynBioHub…', { cls: 'btn-sm', icon: 'upload', onClick: function () { sendToSynBioHubModal(study); } }));
    if (!version) {
      if (owner && study.visibility !== 'public') actions.push(button(study.visibility === 'withdrawn' ? 'Publish again…' : 'Publish…', { cls: 'btn-sm btn-accent', icon: 'eye', onClick: function () { publishModal(study, reload); } }));
      if (owner && study.visibility === 'public') actions.push(button('Withdraw…', { cls: 'btn-sm', icon: 'warning', onClick: function () { withdrawModal(study, reload); } }));
      actions.push(button('Edit', { cls: 'btn-sm', icon: 'pencil', locked: lock, onClick: function () { studyModal(null, study, reload); } }));
      actions.push(button('Delete', {
        cls: 'btn-sm btn-danger', icon: 'trash',
        locked: lock || (study.visibility !== 'private' ? 'A published study cannot be deleted, because readers may have cited it. Withdraw it instead.' : null),
        onClick: function () { deleteStudy(study, function () { location.hash = '#/projects/' + study.investigation_id; }); }
      }));
    }
    var meta = [visibilityBadge(study.visibility)];
    if (study.license) meta.push(h('a', { class: 'badge badge-muted', href: study.license_url, target: '_blank', rel: 'noopener noreferrer' }, LICENSE_NAMES[study.license] || study.license));
    if (study.latest_version) meta.push(h('span', null, version ? 'Version ' + version + ' of ' + study.latest_version : 'Version ' + study.latest_version));
    meta.push(h('span', null, 'Created ' + fmtDate(study.created_at)));
    if (lock && !version) meta.push(h('span', { class: 'badge badge-warn', 'data-help': lock, tabindex: '0' }, icon('lock'), 'Read only'));

    view.appendChild(pageHero('Study', study.title, [
      (study.authors || []).length ? h('p', { class: 'byline' }, study.authors.map(function (a, i) {
        return [i ? ', ' : null, a.orcid ? h('a', { href: 'https://orcid.org/' + a.orcid, target: '_blank', rel: 'noopener noreferrer', title: 'ORCID ' + a.orcid }, authorName(a)) : authorName(a)];
      })) : null,
      study.description ? h('p', { class: 'page-desc' }, study.description) : null,
      h('div', { class: 'page-meta' }, meta)
    ], actions));

    var sampleList = h('div', { class: 'list' }, skeleton(2));
    var sampleCount = cardCount();
    var afterSampleChange = study.visibility === 'public' ? reload : function () { loadSamples(); };
    var newSample = function () { sampleModal(study, null, afterSampleChange); };
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Samples', helpIcon('Everything that went into a well: cells with their strains and plasmids, medium-only controls, and untransformed controls. A sample with several strains is a consortium.'), sampleCount),
        version ? null : button('New sample', { cls: 'btn-accent btn-sm', icon: 'plus', locked: lock, onClick: newSample })),
      sampleList));

    async function loadSamples() {
      var samples;
      try {
        samples = await api('GET', '/api/studies/' + study.id + '/samples' + q);
      } catch (e) {
        if (!ctx.alive()) return;
        sampleList.textContent = '';
        sampleList.appendChild(errorCallout(e, loadSamples));
        return;
      }
      if (!ctx.alive()) return;
      sampleList.textContent = '';
      sampleCount.textContent = samples.length ? String(samples.length) : '';
      if (!samples.length) {
        sampleList.appendChild(emptyState('beaker', 'No samples yet',
          lock ? 'No samples have been described for this study.' : 'Describe what went into the wells: your samples, plus medium and untransformed controls for background correction.'));
        return;
      }
      var styles = P.sampleStyles(samples);
      samples.forEach(function (s) {
        var strains = (s.components || []).filter(function (c) { return c.role === 'strain'; }).length;
        sampleList.appendChild(h('div', { class: 'sample-row' },
          P.swatch(styles.get(s.id)),
          h('div', { style: { minWidth: '0' } },
            h('div', { class: 'sample-name' }, s.name, typeBadge(s.sample_type),
              strains > 1 ? badge('Consortium · ' + strains + ' strains', 'badge-accent', { 'data-help': 'This sample holds several strains, so it is a consortium.' }) : null),
            s.description ? h('div', { class: 'sample-desc' }, s.description) : null,
            (s.components || []).length ? h('div', { class: 'chips' }, s.components.map(componentChip)) : null),
          lock ? h('span') : h('div', { class: 'row-actions' },
            iconButton('pencil', 'Edit sample', function () { sampleModal(study, s, afterSampleChange); }),
            iconButton('trash', 'Delete sample', function () { deleteSample(s, afterSampleChange, study); }, { danger: true }))));
      });
    }

    var assayList = h('div', { class: 'list' }, skeleton(1));
    var assayCard = h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Assays', helpIcon('An assay is one instrument run, read from its raw file through a mapping. BOB keeps the raw file unchanged and records its checksum.'))),
      assayList);
    view.appendChild(assayCard);
    var afterAssayChange = study.visibility === 'public' ? reload : function () { loadAssays(); };

    async function loadAssays() {
      var assays;
      try {
        assays = await api('GET', '/api/studies/' + study.id + '/assays' + q);
      } catch (e) {
        if (!ctx.alive()) return;
        assayList.textContent = '';
        assayList.appendChild(errorCallout(e, loadAssays));
        return;
      }
      if (!ctx.alive()) return;
      assayList.textContent = '';
      if (!assays.length) {
        assayList.appendChild(emptyState('plate', 'No assays yet',
          lock ? 'No instrument files are part of this study' + (version ? ' version.' : '.') : 'Import a plate-reader export below. BOB reads it with the mapping you pick and keeps the original file.'));
        return;
      }
      var maps = state.mappings || [];
      assays.forEach(function (a) {
        var m = maps.find(function (x) { return x.key === a.mapping_key; });
        var nWarn = (a.warnings || []).length;
        assayList.appendChild(listRow({
          href: assayHref(a.id), glyph: 'plate', emoji: m && m.emoji, title: a.name, badges: nWarn ? badge(plural(nWarn, 'warning'), 'badge-warn') : null,
          sub: (a.mapping_name || a.mapping_key || '') + (a.raw_file && a.raw_file.filename ? ' · ' + a.raw_file.filename : ''),
          meta: [plural((a.signals || []).length, 'signal'), plural((a.positions || []).length, 'well'), 'Imported ' + fmtDate(a.created_at)],
          actions: lock ? null : [iconButton('trash', 'Delete assay', function () { deleteAssay(a, afterAssayChange, study); }, { danger: true })]
        }));
      });
    }

    if (!lock) {
      var importKind = selectEl([{ value: 'plate', label: 'A plate-reader file' }, { value: 'workbook', label: 'An Excel-to-SBOL assay workbook with its plate files' }], 'plate', { 'aria-label': 'What to import' });
      var importArea = h('div');
      var showImport = function () {
        importArea.textContent = '';
        importArea.appendChild(importKind.value === 'workbook'
          ? workbookBox(study, ctx, study.visibility === 'public' ? reload : function () { loadSamples(); loadAssays(); })
          : importBox(study, ctx, afterAssayChange));
      };
      importKind.addEventListener('change', showImport);
      assayCard.appendChild(h('div', { class: 'import-kind' }, field('Import', importKind)));
      assayCard.appendChild(importArea);
      showImport();
    }
    else if (!version) assayCard.appendChild(h('div', { class: 'readonly-note', style: { marginTop: '14px', marginBottom: '0' } }, icon('lock'), 'Importing files needs editor access.'));

    var loaders = [loadSamples(), loadMappings().catch(function () { return []; }).then(loadAssays)];
    if (study.latest_version) {
      var historyList = h('div', { class: 'list' }, skeleton(1));
      view.appendChild(h('section', { class: 'card' },
        h('div', { class: 'card-title' }, 'History', helpIcon('Each published version keeps the study exactly as it was, with its own link and downloads, so results can be checked against the data they came from.')),
        historyList));
      loaders.push(api('GET', '/api/studies/' + study.id + '/versions').then(function (list) {
        if (!ctx.alive()) return;
        historyList.textContent = '';
        list.forEach(function (v) {
          var here = v.number === (version || study.latest_version);
          historyList.appendChild(listRow({
            href: '#/study/' + study.id + (v.number === study.latest_version ? '' : '/v/' + v.number), glyph: 'layers', title: 'Version ' + v.number,
            badges: [v.number === study.latest_version ? badge('Latest', 'badge-accent') : null, here ? badge('Shown', 'badge-muted') : null],
            sub: v.note, meta: [fmtDateTime(v.created_at), v.author],
            actions: [copyButton(citableLink(study.id, v.number), 'link')]
          }));
        });
      }).catch(function (e) {
        if (!ctx.alive()) return;
        historyList.textContent = '';
        historyList.appendChild(errorCallout(e));
      }));
    }
    await Promise.all(loaders);
  }

  /* An Excel-to-SBOL Assay workbook with one plate-reader file per assay: what SynBioSuite sends.
     A check shows what the import would do, and only a clean check offers the import. */
  function workbookBox(study, ctx, onImported) {
    var result = h('div', { style: { marginTop: '12px' } });
    var preview = h('div');
    var err = h('div', { class: 'field-error', role: 'alert', hidden: true });
    var picker = mappingPicker(study, ctx, function (e) { result.appendChild(errorCallout(e)); });
    var book = fileDrop({ accept: '.xlsx,.xlsm', label: 'Assay workbook', prompt: 'Choose the .xlsx or .xlsm workbook or drop it here', onFiles: reset });
    var plates = fileDrop({
      accept: PLATE_FILE_TYPES, multiple: true, label: 'Plate-reader files', prompt: 'Choose the plate files or drop them here', sub: 'One per assay in the workbook.',
      onFiles: function (fs) { if (fs[0]) picker.fit(fs[0].name); reset(); }
    });
    picker.select.addEventListener('change', reset);
    var progress = uploadProgress();
    var check = button('Check', { cls: 'btn-accent', icon: 'search' });
    var submit = button('Import workbook', { cls: 'btn-accent', icon: 'upload' });
    submit.hidden = true;
    var choices = null;

    function reset() {
      choices = null;
      preview.textContent = '';
      result.textContent = '';
      submit.hidden = true;
      check.hidden = false;
    }

    function form() {
      var fd = new FormData();
      var wb = book.files()[0];
      fd.append('workbook', wb, wb.name);
      plates.files().forEach(function (f) { fd.append('plates', f, f.name); });
      fd.append('mapping_key', picker.select.value);
      if (choices) {
        var chosen = {};
        Object.keys(choices).forEach(function (plate) { if (choices[plate].value) chosen[plate] = choices[plate].value; });
        if (Object.keys(chosen).length) fd.append('plate_assays', JSON.stringify(chosen));
      }
      return fd;
    }

    function ready() {
      formError(err, null);
      var wb = book.files()[0];
      var ps = plates.files();
      if (!wb) { formError(err, 'Choose the Excel-to-SBOL Assay workbook.'); return null; }
      if (!ps.length) { formError(err, 'Choose the plate-reader files, one per assay in the workbook.'); return null; }
      var wrong = ps.map(function (f) { return picker.mismatch(f.name); }).filter(Boolean)[0];
      if (wrong) { formError(err, wrong); return null; }
      if (!picker.select.value) { formError(err, 'Pick the mapping that describes your instrument.'); return null; }
      return wb.name + ' and ' + plural(ps.length, 'plate file');
    }

    function workbookPreview(found) {
      var box = h('div', { class: 'wb-preview' });
      if (found.problems.length) {
        box.appendChild(callout('error', 'Not ready to import', h('ul', null, found.problems.map(function (p) { return h('li', null, p); }))));
      }
      var assays = found.workbook.assays.filter(function (a) { return a.wells; });
      if (found.pairing.some(function (p) { return p.source !== 'only one'; })) {
        var before = choices || {};
        choices = {};
        box.appendChild(h('div', { class: 'form-label' }, 'Which assay each plate file holds',
          helpIcon('BOB never pairs files with assays by their order. A file whose name holds an assay ID is matched to it; choose the rest.')));
        box.appendChild(h('div', { class: 'wb-pairs' }, found.pairing.map(function (p) {
          var options = [{ value: '', label: 'Choose the assay…' }].concat(assays.map(function (a) {
            return { value: a.id, label: a.name + ' (' + a.id + ', ' + plural(a.wells, 'well') + ')' };
          }));
          var sel = selectEl(options, (before[p.plate] && before[p.plate].value) || p.assay_id || '', { 'aria-label': 'Assay for ' + p.plate });
          sel.addEventListener('change', function () { submit.hidden = true; check.hidden = false; });
          choices[p.plate] = sel;
          return h('div', { class: 'wb-pair' }, h('span', { class: 'wb-file' }, icon('plate'), p.plate), sel,
            p.source === 'file name' ? h('span', { class: 'hint' }, 'Matched by file name') : null);
        })));
      }
      found.assays.forEach(function (a) {
        var action = a.action === 'replace' ? badge('Replaces the earlier import', 'badge-warn')
          : a.action === 'unchanged' ? badge('Already imported, unchanged', 'badge-muted') : badge('New', 'badge-accent');
        box.appendChild(h('div', { class: 'wb-assay' },
          h('div', { class: 'wb-assay-head' }, h('strong', null, a.name), action, h('span', { class: 'hint' }, a.plate + ', ' + plural(a.wells, 'well'))),
          h('ol', { class: 'wb-channels' }, a.channels.map(function (c) {
            return h('li', null, c.color ? h('span', { class: 'wb-color', style: { background: c.color } }) : null,
              h('strong', null, c.name), c.description ? ', ' + c.description : '', h('span', { class: 'hint' }, ' read as ' + c.label));
          }))));
      });
      if (found.samples.length) {
        box.appendChild(h('div', { class: 'form-label' }, 'Samples from the sample designs',
          helpIcon('Each design is read from SynBioHub into its parts: medium, strain, plasmids, and supplements with their amounts. BOB keeps what it read with the design version, so a later edit on SynBioHub does not change this study.')));
        box.appendChild(h('div', { class: 'list wb-samples' }, found.samples.map(function (s) {
          var action = s.action === 'new' ? 'New' : s.action === 'update' ? 'Updated' : 'Kept as is';
          return h('div', { class: 'sample-row wb-sample' },
            h('div', { style: { minWidth: '0' } },
              h('div', { class: 'sample-name' }, s.name, badge(action, s.action === 'keep' ? 'badge-muted' : 'badge-accent')),
              s.parts.length ? h('div', { class: 'chips' }, s.parts.map(componentChip)) : null,
              s.error ? h('div', { class: 'hint wb-error' }, 'Not read from SynBioHub: ' + s.error) : null));
        })));
      }
      var w = warningsCallout(plural(found.warnings.length, 'warning'), found.warnings);
      if (w) box.appendChild(w);
      if (found.samples.some(function (s) { return s.error; })) {
        box.appendChild(h('p', { class: 'hint' }, 'Private designs are read with your SynBioHub sign-in. Sign in from your account menu, then check again.'));
      }
      return box;
    }

    check.addEventListener('click', async function () {
      var what = ready();
      if (!what) return;
      result.textContent = '';
      setBusy(check, true, 'Checking…');
      try {
        var found = await progress.send('/api/studies/' + study.id + '/workbook/check', form(), what, 'Reading the workbook, the plates, and the designs on SynBioHub…');
        if (!ctx.alive()) return;
        preview.textContent = '';
        preview.appendChild(workbookPreview(found));
        submit.hidden = !found.ok;
        check.hidden = found.ok;
      } catch (e) {
        importFailed(result, 'The workbook could not be checked', e);
      } finally {
        setBusy(check, false);
      }
    });

    submit.addEventListener('click', async function () {
      var what = ready();
      if (!what) return;
      result.textContent = '';
      setBusy(submit, true, 'Importing…');
      try {
        var res = await progress.send('/api/studies/' + study.id + '/workbook', form(), what, 'Reading the workbook and the plates…');
        book.clear();
        plates.clear();
        var fresh = res.assays.filter(function (a) { return a.action !== 'unchanged'; }).length;
        result.appendChild(callout('ok', res.changed ? 'Imported ' + plural(fresh, 'assay') : 'Nothing changed',
          h('div', null, plural(res.samples_created, 'new sample') + ', ' + plural(res.samples_updated, 'updated sample') + '; ' +
            res.assays.map(function (a) { return a.name + ' (' + (a.action === 'unchanged' ? 'already imported' : plural(a.wells_assigned, 'well') + ' laid out') + ')'; }).join(', ') + '.')));
        if ((res.warnings || []).length) result.appendChild(warningsCallout('Imported with ' + plural(res.warnings.length, 'warning'), res.warnings));
        toast(res.changed ? 'Workbook imported' : 'This workbook was already imported');
        onImported(res);
      } catch (e) {
        importFailed(result, 'The workbook could not be imported', e);
      } finally {
        setBusy(submit, false);
      }
    });

    return h('div', { class: 'import-box' },
      h('div', { class: 'import-title' }, icon('upload'), 'Import an assay workbook'),
      h('p', { class: 'hint', style: { marginTop: '0' } }, 'An Excel-to-SBOL Assay workbook says which sample design sat in each well. BOB reads each design from SynBioHub into its parts, names the signals from the workbook\u2019s signal sheet, and lays out each plate. Check first to see all of it before anything is saved.'),
      h('div', { class: 'form-grid' },
        dropField('Workbook', book),
        dropField('Plate-reader files', plates),
        field('Mapping', picker.select, { help: 'How to read the plate files.', cls: 'span-2' })),
      versionHint(study, 'Importing'),
      err,
      preview,
      h('div', { class: 'form-actions' }, check, submit),
      progress.el,
      result);
  }

  function importBox(study, ctx, onImported) {
    var name = h('input', { type: 'text', placeholder: 'e.g. Plate 1, 24 h kinetic', maxlength: '200' });
    var result = h('div', { style: { marginTop: '12px' } });
    var err = h('div', { class: 'field-error', role: 'alert', hidden: true });
    var picker = mappingPicker(study, ctx, function (e) { result.textContent = ''; result.appendChild(errorCallout(e)); });
    var nameTouched = false;
    name.addEventListener('input', function () { nameTouched = true; });
    var drop = fileDrop({
      accept: PLATE_FILE_TYPES, label: 'Plate-reader file', prompt: PLATE_FILE_PROMPT, sub: 'The original file is stored unchanged.',
      onFiles: function (fs) {
        if (!fs[0]) return;
        picker.fit(fs[0].name);
        if (!nameTouched || !name.value.trim()) {
          name.value = fs[0].name.replace(/\.[^.]+$/, '');
          nameTouched = false;
        }
      }
    });
    var progress = uploadProgress();
    var submit = button('Import', { cls: 'btn-accent', icon: 'upload' });

    submit.addEventListener('click', async function () {
      result.textContent = '';
      formError(err, null);
      var file = drop.files()[0];
      var n = name.value.trim();
      if (!file) { formError(err, 'Choose the plate-reader file to import.'); return; }
      var wrong = picker.mismatch(file.name);
      if (wrong) { formError(err, wrong); return; }
      if (!n) { formError(err, 'Give the assay a name.'); name.focus(); return; }
      if (!picker.select.value) { formError(err, 'Pick the mapping that describes your instrument.'); return; }
      var fd = new FormData();
      fd.append('name', n);
      fd.append('mapping_key', picker.select.value);
      fd.append('file', file, file.name);
      setBusy(submit, true, 'Importing…');
      try {
        var assay = await progress.send('/api/studies/' + study.id + '/assays', fd, file.name, 'Reading the file with the mapping…');
        var warn = assay.warnings || [];
        result.appendChild(callout('ok', 'Imported ' + assay.name,
          h('div', null, plural((assay.signals || []).length, 'signal') + ' across ' + plural((assay.positions || []).length, 'well') + '. Next, assign wells to samples in the plate layout.'),
          h('a', { class: 'btn btn-sm btn-accent', href: '#/assay/' + assay.id, style: { marginTop: '8px' } }, 'Open assay', icon('chevronRight'))));
        if (warn.length) result.appendChild(warningsCallout('The file was read with ' + plural(warn.length, 'warning'), warn));
        toast('Assay imported');
        drop.clear();
        name.value = '';
        nameTouched = false;
        onImported(assay);
      } catch (e) {
        importFailed(result, 'The file could not be imported', e);
      } finally {
        setBusy(submit, false);
      }
    });

    return h('div', { class: 'import-box' },
      h('div', { class: 'import-title' }, icon('upload'), 'Import plate-reader file'),
      h('div', { class: 'form-grid' },
        field('Assay name', name),
        field('Mapping', picker.select, { help: 'How to read the file. A mapping describes one instrument export format. See the Mappings tab for the full list.' }),
        h('div', { class: 'form-row span-2' }, drop.el)),
      versionHint(study, 'Importing'),
      err,
      h('div', { class: 'form-actions' }, submit),
      progress.el,
      result);
  }

  /* ===================================================================
     Assay view: run details, plate layout, plot, mean expression
     =================================================================== */

  async function viewAssay(view, ctx, assayId, versionParam) {
    var version = versionParam ? parseInt(versionParam, 10) : null;
    var q = version ? '?version=' + version : '';
    view.appendChild(skeleton(3));
    var assay;
    try {
      assay = await api('GET', '/api/assays/' + assayId + q);
    } catch (e) {
      if (e.status === 404) { if (ctx.alive()) notFoundPage(view, 'Assay', version ? 'This assay is not part of version ' + version + ' of its study.' : null); return; }
      if (e.status === 410 && e.detail && e.detail.withdrawn) { if (ctx.alive()) withdrawnPage(view, e.detail.withdrawn); return; }
      throw e;
    }
    if (!ctx.alive()) return;
    var results = await Promise.all([
      api('GET', '/api/studies/' + assay.study_id + q),
      api('GET', '/api/assays/' + assay.id + '/layout' + q),
      loadMappings().catch(function () { return []; })
    ]);
    if (!ctx.alive()) return;
    var study = results[0], layout = results[1], maps = results[2];
    adoptWorkspace(study.workspace_id);
    var lock = version ? versionReason(version) : writeLock(study.workspace_id);
    var studyHref = '#/study/' + study.id + (version ? '/v/' + version : '');
    view.textContent = '';
    view.appendChild(studyCrumbs(ctx, study, [{ label: study.title, href: studyHref }, version ? { label: 'Version ' + version, href: studyHref } : null, { label: assay.name }]));
    if (version) view.appendChild(versionNotice(study, version, 'This is the assay as published in version ' + version + ' of ' + study.latest_version + ' of its study. It never changes.', false));

    var mapping = maps.find(function (m) { return m.key === assay.mapping_key; });
    view.appendChild(pageHero('Assay', assay.name, [
      h('div', { class: 'page-meta' },
        badge(humanize(assay.modality || 'plate_reader'), 'badge-accent'),
        h('span', null, (mapping && mapping.emoji ? mapping.emoji + ' ' : '') + (assay.mapping_name || assay.mapping_key || '')),
        h('span', null, 'Imported ' + fmtDateTime(assay.created_at)))
    ], version ? null : [
      button('Delete', { cls: 'btn-sm btn-danger', icon: 'trash', locked: lock, onClick: function () { deleteAssay(assay, function () { location.hash = '#/study/' + study.id; }, study); } })
    ]));

    var meta = assay.run_metadata || {};
    var metaKeys = Object.keys(meta);
    var raw = assay.raw_file || {};
    var rawBtn = downloadButton('Download', raw.url || '/api/assays/' + assay.id + '/raw', raw.filename || 'raw-file');
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Instrument run', helpIcon('What the instrument wrote about the run, read by the mapping from the file header, and the raw file exactly as it was uploaded.')),
      warningsCallout('Read with ' + plural((assay.warnings || []).length, 'warning'), assay.warnings),
      metaKeys.length
        ? h('dl', { class: 'kv' }, metaKeys.map(function (k) { return [h('dt', null, humanize(k)), h('dd', null, String(meta[k]))]; }))
        : h('p', { class: 'muted', style: { fontSize: '0.86rem' } }, 'The file header carried no run metadata.'),
      h('div', { class: 'form-label', style: { marginTop: '16px' } }, 'Signals'),
      (assay.signals || []).length
        ? h('div', { class: 'signal-list' }, assay.signals.map(function (s) {
          var optics = s.optics ? Object.keys(s.optics).map(function (k) { return humanize(k) + ' ' + s.optics[k]; }).join(', ') : '';
          return h('div', { class: 'signal' },
            h('div', { class: 'signal-name' }, s.color ? h('span', { class: 'wb-color', style: { background: s.color } }) : null, s.name),
            s.description ? h('div', { class: 'signal-meta' }, s.description) : null,
            h('div', { class: 'signal-meta' }, humanize(s.kind) + (s.unit ? ', ' + s.unit : '') + (s.n_times ? ', ' + plural(s.n_times, 'time point') : '')),
            optics ? h('div', { class: 'signal-meta' }, optics) : null);
        }))
        : h('p', { class: 'muted' }, 'No signals were read.'),
      h('div', { class: 'form-label', style: { marginTop: '16px' } }, 'Raw file'),
      h('div', { class: 'file-box' },
        h('span', { class: 'row-glyph' }, icon('file')),
        h('div', { style: { flex: '1', minWidth: '0' } },
          h('div', { class: 'file-name' }, raw.filename || 'Unnamed file'),
          h('div', { class: 'file-meta' },
            raw.size !== undefined ? h('span', null, fmtBytes(raw.size)) : null,
            raw.sha256 ? h('span', null, 'SHA-256') : null,
            raw.sha256 ? h('span', { class: 'hash', title: raw.sha256 }, shortHash(raw.sha256)) : null,
            raw.sha256 ? copyButton(raw.sha256, 'SHA-256 checksum') : null)),
        rawBtn)));

    var samples = layout.samples || [];
    var styles = P.sampleStyles(samples);
    var sampleById = new Map(samples.map(function (s) { return [String(s.id), s]; }));
    var unknownStyle = { color: 'var(--control-tertiary)', dash: '', isControl: false, badge: '?' };
    var styleOf = function (id) { return styles.get(sampleById.has(String(id)) ? sampleById.get(String(id)).id : id) || unknownStyle; };
    var nameOf = function (id) { var s = sampleById.get(String(id)); return s ? s.name + ' (' + (s.sample_type || 'sample') + ')' : 'unknown sample'; };
    var positions = (layout.positions || []).map(function (p) { return p.position; });
    if (!positions.length) positions = assay.positions || [];
    var saved = new Map((layout.positions || []).map(function (p) { return [p.position, p.sample_id === undefined ? null : p.sample_id]; }));
    positions.forEach(function (p) { if (!saved.has(p)) saved.set(p, null); });
    var current = new Map(saved);
    var wellValues = null;
    var selection = new Set();

    var dirty = function () {
      var d = false;
      current.forEach(function (v, k) { if ((saved.get(k) || null) !== (v || null)) d = true; });
      return d;
    };
    state.leaveGuard = function () { return !lock && dirty(); };
    ctx.onCleanup(function () { state.leaveGuard = null; });

    var plateBox = h('div', { class: 'plate-wrap' });
    var hoverLine = h('span', null, lock ? 'Hover a well to see its sample.' : 'Click or drag to select wells. Shift-click selects a range.');
    var selLine = h('span');
    var sampleSel = h('select', { 'aria-label': 'Sample to assign' });
    var dirtyNote = h('span', { class: 'dirty-note', hidden: true }, 'Unsaved changes');
    var assignBtn = button('Assign', { cls: 'btn-sm btn-accent', icon: 'check' });
    var clearBtn = button('Clear', { cls: 'btn-sm', icon: 'x' });
    var discardBtn = button('Discard', { cls: 'btn-sm btn-quiet' });
    var saveBtn = button('Save layout', { cls: 'btn-sm btn-accent' });
    var legendBox = h('div', { class: 'plate-legend' });

    samples.forEach(function (s) {
      var st = styles.get(s.id);
      sampleSel.appendChild(h('option', { value: s.id }, (st && st.badge ? st.badge + '. ' : '') + s.name + (P.isControl(s.sample_type) ? ' (' + s.sample_type + ' control)' : '')));
    });

    var plate = P.plateMap(plateBox, {
      positions: positions,
      assignment: current,
      saved: saved,
      styleOf: styleOf,
      nameOf: nameOf,
      readOnly: !!lock,
      onSelect: function (sel) { selection = sel; syncTools(); },
      onHover: showHover
    });

    var hovered = null;
    function showHover(pos) {
      hovered = pos;
      if (!pos) { hoverLine.textContent = lock ? 'Hover a well to see its sample.' : 'Click or drag to select wells. Shift-click selects a range.'; return; }
      var sid = current.get(pos);
      var text = pos + ': ' + (sid ? nameOf(sid) : (positions.indexOf(pos) >= 0 ? 'no sample' : 'no data in this well'));
      if (wellValues && wellValues[pos] !== undefined) text += ', mean ' + P.fmt(wellValues[pos]);
      hoverLine.textContent = text;
    }

    function syncTools() {
      showHover(hovered);
      var n = selection.size;
      selLine.textContent = n ? plural(n, 'well') + ' selected' : '';
      var d = dirty();
      dirtyNote.hidden = !d;
      assignBtn.disabled = !n || !samples.length;
      clearBtn.disabled = !n;
      saveBtn.disabled = !d;
      discardBtn.disabled = !d;
      renderPlateLegend();
    }

    function renderPlateLegend() {
      legendBox.textContent = '';
      var counts = new Map();
      current.forEach(function (sid) { if (sid) counts.set(String(sid), (counts.get(String(sid)) || 0) + 1); });
      samples.forEach(function (s) {
        var c = counts.get(String(s.id)) || 0;
        legendBox.appendChild(h('span', null, P.swatch(styles.get(s.id)), (styles.get(s.id).badge ? styles.get(s.id).badge + '. ' : '') + s.name, h('span', { class: 'muted' }, '(' + c + ')')));
      });
    }

    assignBtn.addEventListener('click', function () {
      if (!selection.size || !sampleSel.value) return;
      var s = sampleById.get(String(sampleSel.value));
      selection.forEach(function (p) { current.set(p, s ? s.id : sampleSel.value); });
      plate.update({ assignment: current });
      plate.clearSelection();
      syncTools();
    });
    clearBtn.addEventListener('click', function () {
      selection.forEach(function (p) { current.set(p, null); });
      plate.update({ assignment: current });
      plate.clearSelection();
      syncTools();
    });
    discardBtn.addEventListener('click', function () {
      saved.forEach(function (v, k) { current.set(k, v); });
      plate.update({ assignment: current });
      syncTools();
    });
    saveBtn.addEventListener('click', async function () {
      var assignments = {};
      current.forEach(function (v, k) { assignments[k] = v || null; });
      setBusy(saveBtn, true, 'Saving…');
      try {
        var res = await api('PUT', '/api/assays/' + assay.id + '/layout', { assignments: assignments });
        if (!ctx.alive()) return;
        saved = new Map(((res && res.positions) || []).map(function (p) { return [p.position, p.sample_id === undefined ? null : p.sample_id]; }));
        if (!saved.size) saved = new Map(current);
        positions.forEach(function (p) { if (!saved.has(p)) saved.set(p, null); });
        saved.forEach(function (v, k) { current.set(k, v); });
        plate.update({ assignment: current, saved: saved });
        toast('Layout saved');
        if (study.visibility === 'public') { route(true); return; }
        if (typeof clearPlotAcknowledgement === 'function') clearPlotAcknowledgement();
        if (typeof syncPlotControls === 'function') syncPlotControls();
        refreshAnalysis();
        if (typeof refreshRateOptions === 'function') refreshRateOptions();
      } catch (e) {
        if (e.status !== 401) toast('The layout was not saved: ' + e.message, 'error');
      } finally {
        setBusy(saveBtn, false);
        syncTools();
      }
    });

    var plateCard = h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Plate layout', helpIcon('Assign each well to the sample it held. Drag across wells, Shift-click for a range, or ' + (IS_MAC ? 'Command-click' : 'Ctrl-click') + ' to add wells. Row letters and column numbers select a whole row or column. Wells assigned to medium or untransformed samples are the background controls.')),
        dirtyNote),
      samples.length ? null : callout('info', 'This study has no samples yet', h('div', null, 'Add samples to the study, then come back to assign them to wells. ', h('a', { href: '#/study/' + study.id }, 'Go to the study'))),
      lock ? h('div', { class: 'readonly-note' }, icon('lock'), 'Read only. ' + lock) : null,
      plateBox,
      h('div', { class: 'plate-status' }, hoverLine, selLine),
      lock ? null : h('div', { class: 'plate-tools' }, sampleSel, assignBtn, clearBtn, h('span', { style: { flex: '1' } }), discardBtn, saveBtn),
      lock ? null : versionHint(study),
      legendBox);
    view.appendChild(plateCard);
    syncTools();

    var signals = assay.signals || [];
    var absorbance = signals.filter(function (s) { return s.kind === 'absorbance'; });
    var fluor = signals.filter(function (s) { return s.kind === 'fluorescence'; });
    var reporter = fluor.find(function (s) { return /yfp|gfp/i.test(s.name); }) || fluor[0] || signals[0] || {};
    var defaults = {
      signal: reporter.name || '',
      correct: true,
      threshold: 2,
      dropBelow: false,
      normalizeBy: '',
      minOd: 0.05
    };
    var saveKey = 'bob.plot.' + assay.id;
    var settings = Object.assign({}, defaults, store(saveKey) || {});
    if (!signals.some(function (s) { return s.name === settings.signal; })) settings.signal = defaults.signal;
    if (settings.normalizeBy && !absorbance.some(function (s) { return s.name === settings.normalizeBy; })) settings.normalizeBy = '';

    var signalSel = selectEl(signals.map(function (s) { return { value: s.name, label: s.name + (s.unit ? ' (' + s.unit + ')' : '') }; }), settings.signal);
    var normSel = selectEl([{ value: '', label: 'None' }].concat(absorbance.map(function (s) { return { value: s.name, label: s.name }; })), settings.normalizeBy);
    var minOd = h('input', { type: 'number', min: '0', step: '0.01', value: String(settings.minOd) });
    var minOdRow = field('Min OD', minOd, { help: 'Time points where the OD is below this value are left out of the normalized signal. Dividing by a near-zero OD early in growth produces spikes.' });
    var threshold = h('input', { type: 'number', min: '0', step: '0.5', value: String(settings.threshold) });
    var thresholdRow = field('Threshold (SD)', threshold, { help: 'A corrected point counts as indistinguishable from background when it is less than this many standard deviations of the control wells at that time point.' });
    var corr = toggleSwitch('Background correction', settings.correct, { help: 'Subtracts the mean of the control wells you select below, at each time point. Only the selected wells are subtracted, and controls recorded in a different medium or supplement context are refused.' });
    var plotSampleSel = selectEl([], '');
    var plotCtrlSel = selectEl([], '');
    var plotNormCtrlSel = selectEl([], '');
    var plotAck = toggleSwitch('I checked the control compatibility', false,
      { help: 'Blanks hold no cells, so no host applies to them. Untransformed controls must additionally be the same host under the same conditions, which BOB cannot establish from the identifiers.' });
    var plotSampleRow = field('Sample', plotSampleSel, { help: 'The group to plot. Correction needs controls compatible with every group shown, so analyse one compatible group at a time on a mixed plate.' });
    var plotCtrlRow = field('Background control', plotCtrlSel, { help: 'The control group subtracted from the selected signal. Medium-only wells for absorbance, untransformed cells for a reporter; a medium well is not a substitute for untransformed cells.' });
    var plotNormCtrlRow = field('Normalization control', plotNormCtrlSel, { help: 'Medium-only wells subtracted from the normalizing absorbance channel. It is validated on its own.' });

    function controlTypeFor(name) {
      var sig = signals.find(function (s) { return s.name === name; }) || {};
      return sig.kind === 'absorbance' ? 'medium' : (sig.kind === 'fluorescence' ? 'untransformed' : '');
    }
    function setOptions(sel, opts) {
      var keep = sel.value;
      sel.textContent = '';
      opts.forEach(function (o) {
        var opt = h('option', { value: o.value }, o.label);
        if (String(o.value) === String(keep)) opt.selected = true;
        sel.appendChild(opt);
      });
      if (!opts.some(function (o) { return String(o.value) === String(keep); })) {
        sel.value = opts.length === 1 ? opts[0].value : '';
      }
      return sel.value;
    }
    var drop = toggleSwitch('Hide points below background', settings.dropBelow, { help: 'Leaves out corrected points that fall within the threshold of background, instead of plotting them near zero.' });

    function syncPlotControls() {
      minOdRow.hidden = !normSel.value;
      threshold.disabled = !corr.input.checked;
      drop.input.disabled = !corr.input.checked;
      if (normSel.value && normSel.value === signalSel.value) normSel.value = '';
      minOdRow.hidden = !normSel.value;
      Array.prototype.forEach.call(normSel.options, function (o) { o.disabled = !!o.value && o.value === signalSel.value; });

      var opts = function (list) {
        return list.filter(function (s) { return wellsOf(s.id).length; })
                   .map(function (s) { return { value: s.id, label: s.name + ' (' + wellsOf(s.id).length + ' wells)' }; });
      };
      var on = corr.input.checked;
      // corrected mode needs one compatible group, so it asks for a choice rather than offering
      // every group and then refusing; raw mode can still plot the whole plate
      var first = on ? { value: '', label: 'Choose sample\u2026' } : { value: '', label: 'Every group' };
      setOptions(plotSampleSel, [first].concat(opts(byType('sample'))));
      var want = controlTypeFor(signalSel.value);
      setOptions(plotCtrlSel, [{ value: '', label: 'Choose background control\u2026' }]
        .concat(opts(byType(want))));
      setOptions(plotNormCtrlSel, [{ value: '', label: 'Choose normalization control\u2026' }]
        .concat(opts(byType('medium'))));
      plotCtrlRow.hidden = !on;
      plotNormCtrlRow.hidden = !(on && normSel.value);
      plotAck.row.hidden = !on;
      plotCtrlSel.disabled = !on;
      plotNormCtrlSel.disabled = !on;
      plotAck.input.disabled = !on;
    }

    var chartBox = h('div');
    var chartWrap = h('div', { class: 'chart', 'aria-busy': 'true' }, loadingLine('Loading the time series…'));
    var busyPill = h('div', { class: 'chart-busy', hidden: true }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Updating');
    var chartNotes = h('div');
    var chart = null;

    var plotCard = h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Time series', helpIcon('Each line is the mean of the wells assigned to one sample, and the band is plus or minus one standard deviation. Controls are dashed. Hover the chart to read values; select a legend entry to hide or show a group.'))),
      signals.length
        ? [h('div', { class: 'plot-controls' },
          field('Signal', signalSel),
          field('Normalize by', normSel, { help: 'Divides the signal by an absorbance reading such as OD600 at each time point, to express it per unit of cell density.' }),
          minOdRow),
        h('div', { class: 'plot-controls' },
          plotSampleRow,
          corr.row,
          thresholdRow,
          drop.row),
        h('div', { class: 'plot-controls' },
          plotCtrlRow,
          plotNormCtrlRow,
          h('div', { class: 'form-row' }, plotAck.row))]
        : null,
      h('div', { style: { position: 'relative' } }, busyPill, chartBox),
      chartNotes);
    chartBox.appendChild(chartWrap);
    view.appendChild(plotCard);

    var meanTable = h('div');
    var meanChart = h('div');
    var meanSub = cardCount();
    var meanCard = h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Mean signal over run', helpIcon('For each well, the selected signal is averaged over the whole run; the group value is the mean and standard deviation of its wells, and the standard deviation is unknown for a single well. The same correction and normalization settings apply. This summarises whichever signal is selected, raw or normalized, and establishes nothing about gene expression.'), meanSub),
      h('div', { class: 'split' }, meanTable, meanChart));
    view.appendChild(meanCard);
    meanTable.appendChild(loadingLine());

    var byType = function (kind) { return samples.filter(function (s) { return s.sample_type === kind; }); };
    // read the SAVED assignments, never the pending ones, so unsaved edits cannot enter a fit
    var wellsOf = function (sid) {
      var out = [];
      saved.forEach(function (v, k) { if (v === sid) out.push(k); });
      return out.sort();
    };
    var rateDefaults = {
      sample: (byType('sample')[0] || {}).id || '',
      mediumControl: (byType('medium')[0] || {}).id || '',
      hostControl: (byType('untransformed')[0] || {}).id || '',
      reporter: reporter.name || '',
      biomass: (absorbance[0] || {}).name || '',
      delta: 1, lam: '', gamma: 0
    };
    var rateKey = 'bob.rates.' + assay.id;
    var rset = Object.assign({}, rateDefaults, store(rateKey) || {});

    var sampleOpts = function (list) { return list.map(function (s) { return { value: s.id, label: s.name + ' (' + wellsOf(s.id).length + ' wells)' }; }); };
    var rSample = selectEl(sampleOpts(byType('sample')), rset.sample);
    var rMedium = selectEl(sampleOpts(byType('medium')), rset.mediumControl);
    var rHost = selectEl(sampleOpts(byType('untransformed')), rset.hostControl);
    var rReporter = selectEl(fluor.map(function (s) { return { value: s.name, label: s.name }; }), rset.reporter);
    var rBiomass = selectEl(absorbance.map(function (s) { return { value: s.name, label: s.name }; }), rset.biomass);
    var rDelta = h('input', { type: 'number', min: '0.05', step: '0.25', value: String(rset.delta) });
    var rLam = h('input', { type: 'number', min: '0', step: 'any', value: String(rset.lam), placeholder: 'Automatic' });
    var rGamma = h('input', { type: 'number', min: '0', step: '0.05', value: String(rset.gamma) });
    var rAck = toggleSwitch('I checked the control compatibility', false,
      { help: 'Blanks must match the sample\u2019s medium and conditions; they contain no cells, so no host applies to them. Untransformed controls must additionally be the same host under the same conditions. BOB records no parent-host mapping, so it cannot establish that from the identifiers.' });
    var presets = {};
    var presetSel = selectEl([], '');
    var rRun = button('Fit rates', { cls: 'btn-sm btn-accent', icon: 'chart' });
    var rDownload = button('Download results', { cls: 'btn-sm btn-quiet', icon: 'download' });
    rDownload.disabled = true;
    var rFigure = button('Download figure', { cls: 'btn-sm btn-quiet', icon: 'download',
      title: 'The figure as SVG, or the table as CSV' });
    rFigure.disabled = true;

    var growthWrap = h('div', { class: 'chart' });
    var prodWrap = h('div', { class: 'chart' });
    var fitBioWrap = h('div', { class: 'chart' });
    var fitRepWrap = h('div', { class: 'chart' });
    var rateNotes = h('div');
    var rateState = h('div');
    var growthChart = null, prodChart = null, fitBioChart = null, fitRepChart = null;
    var lastRates = null, lastSeries = null, rateSeq = 0;

    var SAMPLE_HELP = {
      fit: 'The wells to fit. They must all belong to one sample; their readings are averaged before fitting, so this is a fit to mean observations rather than a mean of per-well rates.',
      plot: 'The wells to plot. They must all belong to one sample; their readings are averaged at each time point, so this is a figure of mean observations.'
    };
    var sampleRow = field('Sample', rSample, { help: SAMPLE_HELP.fit });
    var sampleHelp = sampleRow.querySelector('.help');

    var panelA = h('div', { class: 'card-title small' }, 'Growth rate');
    var panelB = h('div', { class: 'card-title small' }, 'Reporter production');
    var panelC = h('div', { class: 'card-title small' }, 'Biomass: measured and fitted');
    var panelD = h('div', { class: 'card-title small' }, 'Reporter: measured and fitted');
    var boxB = h('div', null, panelB, prodWrap);
    var boxC = h('div', null, panelC, fitBioWrap);
    var boxD = h('div', null, panelD, fitRepWrap);
    var rowTwo = h('div', { class: 'split' }, boxC, boxD);
    var chartsBox = h('div', { hidden: true },
      h('div', { class: 'split' }, h('div', null, panelA, growthWrap), boxB),
      rowTwo);

    var PANEL_TITLES = {
      growth_curve: 'Biomass over time',
      reporter_trajectory: 'Reporter over time, corrected and raw',
      reporter_per_biomass: 'Reporter per biomass',
      mean_over_run: 'Mean over run',
      rate_profiles: 'Growth rate'
    };
    function applyPresetHeadings(preset) {
      panelA.textContent = PANEL_TITLES[preset] || 'Figure';
      var rates = preset === 'rate_profiles';
      boxB.hidden = !rates;
      rowTwo.hidden = !rates;
      rAdvanced.hidden = !rates;
    }

    // Hoisted so preset switching can hide it. The inputs stay in the DOM, so their values
    // survive a switch away and back.
    var rAdvanced = h('details', { class: 'plot-advanced' },
      h('summary', null, 'Advanced'),
      h('div', { class: 'plot-controls' },
        field('\u0394 (h)', rDelta, { help: 'Width and spacing of the Gaussian basis, in hours. It sets the sharpest change that can be reconstructed and must exceed the sampling interval.' }),
        field('\u03bb', rLam, { help: 'Tikhonov regularisation. Leave blank to select it automatically; growth and production are selected independently and both are reported.' }),
        field('\u03b3 (1/h)', rGamma, { help: 'Reporter degradation rate. Zero assumes a stable reporter, which is the published default.' })));

    var ratesHelp = helpIcon('Each workflow runs its own named analysis against the sample and controls you select.');
    var ratesTitle = h('div', { class: 'card-title' }, 'Figure', ratesHelp);
    var ratesCard = h('section', { class: 'card' },
      h('div', { class: 'card-head' }, ratesTitle),
      h('div', { class: 'plot-controls' },
        sampleRow,
        field('Reporter', rReporter),
        field('Biomass', rBiomass)),
      h('div', { class: 'plot-controls' },
        field('Biomass control', rMedium, { help: 'Medium-only wells with no cells. Their mean is subtracted from the biomass channel.' }),
        field('Reporter control', rHost, { help: 'Untransformed cells carrying no reporter. Their mean is subtracted from the reporter channel; a medium well is not a substitute.' })),
      rAdvanced,
      h('div', { class: 'plot-controls' }, rAck.row),
      h('div', { class: 'row gap action-row' }, rRun, rDownload, rFigure),
      rateState, rateNotes, chartsBox);
    view.appendChild(ratesCard);

    var RATE_STYLES = {
      measured: { color: 'var(--series-1)', dash: '', isControl: false, badge: 'm' },
      fitted: { color: 'var(--series-2)', dash: '4 3', isControl: false, badge: 'f' },
      rate: { color: 'var(--series-3)', dash: '', isControl: false, badge: 'r' }
    };
    function rateSeries(label, times, values, style) {
      return { key: label, label: label, times: times || [], mean: values || [], sd: [], n: [], nLabel: '', style: style };
    }
    function drawChart(holder, existing, opts) {
      if (existing) { existing.update(opts); return existing; }
      var c = P.lineChart(holder, opts);
      ctx.onCleanup(function () { if (c) c.destroy(); });
      return c;
    }

    function rateReady() {
      if (!rSample.value || !wellsOf(rSample.value).length) return false;
      var needs = presetNeeds(presetSel && presetSel.value);
      if (!needs.length) needs = ['reporter_signal', 'biomass_signal', 'biomass_control_id', 'reporter_control_id'];
      var have = {
        reporter_signal: !!rReporter.value, biomass_signal: !!rBiomass.value,
        biomass_control_id: !!rMedium.value && !!wellsOf(rMedium.value).length,
        reporter_control_id: !!rHost.value && !!wellsOf(rHost.value).length
      };
      for (var i = 0; i < needs.length; i++) {
        if (needs[i] !== 'sample_id' && have[needs[i]] === false) return false;
      }
      return true;
    }
    function invalidateRates(reason) {
      lastRates = null;
      lastSeries = null;
      lastFigure = null;
      rDownload.disabled = true;
      rFigure.disabled = true;
      chartsBox.hidden = true;
      rateNotes.textContent = '';
      rateSeq += 1;
      rateState.textContent = '';
      if (reason) rateState.appendChild(h('p', { class: 'chart-note' }, reason));
    }
    function syncRateControls() {
      var ok = rateReady();
      rRun.disabled = !ok;
      if (!ok && !rateState.textContent) {
        rateState.textContent = '';
        rateState.appendChild(h('p', { class: 'chart-note' }, 'Assign wells to a sample, a medium control and an untransformed control, then save the layout.'));
      }
    }
    function refreshRateOptions() {
      [[rSample, byType('sample')], [rMedium, byType('medium')], [rHost, byType('untransformed')]].forEach(function (pair) {
        var sel = pair[0], keep = sel.value;
        sel.textContent = '';
        sampleOpts(pair[1]).forEach(function (o) { sel.appendChild(h('option', { value: o.value }, o.label)); });
        sel.value = keep;
      });
      var cleared = resetAcknowledgement();
      invalidateRates(cleared
        ? 'The layout changed, so the compatibility check was cleared. Check it again for the saved wells, then fit.'
        : 'The layout changed. Fit again to refresh these profiles.');
      syncRateControls();
    }
    // a confirmation about one set of wells cannot authorise a different one, so changing the
    // biological context clears it; purely numerical parameters leave it standing
    var NUMERIC_RATE_INPUTS = [rDelta, rLam, rGamma];
    function resetAcknowledgement() {
      if (!rAck.input.checked) return false;
      rAck.input.checked = false;
      return true;
    }
    ratesCard.addEventListener('change', function (e) {
      var msg;
      if (e.target === rAck.input) {
        msg = 'The control-compatibility check changed since the last fit. Fit again.';
      } else if (NUMERIC_RATE_INPUTS.indexOf(e.target) !== -1) {
        msg = 'Fitting parameters changed since the last fit. Fit again.';
      } else {
        var cleared = resetAcknowledgement();
        msg = cleared
          ? 'The sample or controls changed, so the compatibility check was cleared. Check it again for the new wells, then fit.'
          : 'Inputs changed since the last fit. Fit again.';
      }
      invalidateRates(msg);
      syncRateControls();
    });

    async function runRates() {
      var seq = ++rateSeq;
      rateNotes.textContent = '';
      rateState.textContent = '';
      chartsBox.hidden = true;
      rDownload.disabled = true;
      rFigure.disabled = true;
      lastRates = null;
      lastSeries = null;
      var qs = new URLSearchParams({
        signal: rReporter.value, biomass_signal: rBiomass.value,
        wells: wellsOf(rSample.value).join(','),
        biomass_controls: wellsOf(rMedium.value).join(','),
        reporter_controls: wellsOf(rHost.value).join(','),
        delta: String(rDelta.value || 1), gamma: String(rGamma.value || 0),
        context_acknowledged: rAck.input.checked ? 'true' : 'false'
      });
      if (String(rLam.value).trim() !== '') qs.set('lam', String(rLam.value));
      if (version) qs.set('version', String(version));
      store(rateKey, { sample: rSample.value, mediumControl: rMedium.value, hostControl: rHost.value,
                       reporter: rReporter.value, biomass: rBiomass.value,
                       delta: Number(rDelta.value), lam: rLam.value, gamma: Number(rGamma.value) });
      try {
        var d = await api('GET', '/api/assays/' + assay.id + '/rates?' + qs.toString());
        if (seq !== rateSeq || !ctx.alive()) return;
        lastRates = d;
        rDownload.disabled = false;
        rFigure.disabled = false;
        chartsBox.hidden = false;
        var obs = d.observed || {};
        growthChart = drawChart(growthWrap, growthChart, {
          groups: [rateSeries('Growth rate', d.growth.times_h, d.growth.rate, RATE_STYLES.rate)],
          xLabel: 'Time (h)', yLabel: 'Growth rate (' + d.growth.unit + ')' });
        prodChart = drawChart(prodWrap, prodChart, {
          groups: [rateSeries('Reporter production proxy', d.production.times_h, d.production.rate, RATE_STYLES.rate)],
          xLabel: 'Time (h)', yLabel: 'Reporter production (' + d.production.unit + ')' });
        fitBioChart = drawChart(fitBioWrap, fitBioChart, {
          groups: [rateSeries('Measured biomass', obs.times_h, obs.biomass, RATE_STYLES.measured),
                   rateSeries('Fitted biomass', d.growth.times_h, d.growth.fitted, RATE_STYLES.fitted)],
          xLabel: 'Time (h)', yLabel: 'Biomass, background corrected' + unitSuffix((d.source || {}).biomass_unit) });
        fitRepChart = drawChart(fitRepWrap, fitRepChart, {
          groups: [rateSeries('Measured reporter', obs.times_h, obs.reporter, RATE_STYLES.measured),
                   rateSeries('Fitted reporter', d.production.times_h, d.production.fitted, RATE_STYLES.fitted)],
          xLabel: 'Time (h)', yLabel: 'Reporter, background corrected' + unitSuffix((d.source || {}).reporter_unit) });
        var pv = d.provenance || {};
        rateNotes.appendChild(h('p', { class: 'chart-note' },
          '\u0394=' + d.parameters.delta_h + ' h, \u03b3=' + d.parameters.gamma_per_h + '/h. ' +
          '\u03bb growth ' + d.growth.lambda.toPrecision(3) + ' (' + (d.growth.diagnostics.lambda_selection_rule || '') + '), ' +
          '\u03bb production ' + d.production.lambda.toPrecision(3) + ' (' + (d.production.diagnostics.lambda_selection_rule || '') + '). ' +
          'Biomass background ' + (pv.biomass_control_wells || []).join(', ') +
          '; reporter background ' + (pv.reporter_control_wells || []).join(', ') + '.' +
          (pv.snapshot_version ? ' Frozen version ' + pv.snapshot_version + '.' : '')));
        if (d.warnings && d.warnings.length) {
          rateNotes.appendChild(h('details', { class: 'plot-advanced' },
            h('summary', null, plural(d.warnings.length, 'caveat') + ' on these profiles'),
            h('ul', { class: 'chart-note' }, d.warnings.map(function (w) { return h('li', null, String(w)); }))));
        }
        if (!d.growth.converged || !d.production.converged) {
          rateNotes.appendChild(callout('error', 'The fit did not converge',
            h('div', null, 'These profiles are not usable. Try a larger \u0394, or leave \u03bb automatic.')));
        }
      } catch (e) {
        if (seq !== rateSeq || !ctx.alive()) return;
        invalidateRates('');
        rateNotes.appendChild(callout('warn', 'Cannot fit these rates', h('div', { style: { whiteSpace: 'pre-wrap' } }, e.message)));
      } finally {
        syncRateControls();
      }
    }
    async function showSeriesFigure(preset) {
      var seq = ++rateSeq;
      var needs = presetNeeds(preset);
      var qs = new URLSearchParams({
        preset: preset,
        wells: wellsOf(rSample.value).join(','),
        context_acknowledged: rAck.input.checked ? 'true' : 'false'
      });
      if (needs.indexOf('reporter_signal') !== -1) qs.set('signal', rReporter.value);
      if (needs.indexOf('biomass_signal') !== -1) qs.set('biomass_signal', rBiomass.value);
      if (needs.indexOf('biomass_control_id') !== -1) qs.set('biomass_controls', wellsOf(rMedium.value).join(','));
      if (needs.indexOf('reporter_control_id') !== -1) qs.set('reporter_controls', wellsOf(rHost.value).join(','));
      if (version) qs.set('version', String(version));

      var d = await api('GET', '/api/assays/' + assay.id + '/preset-series?' + qs.toString());
      if (seq !== rateSeq || !ctx.alive()) return null;
      lastSeries = d;
      rDownload.disabled = false;
      rFigure.disabled = false;

      var groups = [], preview = [], yLabel = '';
      if (preset === 'growth_curve') {
        yLabel = 'Biomass' + (d.biomass_unit ? ' (' + d.biomass_unit + ')' : '');
        groups.push(rateSeries('Biomass, corrected', d.times_h, d.biomass, RATE_STYLES.rate));
      } else if (preset === 'reporter_trajectory') {
        yLabel = 'Reporter' + (d.reporter_unit ? ' (' + d.reporter_unit + ')' : '');
        groups.push(rateSeries('Corrected', d.times_h, d.reporter, RATE_STYLES.rate));
        groups.push(rateSeries('Raw, not corrected', d.times_h, d.reporter_raw, RATE_STYLES.measured));
      } else if (preset === 'reporter_per_biomass') {
        yLabel = d.ratio_unit || 'Reporter per biomass';
        groups.push(rateSeries('Reporter per biomass', d.times_h, d.ratio, RATE_STYLES.rate));
      } else if (preset === 'mean_over_run') {
        growthWrap.textContent = '';
        growthWrap.appendChild(h('table', { class: 'data' },
          h('thead', null, h('tr', null, h('th', null, 'Sample'), h('th', null, 'Mean'), h('th', null, 'Unit'), h('th', null, 'Points'))),
          h('tbody', null, h('tr', null,
            h('td', null, (samples.find(function (s) { return s.id === rSample.value; }) || {}).name || ''),
            h('td', null, d.mean == null ? '' : Number(d.mean).toPrecision(4)),
            h('td', null, d.mean_unit || ''),
            h('td', null, String(d.n_points))))));
        growthChart = null;
        // This preset has no time series. Drop the reserved chart height rather than leave an
        // empty region, and do not synthesise a two-point line that was never measured.
        growthWrap.classList.add('is-table');
        preview = [];
      }
      if (groups.length) {
        growthWrap.classList.remove('is-table');
        growthChart = drawChart(growthWrap, growthChart, { groups: groups, xLabel: 'Time (h)', yLabel: yLabel });
        preview = groups.slice(0, 2).map(function (g) { return downsample(g.times, g.mean, g.label); });
      }
      prodWrap.textContent = ''; fitBioWrap.textContent = ''; fitRepWrap.textContent = '';
      prodChart = fitBioChart = fitRepChart = null;
      chartsBox.hidden = false;
      applyPresetHeadings(preset);
      var pv = d.provenance || {};
      rateNotes.appendChild(h('p', { class: 'chart-note' },
        'Corrected against ' + (pv.biomass_control_wells || []).concat(pv.reporter_control_wells || []).join(', ') +
        ' (' + (pv.controls_required || []).join(' and ') + ').'));
      if (d.warnings && d.warnings.length) {
        rateNotes.appendChild(h('details', { class: 'plot-advanced' },
          h('summary', null, plural(d.warnings.length, 'caveat') + ' on this figure'),
          h('ul', { class: 'chart-note' }, d.warnings.map(function (w) { return h('li', null, String(w)); }))));
      }
      return { preset: preset, preview: preview,
               method: d.analysis_method || (presets[preset] || {}).method || '',
               method_version: d.analysis_method_version || (presets[preset] || {}).method_version || '1',
               source_fingerprint: d.source_fingerprint || '',
               snapshot_version: d.snapshot_version || null };
    }

    async function showFigure() {
      var preset = presetSel.value || 'rate_profiles';
      lastFigure = null;
      rateNotes.textContent = '';
      rateState.textContent = '';
      chartsBox.hidden = true;
      rDownload.disabled = true;
      rFigure.disabled = true;
      lastSeries = null;
      rRun.disabled = true;
      var restore = rRun.textContent;
      rRun.textContent = 'Working\u2026';
      try {
        if (preset === 'rate_profiles') {
          await runRates();
          if (lastRates) {
            lastFigure = { preset: preset, method: lastRates.method, method_version: lastRates.method_version,
                           source_fingerprint: lastRates.source_fingerprint || '',
                           snapshot_version: (lastRates.provenance || {}).snapshot_version,
                           preview: [downsample(lastRates.growth.times_h, lastRates.growth.rate, 'Growth rate'),
                                     downsample(lastRates.production.times_h, lastRates.production.rate, 'Production')] };
          }
        } else {
          lastFigure = await showSeriesFigure(preset);
        }
      } catch (e) {
        if (e.status !== 401) rateNotes.appendChild(callout('warn', 'Could not show this figure',
          h('div', { style: { whiteSpace: 'pre-wrap' } }, e.message)));
      } finally {
        rRun.disabled = false;
        rRun.textContent = restore === 'Working\u2026' ? 'Show figure' : restore;
        syncRateControls();
      }
    }
    rRun.addEventListener('click', showFigure);
    rDownload.addEventListener('click', function () {
      // rates keep their existing shape; the other workflows download the result they displayed
      var payload = lastRates || lastSeries;
      if (!payload) return;
      var stem = lastRates ? 'rates' : (presetSel.value || 'result');
      var blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = stem + '-' + assay.id + (version ? '-v' + version : '') + '.json';
      a.click();
      URL.revokeObjectURL(a.href);
    });
    // a chart element's styles come from the stylesheet, so a standalone file has to carry the
    // resolved values with it
    var SVG_PROPS = ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray',
      'stroke-linecap', 'stroke-linejoin', 'opacity', 'font-family', 'font-size', 'font-weight',
      'text-anchor', 'dominant-baseline', 'letter-spacing'];

    function unitSuffix(unit) {
      return unit ? ' (' + unit + ')' : '';
    }

    var SVGNS = 'http://www.w3.org/2000/svg';

    function svgEl(tag, attrs, text) {
      var node = document.createElementNS(SVGNS, tag);
      Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, String(attrs[k])); });
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function inlineStyles(source, clone) {
      var from = source.querySelectorAll('*');
      var to = clone.querySelectorAll('*');
      for (var i = 0; i < from.length && i < to.length; i++) {
        var cs = window.getComputedStyle(from[i]);
        to[i].setAttribute('style', SVG_PROPS.map(function (prop) {
          return prop + ':' + cs.getPropertyValue(prop);
        }).join(';'));
      }
      return clone;
    }

    function isPaint(value) {
      // "none" is a value, not an absence, so a truthiness test picks it up and hides the swatch
      if (!value) return false;
      var v = String(value).trim().toLowerCase();
      if (v === 'none' || v === 'transparent' || v === 'currentcolor') return false;
      var alpha = v.match(/^rgba\([^)]*,\s*([\d.]+)\s*\)$/);
      return !(alpha && Number(alpha[1]) === 0);
    }

    function paintOf(entry) {
      var nodes = entry.querySelectorAll('svg *');
      for (var i = 0; i < nodes.length; i++) {
        var cs = window.getComputedStyle(nodes[i]);
        var stroke = cs.getPropertyValue('stroke');
        if (isPaint(stroke)) return stroke;
        var fill = cs.getPropertyValue('fill');
        if (isPaint(fill)) return fill;
      }
      return '#1d1d1f';
    }

    // the legend lives in HTML beside the chart, so a standalone file has to redraw it
    function panelGroup(chartSvg, title, legendEl) {
      var box = chartSvg.getBoundingClientRect();
      var w = Math.max(320, Math.round(box.width) || 640);
      var chartH = Math.max(160, Math.round(box.height) || 360);
      // a series switched off in the legend is not in the chart either, so it is not in the file
      var entries = legendEl ? Array.prototype.filter.call(legendEl.children, function (e) {
        return e.getAttribute('aria-pressed') !== 'false';
      }) : [];
      var headH = title ? 28 : 0;
      var rowH = 18;
      var g = svgEl('g', {});
      if (title) {
        g.appendChild(svgEl('text', { x: 4, y: 18, style: 'font-family:system-ui,sans-serif;font-size:14px;font-weight:600;fill:#1d1d1f' }, title));
      }
      var inner = svgEl('g', { transform: 'translate(0,' + headH + ')' });
      var clone = inlineStyles(chartSvg, chartSvg.cloneNode(true));
      clone.setAttribute('width', String(w));
      clone.setAttribute('height', String(chartH));
      inner.appendChild(clone);
      g.appendChild(inner);
      entries.forEach(function (entry, i) {
        var y = headH + chartH + 8 + i * rowH;
        var key = entry.querySelector('svg');
        if (key) {
          // carry the key itself, so its colour, its band and a control's dashes all survive
          var kg = svgEl('g', { transform: 'translate(4,' + (y - 9) + ')' });
          var kc = inlineStyles(key, key.cloneNode(true));
          kc.setAttribute('width', '18');
          kc.setAttribute('height', '10');
          if (!kc.getAttribute('viewBox')) kc.setAttribute('viewBox', '0 0 18 10');
          kc.removeAttribute('class');
          kg.appendChild(kc);
          g.appendChild(kg);
        } else {
          g.appendChild(svgEl('rect', { x: 4, y: y - 8, width: 16, height: 4, fill: paintOf(entry) }));
        }
        g.appendChild(svgEl('text', { x: 26, y: y, style: 'font-family:system-ui,sans-serif;font-size:12px;fill:#1d1d1f' },
                            (entry.textContent || '').trim()));
      });
      return { g: g, width: w, height: headH + chartH + entries.length * rowH + 8 };
    }

    // one file, because a browser blocks a burst of automatic downloads and the user should not
    // have to loosen that
    function standaloneSvg(panels, documentTitle) {
      var gap = 18;
      var width = 0, height = 0;
      panels.forEach(function (p) { width = Math.max(width, p.width); height += p.height + gap; });
      height = Math.max(0, height - gap);
      var out = svgEl('svg', { xmlns: SVGNS, width: width, height: height,
                               viewBox: '0 0 ' + width + ' ' + height });
      out.appendChild(svgEl('title', {}, documentTitle || 'BOB figure'));
      out.appendChild(svgEl('rect', { x: 0, y: 0, width: width, height: height, fill: '#ffffff' }));
      var y = 0;
      panels.forEach(function (p) {
        p.g.setAttribute('transform', 'translate(0,' + y + ')');
        out.appendChild(p.g);
        y += p.height + gap;
      });
      return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(out);
    }

    function tableCsv(table) {
      var cell = function (el) { return '"' + String(el.textContent).replace(/"/g, '""') + '"'; };
      return Array.prototype.map.call(table.querySelectorAll('tr'), function (tr) {
        return Array.prototype.map.call(tr.children, cell).join(',');
      }).join('\n') + '\n';
    }

    function saveBlob(text, type, name) {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([text], { type: type }));
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    }

    rFigure.addEventListener('click', function () {
      if (!lastRates && !lastSeries) return;
      var preset = lastRates ? 'rate_profiles' : (presetSel.value || 'figure');
      var stem = preset + '-' + assay.id + (version ? '-v' + version : '');
      var wraps = [[growthWrap, panelA], [prodWrap, panelB], [fitBioWrap, panelC], [fitRepWrap, panelD]];
      var blocks = [];
      var wrote = 0;
      wraps.forEach(function (pair) {
        // a hidden panel holds whatever the previous workflow drew, so it is not exported
        if (pair[0].hidden || pair[0].offsetParent === null) return;
        var svg = pair[0].querySelector('svg:not(.legend-key)');
        if (svg) {
          blocks.push(panelGroup(svg, pair[1] ? (pair[1].textContent || '').trim() : '',
                                 pair[0].querySelector('.legend')));
          return;
        }
        var table = pair[0].querySelector('table');
        // this preset is one number per sample, so a table is the honest export, not a drawn chart
        if (table) { saveBlob(tableCsv(table), 'text/csv', stem + '.csv'); wrote += 1; }
      });
      if (blocks.length) {
        saveBlob(standaloneSvg(blocks, (presets[preset] || {}).label || preset),
                 'image/svg+xml', stem + '.svg');
        wrote += 1;
      }
      if (!wrote) toast('There is nothing drawn to export yet.', 'info');
    });

    syncRateControls();

    var presetNote = h('p', { class: 'chart-note' });
    var recipeName = h('input', { type: 'text', placeholder: 'Name this figure', maxlength: '200' });
    var saveRecipeBtn = button('Save figure recipe', { cls: 'btn-sm btn-accent', icon: 'check' });
    var recipeList = h('div', { class: 'recipe-list' });
    var recipeNotes = h('div');
    var lastFigure = null;

    function presetNeeds(key) { return (presets && presets[key] && presets[key].needs) || []; }
    function applyPresetVisibility() {
      var needs = presetNeeds(presetSel && presetSel.value);
      if (!needs.length) return;
      var show = function (el, key) { var row = el && el.closest ? el.closest('.form-row') : null; if (row) row.hidden = needs.indexOf(key) === -1; };
      show(rReporter, 'reporter_signal');
      show(rBiomass, 'biomass_signal');
      show(rMedium, 'biomass_control_id');
      show(rHost, 'reporter_control_id');
      var spec = presets[presetSel.value] || {};
      presetNote.textContent = spec.measurement || '';
      setHelp(ratesHelp, [spec.measurement || '', spec.caveat || ''].filter(Boolean).join(' ')
        || 'Each workflow runs its own named analysis against the sample and controls you select.');
      setHelp(sampleHelp, presetSel.value === 'rate_profiles' ? SAMPLE_HELP.fit : SAMPLE_HELP.plot);
      ratesTitle.firstChild.nodeValue = spec.label || 'Figure';
      applyPresetHeadings(presetSel.value);
      rRun.textContent = presetSel.value === 'rate_profiles' ? 'Fit rates' : 'Show figure';
      var ackRow = rAck.row;
      if (ackRow) ackRow.hidden = needs.indexOf('reporter_control_id') === -1 && needs.indexOf('biomass_control_id') === -1;
      invalidateRates('Workflow changed. Run it again.');
      syncRateControls();
    }
    presetSel.addEventListener('change', applyPresetVisibility);

    function currentConfig() {
      var c = { delta: Number(rDelta.value), gamma: Number(rGamma.value),
                lam: String(rLam.value).trim() === '' ? null : Number(rLam.value) };
      var needs = presetNeeds(presetSel.value);
      if (needs.indexOf('reporter_signal') !== -1) c.reporter_signal = rReporter.value;
      if (needs.indexOf('biomass_signal') !== -1) c.biomass_signal = rBiomass.value;
      c.sample_id = rSample.value;
      if (needs.indexOf('biomass_control_id') !== -1) c.biomass_control_id = rMedium.value;
      if (needs.indexOf('reporter_control_id') !== -1) c.reporter_control_id = rHost.value;
      return c;
    }

    // a preview is numeric series this page downsamples itself, never markup from the server
    function downsample(times, values, label) {
      var n = (times || []).length, step = Math.max(1, Math.ceil(n / 40)), x = [], y = [];
      for (var i = 0; i < n; i += step) { x.push(Number(times[i])); y.push(values[i] == null ? null : Number(values[i])); }
      return { label: label, x: x, y: y };
    }
    function previewFromFigure() {
      if (!lastFigure || !lastFigure.preview) return null;
      return lastFigure.preview;
    }
    function drawPreview(holder, series) {
      holder.textContent = '';
      if (!series || !series.length) return;
      var NS = 'http://www.w3.org/2000/svg';
      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('viewBox', '0 0 100 40');
      svg.setAttribute('preserveAspectRatio', 'none');
      var all = [];
      series.forEach(function (s) { (s.y || []).forEach(function (v) { if (v != null && isFinite(v)) all.push(v); }); });
      if (!all.length) return;
      var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), span = (hi - lo) || 1;
      series.forEach(function (s, idx) {
        var pts = [], n = (s.y || []).length;
        for (var i = 0; i < n; i++) {
          var v = s.y[i];
          if (v == null || !isFinite(v)) continue;
          pts.push((n > 1 ? (i / (n - 1)) * 100 : 50).toFixed(2) + ',' + (38 - ((v - lo) / span) * 36).toFixed(2));
        }
        if (!pts.length) return;
        var line = document.createElementNS(NS, 'polyline');
        line.setAttribute('points', pts.join(' '));
        line.setAttribute('fill', 'none');
        line.setAttribute('stroke', idx === 0 ? 'var(--series-1)' : 'var(--series-2)');
        line.setAttribute('stroke-width', '1.5');
        svg.appendChild(line);
      });
      holder.appendChild(svg);
    }

    async function refreshRecipes() {
      recipeList.textContent = '';
      var data;
      try { data = await api('GET', '/api/studies/' + study.id + '/recipes'); }
      catch (e) { if (e.status !== 401) recipeList.appendChild(callout('warn', 'Could not load saved figures', h('div', null, e.message))); return; }
      var rows = data.recipes || [];
      if (!rows.length) { recipeList.appendChild(h('p', { class: 'chart-note' }, 'No saved figures in this study yet.')); return; }
      rows.forEach(function (r) {
        var here = r.assay_id === assay.id;
        var openBtn = button(here ? 'Open' : 'Open its assay', { cls: 'btn-sm btn-quiet' });
        var reuseBtn = button('Use here', { cls: 'btn-sm btn-quiet' });
        openBtn.addEventListener('click', function () { openRecipe(r); });
        reuseBtn.addEventListener('click', function () { reuseRecipe(r.id); });
        var preview = h('div', { class: 'recipe-preview' });
        // A preset with no time series saves an empty preview, and an empty decorative block is
        // worse than none. Draw only a real series, and hide the container otherwise.
        if (r.preview) {
          try {
            var series = JSON.parse(r.preview);
            if (Array.isArray(series) && series.length) { drawPreview(preview, series); }
          } catch (err) { /* a preview is decoration */ }
        }
        if (!preview.childNodes.length) { preview.hidden = true; }
        recipeList.appendChild(h('div', { class: 'recipe-card' },
          preview,
          h('div', { class: 'recipe-meta' },
            h('div', { class: 'recipe-title' }, r.name),
            h('div', { class: 'chart-note' }, r.preset_label + (here ? '' : ' from another assay')),
            r.reproducible ? null : h('div', { class: 'chart-note' }, r.stale_reason)),
          h('div', { class: 'row gap' }, openBtn, reuseBtn)));
      });
    }

    async function openRecipe(row) {
      recipeNotes.textContent = '';
      // identities belong to the assay a recipe was saved from, so they are never applied here
      var savedVersion = (row.source || {}).snapshot_version || null;
      if (row.assay_id && row.assay_id === assay.id && savedVersion && String(savedVersion) !== String(version || '')) {
        recipeNotes.appendChild(callout('info', 'Saved against another version',
          h('div', null,
            h('p', null, 'This recipe was saved against version ' + savedVersion + ' of this assay, and you are viewing ' + (version ? 'version ' + version : 'the live data') + '.'),
            h('p', null, h('a', { href: '#/assay/' + row.assay_id + '?version=' + savedVersion }, 'Open that version'),
              ' to restore it, so a frozen recipe is not run against current data.'))));
        return;
      }
      if (row.assay_id && row.assay_id !== assay.id) {
        recipeNotes.appendChild(callout('info', 'Saved on another assay',
          h('div', null,
            h('p', null, 'This recipe\u2019s sample and controls belong to its own assay, so they are not applied here.'),
            h('p', null, h('a', { href: '#/assay/' + row.assay_id + (savedVersion ? '?version=' + savedVersion : '') }, 'Open that assay to see the figure'),
              ', or choose Use here to copy its settings and pick this assay\u2019s own sample and controls.'))));
        return;
      }
      try {
        var r = await api('GET', '/api/recipes/' + row.id);
        var c = r.config || {};
        if (presets[r.preset]) { presetSel.value = r.preset; applyPresetVisibility(); }
        if (c.reporter_signal) rReporter.value = c.reporter_signal;
        if (c.biomass_signal) rBiomass.value = c.biomass_signal;
        if (c.sample_id) rSample.value = c.sample_id;
        if (c.biomass_control_id) rMedium.value = c.biomass_control_id;
        if (c.reporter_control_id) rHost.value = c.reporter_control_id;
        if (c.delta != null) rDelta.value = String(c.delta);
        if (c.gamma != null) rGamma.value = String(c.gamma);
        rLam.value = c.lam == null ? '' : String(c.lam);
        resetAcknowledgement();
        invalidateRates('Opened "' + r.name + '". The compatibility check is not inherited, so check it and run again.');
        syncRateControls();
        if (!r.reproducible) {
          recipeNotes.appendChild(callout('warn', 'This figure may not reproduce',
            h('div', null, r.stale_reason + '. The saved recipe and its preview are kept; run it again to see the current data.')));
        }
      } catch (e) {
        if (e.status !== 401) recipeNotes.appendChild(callout('warn', 'Could not open that figure', h('div', null, e.message)));
      }
    }

    async function reuseRecipe(id) {
      recipeNotes.textContent = '';
      try {
        var tpl2 = await api('GET', '/api/recipes/' + id + '/reuse?assay_id=' + encodeURIComponent(assay.id));
        var tpl = tpl2.template || {};
        if (presets[tpl.preset]) { presetSel.value = tpl.preset; applyPresetVisibility(); }
        // nothing from this assay may stand in for a mapping the user has not made
        rSample.value = ''; rMedium.value = ''; rHost.value = '';
        rReporter.value = tpl.reporter_signal || '';
        rBiomass.value = tpl.biomass_signal || '';
        rDelta.value = tpl.delta != null ? String(tpl.delta) : '1';
        rGamma.value = tpl.gamma != null ? String(tpl.gamma) : '0';
        rLam.value = tpl.lam == null ? '' : String(tpl.lam);
        resetAcknowledgement();
        invalidateRates('Settings copied from "' + tpl2.source_recipe.name + '". Choose this assay\u2019s sample and controls, check compatibility, then run.');
        syncRateControls();
        recipeNotes.appendChild(callout('info', 'Reused on this assay',
          h('div', null,
            h('p', null, 'Signal roles and numerical settings were copied. The sample and controls were not, so pick them for this assay.'),
            (tpl2.problems || []).length ? h('ul', null, tpl2.problems.map(function (x) { return h('li', null, String(x)); })) : null)));
      } catch (e) {
        if (e.status !== 401) recipeNotes.appendChild(callout('warn', 'Could not reuse that figure', h('div', null, e.message)));
      }
    }

    saveRecipeBtn.addEventListener('click', async function () {
      recipeNotes.textContent = '';
      var name = recipeName.value.trim();
      if (!name) { recipeNotes.appendChild(callout('warn', 'Name it first', h('div', null, 'Give the figure a name so it can be found again.'))); return; }
      if (!lastFigure || lastFigure.preset !== presetSel.value) {
        recipeNotes.appendChild(callout('warn', 'Run it first',
          h('div', null, 'Run this workflow once so the saved recipe carries a preview of what it actually produces.')));
        return;
      }
      setBusy(saveRecipeBtn, true, 'Saving\u2026');
      try {
        var payload = {
          name: name, preset: presetSel.value, assay_id: assay.id, config: currentConfig(),
          preview: previewFromFigure(),
          reporter_unit: (signals.find(function (s) { return s.name === rReporter.value; }) || {}).unit,
          biomass_unit: (signals.find(function (s) { return s.name === rBiomass.value; }) || {}).unit,
          analysis_method: lastFigure.method || '',
          analysis_method_version: lastFigure.method_version || '',
          source_fingerprint: lastFigure.source_fingerprint || ''
        };
        if (lastFigure.snapshot_version) payload.snapshot_version = lastFigure.snapshot_version;
        await api('POST', '/api/studies/' + study.id + '/recipes', payload);
        recipeName.value = '';
        toast('Figure recipe saved');
        refreshRecipes();
      } catch (e) {
        if (e.status !== 401) recipeNotes.appendChild(callout('warn', 'Not saved', h('div', { style: { whiteSpace: 'pre-wrap' } }, e.message)));
      } finally { setBusy(saveRecipeBtn, false); }
    });

    var recipesCard = h('section', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', { class: 'card-title' }, 'Figure recipes',
          helpIcon('Pick a workflow above, run it, then save the selections under a name so the figure can be reopened or reused on another assay. A recipe stores roles and settings, never well identifiers, and never a control-compatibility confirmation. Its preview is numeric series this page draws itself.'))),
      h('div', { class: 'plot-controls' }, field('Save as', recipeName), h('div', { class: 'form-row' }, saveRecipeBtn)),
      recipeNotes,
      recipeList);
    view.appendChild(recipesCard);

    ratesCard.insertBefore(h('div', { class: 'plot-controls' },
      field('Workflow', presetSel, { help: 'Each workflow runs its own named analysis and saves what that analysis produced.' })),
      ratesCard.children[1] || null);
    ratesCard.insertBefore(presetNote, ratesCard.children[2] || null);

    (async function () {
      try {
        var pres = await api('GET', '/api/presets');
        (pres.presets || []).forEach(function (p2) {
          presets[p2.key] = p2;
          presetSel.appendChild(h('option', { value: p2.key }, p2.label));
        });
        presetSel.value = 'rate_profiles';
        applyPresetVisibility();
      } catch (e) { /* presets are a convenience; the controls still work without them */ }
      refreshRecipes();
    })();

    if (!signals.length) {
      chartWrap.textContent = '';
      chartWrap.appendChild(emptyState('chart', 'No signals to plot', 'The mapping read no signals from this file.'));
      meanTable.textContent = '';
      meanTable.appendChild(h('p', { class: 'muted' }, 'No signals to summarize.'));
      return;
    }

    function readSettings() {
      settings = {
        signal: signalSel.value,
        correct: corr.input.checked,
        threshold: parseFloat(threshold.value),
        dropBelow: drop.input.checked,
        normalizeBy: normSel.value,
        minOd: parseFloat(minOd.value)
      };
      if (!isFinite(settings.threshold) || settings.threshold < 0) settings.threshold = defaults.threshold;
      if (!isFinite(settings.minOd) || settings.minOd < 0) { settings.minOd = defaults.minOd; minOd.value = String(defaults.minOd); }
      if (!isFinite(parseFloat(threshold.value)) || parseFloat(threshold.value) < 0) threshold.value = String(settings.threshold);
      store(saveKey, settings);
      return settings;
    }

    var groupStyleCache = null;
    function styleForGroup(g, i, fallbackCounter) {
      var s = (g.sample_id !== undefined && sampleById.get(String(g.sample_id))) || samples.find(function (x) { return x.name === g.group; });
      if (s && styles.get(s.id)) return styles.get(s.id);
      if (P.isControl(g.sample_type)) return P.controlStyle(g.sample_type);
      var st = P.slotStyle(samples.filter(function (x) { return !P.isControl(x.sample_type); }).length + fallbackCounter.n);
      fallbackCounter.n += 1;
      return st;
    }

    var analysisSeq = 0;
    var debounce = 0;
    function scheduleAnalysis(delay) {
      clearTimeout(debounce);
      debounce = setTimeout(refreshAnalysis, delay || 0);
    }
    ctx.onCleanup(function () { clearTimeout(debounce); });

    async function refreshAnalysis() {
      var s = readSettings();
      syncPlotControls();
      var seq = ++analysisSeq;
      var qs = new URLSearchParams({ signal: s.signal, correct: s.correct ? '1' : '0', threshold_sd: String(s.threshold), drop_below: s.dropBelow ? '1' : '0' });
      var qm = new URLSearchParams({ signal: s.signal, correct: s.correct ? '1' : '0' });
      if (plotSampleSel.value) { qs.set('samples', plotSampleSel.value); qm.set('samples', plotSampleSel.value); }
      if (s.correct) {
        var ctl = wellsOf(plotCtrlSel.value).join(',');
        qs.set('controls', ctl); qm.set('controls', ctl);
        qs.set('context_acknowledged', plotAck.input.checked ? 'true' : 'false');
        qm.set('context_acknowledged', plotAck.input.checked ? 'true' : 'false');
        if (s.normalizeBy) {
          var nctl = wellsOf(plotNormCtrlSel.value).join(',');
          qs.set('normalize_controls', nctl); qm.set('normalize_controls', nctl);
        }
      }
      if (version) { qs.set('version', String(version)); qm.set('version', String(version)); }
      if (s.normalizeBy) {
        qs.set('normalize_by', s.normalizeBy);
        qs.set('min_od', String(s.minOd));
        qm.set('normalize_by', s.normalizeBy);
        qm.set('min_od', String(s.minOd));
      }
      var needs = [];
      if (s.correct) {
        if (!plotSampleSel.value) needs.push('a sample group');
        if (!plotCtrlSel.value) needs.push('a background control');
        if (s.normalizeBy && !plotNormCtrlSel.value) needs.push('a normalization control');
      }
      if (needs.length) {
        if (chart) { chart.destroy(); chart = null; }
        busyPill.hidden = true;
        chartWrap.className = 'chart';
        chartWrap.textContent = '';
        chartWrap.removeAttribute('aria-busy');
        chartWrap.appendChild(emptyState('chart', 'Choose ' + needs.join(' and '),
          'Background correction subtracts only the wells you select. Turn correction off to plot raw values.'));
        meanTable.textContent = '';
        meanChart.textContent = '';
        meanSub.textContent = '';
        meanCard.removeAttribute('aria-busy');
        meanTable.appendChild(emptyState('chart', 'Choose ' + needs.join(' and '), ''));
        return;
      }
      if (chart) {
        chartWrap.classList.add('is-loading');
        busyPill.hidden = false;
      }
      meanCard.setAttribute('aria-busy', 'true');
      var out = await Promise.allSettled([
        api('GET', '/api/assays/' + assay.id + '/series?' + qs.toString()),
        api('GET', '/api/assays/' + assay.id + '/mean-expression?' + qm.toString())
      ]);
      if (seq !== analysisSeq || !ctx.alive()) return;
      busyPill.hidden = true;
      chartWrap.classList.remove('is-loading');
      chartWrap.removeAttribute('aria-busy');
      meanCard.removeAttribute('aria-busy');
      renderSeries(out[0]);
      renderMean(out[1]);
    }

    function renderSeries(res) {
      chartNotes.textContent = '';
      if (res.status === 'rejected') {
        if (res.reason && res.reason.status === 401) return;
        if (chart) { chart.destroy(); chart = null; }
        chartWrap.className = 'chart';
        chartWrap.textContent = '';
        chartWrap.appendChild(errorCallout(res.reason, function () { scheduleAnalysis(0); },
          res.reason && res.reason.status === 422 ? 'This correction needs a compatible control' : null));
        return;
      }
      var data = res.value || {};
      var counter = { n: 0 };
      var groups = (data.groups || []).map(function (g, i) {
        return {
          key: String(g.sample_id || g.group),
          label: String(g.group),
          times: g.times_h || [],
          mean: g.mean || [],
          sd: g.sd || [],
          n: g.n || [],
          nLabel: 'n=' + ((g.positions || []).length || Math.max.apply(null, (g.n || [0]).concat([0]))),
          style: styleForGroup(g, i, counter)
        };
      });
      groupStyleCache = new Map(groups.map(function (g) { return [g.key, g.style]; }));

      if (!groups.length) {
        if (chart) { chart.destroy(); chart = null; }
        chartWrap.className = 'chart';
        chartWrap.textContent = '';
        chartWrap.appendChild(emptyState('plate', 'Nothing to plot yet',
          samples.length ? 'Assign wells to samples in the plate layout above and save it. Each sample becomes one line.' : 'Add samples to the study, then assign them to wells in the plate layout.'));
      } else {
        var unit = data.unit ? ' (' + data.unit + ')' : '';
        var yLabel = (data.signal || settings.signal) + (data.normalized_by ? ' / ' + data.normalized_by : '') + unit;
        var opts = { groups: groups, xLabel: 'Time (h)', yLabel: yLabel };
        if (!chart) {
          chartWrap.textContent = '';
          chartWrap.className = 'chart';
          chart = P.lineChart(chartWrap, opts);
          ctx.onCleanup(function () { if (chart) chart.destroy(); });
        } else {
          chart.update(opts);
        }
      }

      var notes = [];
      if (settings.correct && data.corrected) {
        var cp = data.control_positions || [];
        notes.push('Background corrected with the mean of ' + plural(cp.length, (data.control_type ? data.control_type + ' ' : '') + 'well') +
          (cp.length ? ' (' + cp.slice(0, 8).join(', ') + (cp.length > 8 ? ', …' : '') + ')' : '') +
          '. Points within ' + settings.threshold + ' SD of background are ' + (settings.dropBelow ? 'hidden.' : 'kept.'));
      }
      if (data.normalized_by) notes.push('Normalized by ' + data.normalized_by + '; points with OD below ' + settings.minOd + ' are left out.');
      if (notes.length) chartNotes.appendChild(h('p', { class: 'chart-note' }, notes.join(' ')));
      if (settings.correct && data.corrected === false) {
        chartNotes.appendChild(callout('warn', 'Background correction was not applied',
          h('div', null, 'Assign medium or untransformed control samples to wells in the plate layout, then save it. The raw signal is shown instead.')));
      }
      var shownWarnings = (data.warnings || []).filter(function (x) { return !(settings.correct && data.corrected === false && /^No control wells/.test(x)); });
      var w = groups.length ? warningsCallout('Notes from the analysis', shownWarnings) : null;
      if (w) {
        w.style.marginTop = '10px';
        chartNotes.appendChild(w);
      }
    }

    var bars = null;
    ctx.onCleanup(function () { if (bars) bars.destroy(); });
    function dropBars() {
      if (bars) { bars.destroy(); bars = null; }
      meanChart.textContent = '';
    }

    function renderMean(res) {
      meanTable.textContent = '';
      meanSub.textContent = '';
      if (res.status === 'rejected') {
        wellValues = null;
        dropBars();
        if (res.reason && res.reason.status === 401) return;
        meanTable.appendChild(errorCallout(res.reason, function () { scheduleAnalysis(0); },
          res.reason && res.reason.status === 422 ? 'This correction needs a compatible control' : null));
        return;
      }
      var data = res.value || {};
      wellValues = data.wells || null;
      meanSub.textContent = (data.signal || settings.signal) + (data.normalized_by ? ' / ' + data.normalized_by : '') + (data.corrected ? ', background corrected' : ', raw values');
      var groups = data.groups || [];
      if (!groups.length) {
        dropBars();
        meanTable.appendChild(h('p', { class: 'muted', style: { fontSize: '0.86rem' } }, 'No groups yet. Assign wells to samples to see mean expression per sample.'));
        return;
      }
      var counter = { n: 0 };
      var rows = groups.map(function (g, i) {
        var gk = String(g.sample_id || g.group);
        var st = (groupStyleCache && groupStyleCache.get(gk)) || styleForGroup(g, i, counter);
        return { key: gk, label: String(g.group), mean: g.mean, sd: g.sd, n: g.n, type: g.sample_type, style: st };
      });
      meanTable.appendChild(h('div', { class: 'table-scroll' },
        h('table', { class: 'table' },
          h('thead', null, h('tr', null, h('th', null, 'Group'), h('th', { class: 'num' }, 'Mean'), h('th', { class: 'num' }, 'SD'), h('th', { class: 'num' }, 'n'))),
          h('tbody', null, rows.map(function (r) {
            return h('tr', null,
              h('td', null, h('span', { class: 'cell-name' }, P.swatch(r.style), h('span', null, r.label), P.isControl(r.type) ? typeBadge(r.type) : null)),
              h('td', { class: 'num' }, P.fmt(r.mean)),
              h('td', { class: 'num' }, P.fmt(r.sd)),
              h('td', { class: 'num' }, r.n === null || r.n === undefined ? 'n/a' : String(r.n)));
          })))));
      var barOpts = { groups: rows, unitLabel: meanSub.textContent };
      if (bars) bars.update(barOpts);
      else bars = P.barChart(meanChart, barOpts);
    }

    // an acknowledgement is about one set of wells, so changing the biological selection clears it
    function clearPlotAcknowledgement() {
      if (!plotAck.input.checked) return;
      plotAck.input.checked = false;
      toast('The control-compatibility check was cleared because the selection changed.');
    }
    [signalSel, normSel, plotSampleSel, plotCtrlSel, plotNormCtrlSel].forEach(function (el) {
      el.addEventListener('change', function () { clearPlotAcknowledgement(); scheduleAnalysis(0); });
    });
    plotAck.input.addEventListener('change', function () { scheduleAnalysis(0); });
    corr.input.addEventListener('change', function () { scheduleAnalysis(0); });
    drop.input.addEventListener('change', function () { scheduleAnalysis(0); });
    threshold.addEventListener('input', function () { scheduleAnalysis(400); });
    minOd.addEventListener('input', function () { scheduleAnalysis(400); });

    syncPlotControls();
    await refreshAnalysis();
  }

  /* ===================================================================
     Mappings
     =================================================================== */

  function mappingSpecModal(m) {
    var pre = h('pre', { class: 'code-view' }, 'Loading…');
    var specText = '';
    var lock = writeLock(state.wsId);
    var ctl = openModal({
      title: (m.emoji ? m.emoji + ' ' : '') + m.name,
      wide: true,
      body: h('div', null,
        h('p', { class: 'modal-text' }, h('code', null, m.key + (m.version !== undefined ? ' v' + m.version : '')), '  ', m.description || ''),
        pre),
      actions: [
        {
          label: 'Copy JSON', cls: 'btn-quiet', icon: 'copy',
          onClick: async function () {
            if (!specText) return false;
            var ok = await copyText(specText);
            toast(ok ? 'Mapping JSON copied' : 'Copy failed. Select the text and copy it by hand.', ok ? 'ok' : 'error');
            return false;
          }
        },
        {
          label: 'Use as template', cls: 'btn-quiet', icon: 'plus',
          onClick: function (c) {
            if (lock || !state.wsId) { toast(lock || 'Create a workspace first.', 'info'); return false; }
            if (!specText) return false;
            c.close(null);
            newMappingModal(JSON.parse(specText), true);
            return false;
          }
        },
        { label: 'Close', cls: 'btn-accent', primary: true }
      ]
    });
    api('GET', '/api/mappings/' + m.id).then(function (full) {
      specText = JSON.stringify(full.spec !== undefined ? full.spec : full, null, 2);
      pre.textContent = specText;
    }).catch(function (e) {
      pre.textContent = '';
      ctl.setError(e.message);
    });
  }

  function templateFrom(spec) {
    var copy = JSON.parse(JSON.stringify(spec || {}));
    if (copy.key) copy.key = copy.key + '-custom';
    if (copy.name) copy.name = copy.name + ' (custom)';
    return copy;
  }

  function slugify(text) {
    var s = String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return s.length >= 3 ? s.slice(0, 64) : '';
  }

  var MAPPING_FORM_OPTIONS = null;

  async function mappingFormOptions() {
    if (!MAPPING_FORM_OPTIONS) MAPPING_FORM_OPTIONS = await api('GET', '/api/mapping-form/options');
    return MAPPING_FORM_OPTIONS;
  }

  /* The guided path: ordinary fields, then a check against one real export before saving.
     A valid mapping is not evidence that it fits the file, so Save waits for that check. */
  async function newMappingModal(baseSpec, fromView) {
    var ws = currentWs();
    var opts;
    try {
      opts = await mappingFormOptions();
    } catch (e) {
      opts = { position_styles: [{ value: 'a1-384', label: 'A1 to P24' }], kinds: ['absorbance', 'fluorescence', 'luminescence', 'other'], units: {}, formats: [{ value: 'xlsx', label: 'Excel workbook (.xlsx)' }, { value: 'delimited', label: 'Text export (.txt or .csv)' }] };
    }
    var form = {
      key: '', name: '', emoji: '🧪', description: '', format: 'xlsx', sheet_index: 0,
      label_column: 1, header_offset: 2, time_header: 'Time', position_style: 'a1-384',
      temperature_column: true, label_has_optics: true,
      metadata: { key_column: 1, value_column: 2, fields: {} }, channels: []
    };
    var advanced = false, checked = null, keyEdited = false, allowNewVersion = false;
    var checkSeq = 0, jsonDirty = false, templateSpec = baseSpec || null;

    var nameIn = h('input', { type: 'text', placeholder: 'Lab plate reader', value: '' });
    var keyIn = h('input', { type: 'text', placeholder: 'lab-plate-reader', spellcheck: 'false' });
    var emojiIn = h('input', { type: 'text', value: form.emoji, maxlength: '8', class: 'input-tiny' });
    var descIn = h('input', { type: 'text', placeholder: 'What this export looks like' });
    var templateSel = selectEl([{ value: '', label: 'Loading templates…' }], '', { 'aria-label': 'Start from' });
    var formatSel = selectEl(opts.formats, form.format);
    var sheetIn = h('input', { type: 'number', min: '1', value: '1', class: 'input-tiny' });
    var labelColIn = h('input', { type: 'number', min: '1', value: '1', class: 'input-tiny' });
    var offsetIn = h('input', { type: 'number', min: '1', value: '2', class: 'input-tiny' });
    var timeHeadIn = h('input', { type: 'text', value: 'Time', class: 'input-small' });
    var posSel = selectEl(opts.position_styles, form.position_style);
    var tempTog = toggleSwitch('The reading blocks have a temperature column', true);
    var opticsTog = toggleSwitch('Channel labels carry the optics after a colon, as in OD600:600', true);
    var fileIn = h('input', { type: 'file', accept: '.xlsx,.xlsm,.txt,.csv,.tsv' });
    var checkOut = h('div', { class: 'preview-out' });
    var chanBox = h('div', { class: 'chan-box' });
    var statusLine = h('p', { class: 'hint' }, 'Check the mapping against one export before saving.');
    var jsonArea = h('textarea', { class: 'code', spellcheck: 'false', 'aria-label': 'Mapping JSON' });

    var sheetRow = field('Sheet number', sheetIn, { help: 'Which sheet of the workbook holds the readings. The first sheet is 1.' });
    var guided = h('div', null,
      h('div', { class: 'form-grid' },
        field('Start from', templateSel, { help: 'A template fills in the structure settings for you. Your copy is independent once saved.' }),
        field('Name', nameIn),
        field('Identifier', keyIn, { help: 'Used in links and when importing a file. Lowercase letters, numbers and hyphens.' }),
        field('Icon', emojiIn),
        field('Description', descIn, { cls: 'span-2' })),
      h('h4', { class: 'form-head' }, 'Where the readings sit'),
      h('div', { class: 'form-grid' },
        field('File format', formatSel),
        sheetRow,
        field('Column with the channel label', labelColIn, { help: 'The column where each reading block announces itself. The first column is 1.' }),
        field('Rows between that label and the header', offsetIn, { help: 'Gen5 writes the label, a blank row, then the header row, which is 2.' }),
        field('Header of the time column', timeHeadIn, { help: 'Copy it exactly as the file spells it.' }),
        field('Well names', posSel, { help: 'Choose the shape that covers every well the file measured. A shape that left wells out would discard their readings, so BOB refuses it.' })),
      h('div', { class: 'form-stack' }, tempTog.row, opticsTog.row));
    var advancedBox = h('div', { hidden: true },
      h('p', { class: 'modal-text flush' }, 'The mapping as JSON, for a layout the guided fields cannot describe.'),
      jsonArea);
    var checkBlock = h('div', null,
      h('h4', { class: 'form-head' }, 'Check it against one export',
        helpIcon('BOB reads the file with these settings and shows what it found. Nothing is saved and no assay or sample is created. A mapping can be perfectly valid and still not fit this file, so this check is what settles it.')),
      h('div', { class: 'form-grid' }, field('One export from this instrument', fileIn, { cls: 'span-2' })),
      h('div', { class: 'form-stack' },
        button('Check this file', { cls: 'btn-quiet btn-sm', icon: 'play', onClick: runCheck }),
        statusLine),
      checkOut, chanBox);
    var body = h('div', null, guided, advancedBox, checkBlock);

    function setStatus(text, cls) {
      statusLine.textContent = text;
      statusLine.className = cls || 'hint';
    }

    // the result stops being evidence, but what the user typed is theirs and stays on screen
    function invalidate(why) {
      checkSeq += 1;
      if (!checked && !why) return;
      checked = null;
      setStatus(why || 'The settings changed, so the previous check no longer applies. Check the file again.', 'hint warn');
      syncSave();
    }

    // a different file or template means the channels found before describe nothing here
    function resetDiscovery(why) {
      rows = [];
      chanBox.textContent = '';
      checkOut.textContent = '';
      invalidate(why);
    }

    function readForm() {
      form.name = nameIn.value.trim();
      form.key = keyIn.value.trim() || slugify(nameIn.value);
      form.emoji = emojiIn.value.trim() || null;
      form.description = descIn.value.trim();
      form.format = formatSel.value;
      form.sheet_index = Math.max(0, (parseInt(sheetIn.value, 10) || 1) - 1);
      form.label_column = Math.max(1, parseInt(labelColIn.value, 10) || 1);
      form.header_offset = Math.max(1, parseInt(offsetIn.value, 10) || 2);
      form.time_header = timeHeadIn.value || 'Time';
      form.position_style = posSel.value;
      form.temperature_column = tempTog.input.checked;
      form.label_has_optics = opticsTog.input.checked;
      form.channels = channelsFromRows();
      sheetRow.hidden = form.format !== 'xlsx';
      return form;
    }

    var rows = [];

    function channelsFromRows() {
      return rows.map(function (r) {
        return { label: r.label, kind: r.kind.value, unit: r.unit.value.trim() };
      });
    }

    function buildChannelRows(channels) {
      rows = [];
      chanBox.textContent = '';
      if (!channels.length) return;
      chanBox.appendChild(h('h4', { class: 'form-head' }, 'Channel measurements',
        helpIcon('Say what the instrument measured, not what you will conclude from it. BOB reads no meaning into a name: absorbance is not biomass until you interpret it that way, and fluorescence is not expression on its own. Leave a channel as other when you are not sure. Labels come from the file; rename a channel per run when you import it.')));
      channels.forEach(function (c) {
        var kind = selectEl((opts.kinds || []).map(function (k) { return { value: k, label: k }; }), c.kind === 'other' ? 'other' : c.kind);
        var unit = h('input', { type: 'text', value: c.unit || '', class: 'input-tiny', placeholder: 'unit' });
        var units = (opts.units || {})[kind.value] || [];
        if (!unit.value && units.length) unit.value = units[0];
        kind.addEventListener('change', function () {
          var list = (opts.units || {})[kind.value] || [];
          if (list.length) unit.value = list[0];
          invalidate();
        });
        unit.addEventListener('input', function () { invalidate(); });
        rows.push({ label: c.label, kind: kind, unit: unit });
        chanBox.appendChild(h('div', { class: 'chan-row' },
          h('code', { class: 'chan-label' }, c.label),
          field('This measures', kind), field('Unit', unit),
          h('span', { class: 'chan-meta' }, (c.measured_well_count || 0) + ' wells with readings of '
            + (c.header_position_count || 0) + ' listed, ' + (c.point_count || 0) + ' time points')));
      });
    }

    function renderCheck(b) {
      checkOut.textContent = '';
      var problems = b.problems || [];
      if (b.next_step && !problems.length) {
        checkOut.appendChild(h('div', { class: 'callout' },
          h('strong', null, 'Read ' + ((b.channels || []).length) + ' channels from ' + b.file.name),
          h('p', { class: 'flush' }, b.next_step)));
      }
      if (problems.length) {
        checkOut.appendChild(h('div', { class: 'callout callout-error' },
          h('strong', null, 'This mapping did not read the file'),
          h('ul', { class: 'tight' }, problems.map(function (p) { return h('li', null, p); }))));
      }
      (b.warnings || []).forEach(function (w) {
        checkOut.appendChild(h('div', { class: 'callout callout-warn' }, w));
      });
      if (!b.channels || !b.channels.length) return;
      var first = b.channels[0];
      checkOut.appendChild(h('dl', { class: 'kv-list' },
        h('dt', null, 'Channels'), h('dd', null, String(b.channels.length)),
        h('dt', null, 'Wells with readings'), h('dd', null, String(first.measured_well_count) + ' of ' + String(first.header_position_count) + ' listed in the header' + ((b.wells || []).length ? ' (' + b.wells[0] + ' to ' + b.wells[b.wells.length - 1] + ')' : '')),
        h('dt', null, 'Time'), h('dd', null, first.point_count + ' points, ' + fmtNum(first.first_time_h) + ' h to ' + fmtNum(first.last_time_h) + ' h'),
        h('dt', null, 'Temperature'), h('dd', null, first.has_temperature ? 'read' : 'not in this file'),
        h('dt', null, 'From the header'), h('dd', null, Object.keys(b.metadata || {}).length ? Object.keys(b.metadata).map(function (k) { return k + ': ' + b.metadata[k]; }).join(' · ') : 'nothing matched')));
      var tbl = h('table', { class: 'table table-tight' },
        h('thead', null, h('tr', null, h('th', null, 'Channel'), h('th', null, 'Well'), h('th', { class: 'num' }, 'First three readings'))),
        h('tbody', null, b.channels.map(function (c) {
          var w = (c.preview && c.preview.wells && c.preview.wells[0]) || { position: '', values: [] };
          return h('tr', null,
            h('td', null, c.name + (c.optics_text ? ' (' + c.optics_text + ')' : '')),
            h('td', null, w.position),
            h('td', { class: 'num' }, w.values.map(function (v) { return v === null ? 'n/a' : fmtNum(v); }).join(', ')));
        })));
      checkOut.appendChild(h('div', { class: 'table-scroll' }, tbl));
    }

    function fmtNum(v) {
      if (v === null || v === undefined) return 'n/a';
      return String(Math.round(v * 10000) / 10000);
    }

    async function runCheck() {
      var f = fileIn.files && fileIn.files[0];
      if (!f) { setStatus('Choose one export from this instrument first.', 'hint warn'); return false; }
      readForm();
      if (advanced) {
        try { JSON.parse(jsonArea.value); } catch (e) { setStatus('The JSON is not valid: ' + e.message, 'hint warn'); return false; }
      } else if (!form.key) {
        setStatus('Give the mapping a name, so it has an identifier.', 'hint warn'); return false;
      }
      var fd = new FormData();
      fd.append('file', f, f.name);
      fd.append(advanced ? 'spec' : 'form', advanced ? jsonArea.value : JSON.stringify(form));
      setStatus('Reading ' + f.name + '…');
      checkSeq += 1;
      var mine = checkSeq;
      try {
        var b = await api('POST', '/api/workspaces/' + ws.id + '/mappings/preview', fd);
      } catch (e) {
        if (mine !== checkSeq) return false;
        setStatus(e.message || 'The check failed.', 'hint warn');
        checked = null; syncSave(); return false;
      }
      // an answer about inputs that have since changed is not evidence about the current ones
      if (mine !== checkSeq) return false;
      renderCheck(b);
      if (!advanced && (!rows.length || !b.channels_named)) buildChannelRows(b.channels || []);
      checked = b.ok ? b : null;
      var failed = (b.problems || []).length > 0;
      setStatus(b.ok ? 'This mapping reads ' + b.file.name + '. You can save it.'
                     : failed ? 'This mapping did not read ' + b.file.name + '. Change the settings and check again.'
                              : 'Read ' + (b.channels || []).length + ' channels. Say what each one measures, then check again.',
                b.ok ? 'hint ok' : 'hint warn');
      syncSave();
      return false;
    }

    var ctl = openModal({
      title: 'New mapping',
      icon: 'layers',
      wide: true,
      body: body,
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: 'Advanced JSON', cls: 'btn-quiet', icon: 'code',
          onClick: async function () {
            advanced = !advanced;
            guided.hidden = advanced;
            advancedBox.hidden = !advanced;
            chanBox.hidden = advanced;
            if (advanced && !jsonDirty) {
              try {
                jsonArea.value = JSON.stringify(await specForJson(), null, 2);
              } catch (e) {
                setStatus('The current answers could not be turned into JSON: ' + e.message, 'hint warn');
              }
            }
            invalidate(advanced ? 'Edit the JSON, then check it against a file; the previous check no longer applies.'
                                : 'Back to the guided fields. Check the file again.');
            return false;
          }
        },
        {
          label: 'Save mapping', cls: 'btn-accent', primary: true, busyLabel: 'Saving…', verbatimErrors: true,
          onClick: async function (c) {
            if (!checked) {
              c.setError('Check the mapping against one export first. A mapping that passes the schema can still not fit the file.', true);
              return false;
            }
            readForm();
            var payload = advanced ? { spec: JSON.parse(jsonArea.value) } : { form: form, new_version: allowNewVersion };
            try {
              var res = await api('POST', '/api/workspaces/' + ws.id + '/mappings', payload);
              toast('Mapping ' + (res.name || '') + ' saved as version ' + res.version);
              await loadMappings(true);
              if (parseRoute() && parseRoute().name === 'mappings') route(true);
            } catch (e) {
              if (e.status === 401) throw e;
              if (e.status === 409 && !advanced && /already has/.test(String(e.detail || ''))) {
                // the existing version is kept either way; pressing Save again is the confirmation
                allowNewVersion = true;
                c.setError(String(e.detail) + ' Press Save mapping again to add it.', true);
                return false;
              }
              var d = e.detail;
              throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d, null, 2) : e.message);
            }
          }
        }
      ]
    });

    function syncSave() {
      var btn = ctl.box.querySelector('.modal-actions .btn-accent');
      if (!btn) return;
      btn.setAttribute('aria-disabled', checked ? 'false' : 'true');
    }

    // the spec the guided answers currently mean, so the editor never opens on a stub
    async function specForJson() {
      readForm();
      try {
        return (await api('POST', '/api/mapping-form/spec', { form: form })).spec;
      } catch (e) {
        if (templateSpec) {
          var copy = templateFrom(templateSpec);
          copy.key = form.key || copy.key;
          copy.name = form.name || copy.name;
          return copy;
        }
        throw e;
      }
    }

    [nameIn, descIn, emojiIn, timeHeadIn, sheetIn, labelColIn, offsetIn].forEach(function (el) {
      el.addEventListener('input', function () { invalidate(); });
    });
    [formatSel, posSel].forEach(function (el) { el.addEventListener('change', function () { invalidate(); }); });
    templateSel.addEventListener('change', function () {
      resetDiscovery('A different template, so the channels found before no longer apply. Check the file again.');
    });
    [tempTog.input, opticsTog.input].forEach(function (el) { el.addEventListener('change', function () { invalidate(); }); });
    fileIn.addEventListener('change', function () {
      resetDiscovery('A different file, so the channels found before no longer describe it. Check this file.');
    });
    jsonArea.addEventListener('input', function () { jsonDirty = true; invalidate('The JSON changed, so check it against the file again.'); });
    keyIn.addEventListener('input', function () { keyEdited = true; invalidate(); });
    nameIn.addEventListener('input', function () {
      if (!keyEdited) keyIn.value = slugify(nameIn.value);
    });
    formatSel.addEventListener('change', function () { sheetRow.hidden = formatSel.value !== 'xlsx'; });

    function applyForm(f) {
      formatSel.value = f.format;
      sheetIn.value = String((f.sheet_index || 0) + 1);
      labelColIn.value = String(f.label_column);
      offsetIn.value = String(f.header_offset);
      timeHeadIn.value = f.time_header;
      posSel.value = f.position_style;
      tempTog.input.checked = !!f.temperature_column;
      opticsTog.input.checked = !!f.label_has_optics;
      form.metadata = f.metadata || form.metadata;
      sheetRow.hidden = f.format !== 'xlsx';
    }

    try {
      var maps = await loadMappings();
      var usable = maps.filter(function (m) { return m.modality === 'plate_reader'; });
      templateSel.textContent = '';
      usable.forEach(function (m) {
        templateSel.appendChild(h('option', { value: m.id }, (m.emoji ? m.emoji + ' ' : '') + m.name + (m.builtin ? ' (built in)' : ' v' + m.version)));
      });
      async function loadTemplate(id) {
        if (!id) return;
        var r = await api('GET', '/api/mappings/' + id + '/form');
        applyForm(r.form);
        api('GET', '/api/mappings/' + id).then(function (full) { templateSpec = full.spec || templateSpec; }).catch(function () { });
        if (!nameIn.value) {
          nameIn.value = (r.form.name || '') + ' (custom)';
          keyIn.value = slugify(nameIn.value);
        }
        if ((r.advanced || []).length) {
          statusLine.textContent = '';
          statusLine.className = 'hint';
          statusLine.appendChild(document.createTextNode('Choose a file and check it; you will then name what each channel measures. '));
          statusLine.appendChild(helpIcon('This template does something the guided fields do not cover: '
            + r.advanced.join('; ') + '. Your copy names each channel exactly instead, which is why the check lists them.'));
        }
      }
      templateSel.addEventListener('change', function () { loadTemplate(templateSel.value); });
      var start = baseSpec ? usable.find(function (m) { return m.key === baseSpec.key; }) : usable[0];
      if (start) { templateSel.value = start.id; await loadTemplate(start.id); }
    } catch (e) {
      ctl.setError('The templates could not be loaded: ' + e.message);
    }
    syncSave();
    if (!fromView) nameIn.focus();
  }

  async function viewMappings(view, ctx) {
    var ws = currentWs();
    var lock = ws ? writeLock(ws.id) : 'Create a workspace first.';
    var grid = h('div', { class: 'map-grid' });
    view.appendChild(pageHero('Instrument mappings', null,
      [h('p', { class: 'page-desc flush' }, 'A mapping tells BOB how to read one instrument’s export into the shared data core. Mappings are declarative JSON, hold no code, and are frozen once published. Star the ones you rely on.')],
      [button('New mapping', { cls: 'btn-accent btn-sm', icon: 'plus', locked: lock, onClick: function () { newMappingModal(null); } })]));
    view.appendChild(grid);
    grid.appendChild(h('section', { class: 'card', style: { gridColumn: '1 / -1' } }, skeleton(2)));

    var maps;
    try {
      maps = await loadMappings(true);
    } catch (e) {
      if (!ctx.alive()) return;
      grid.textContent = '';
      grid.appendChild(h('section', { class: 'card', style: { gridColumn: '1 / -1' } }, errorCallout(e, function () { route(true); })));
      return;
    }
    if (!ctx.alive()) return;
    grid.textContent = '';
    if (!maps.length) {
      grid.appendChild(h('section', { class: 'card', style: { gridColumn: '1 / -1' } }, emptyState('layers', 'No mappings', 'This server has no mappings yet.')));
      return;
    }
    maps.slice().sort(mappingRank).forEach(function (m) {
      var owner = m.workspace_id !== null && m.workspace_id !== undefined ? wsById(m.workspace_id) : null;
      var star = h('button', { type: 'button', class: 'star-btn', 'aria-pressed': m.starred ? 'true' : 'false', 'aria-label': (m.starred ? 'Unstar ' : 'Star ') + m.name }, icon('star'), h('span', null, String(m.stars || 0)));
      star.addEventListener('click', async function () {
        var was = star.getAttribute('aria-pressed') === 'true';
        var count = star.querySelector('span');
        var before = parseInt(count.textContent, 10) || 0;
        star.setAttribute('aria-pressed', was ? 'false' : 'true');
        count.textContent = String(Math.max(0, before + (was ? -1 : 1)));
        star.disabled = true;
        try {
          var res = await api(was ? 'DELETE' : 'POST', '/api/mappings/' + m.id + '/star');
          if (res) {
            count.textContent = String(res.stars);
            star.setAttribute('aria-pressed', res.starred ? 'true' : 'false');
            m.stars = res.stars;
            m.starred = res.starred;
          }
          star.setAttribute('aria-label', (m.starred ? 'Unstar ' : 'Star ') + m.name);
        } catch (e) {
          star.setAttribute('aria-pressed', was ? 'true' : 'false');
          count.textContent = String(before);
          if (e.status !== 401) toast('Star not saved: ' + e.message, 'error');
        } finally {
          star.disabled = false;
        }
      });
      grid.appendChild(h('article', { class: 'card map-card' },
        h('div', { class: 'map-top' },
          h('div', { class: 'map-emoji', 'aria-hidden': 'true' }, m.emoji || '🧪'),
          h('div', { style: { minWidth: '0' } },
            h('div', { class: 'map-name' }, m.name),
            h('div', { class: 'map-key' }, m.key + (m.version !== undefined && m.version !== null ? ' · v' + m.version : '')))),
        h('div', { class: 'map-badges' },
          badge(humanize(m.modality || 'plate_reader'), 'badge-accent'),
          m.builtin ? badge('Built in') : null,
          owner ? badge(owner.name, 'badge-muted', { title: 'Published in this workspace' }) : null),
        h('div', { class: 'map-desc' }, m.description || 'No description.'),
        h('div', { class: 'map-foot' },
          star,
          button('View', { cls: 'btn-sm btn-quiet', icon: 'eye', onClick: function () { mappingSpecModal(m); } }))));
    });
  }

  /* ===================================================================
     Workspace
     =================================================================== */

  async function viewWorkspace(view, ctx) {
    var ws = currentWs();
    if (!ws) { view.appendChild(noWorkspaceCard()); return; }
    var owner = ws.role === 'owner';
    var me = state.me.user;

    var nameInput = h('input', { type: 'text', value: ws.name, maxlength: '120', disabled: !owner });
    var saveName = button('Save', { cls: 'btn-accent', locked: owner ? null : OWNER_REASON });
    var nameErr = h('div', { class: 'field-error', role: 'alert', hidden: true });
    if (owner) {
      saveName.addEventListener('click', async function () {
        var n = nameInput.value.trim();
        formError(nameErr, null);
        if (!n) { formError(nameErr, 'The workspace needs a name.'); return; }
        setBusy(saveName, true, 'Saving…');
        try {
          await api('PATCH', '/api/workspaces/' + ws.id, { name: n });
          await refreshMe();
          toast('Workspace renamed');
        } catch (e) {
          if (e.status !== 401) formError(nameErr, e.message);
        } finally {
          setBusy(saveName, false);
        }
      });
      nameInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') saveName.click(); });
    }
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Workspace'),
      h('div', { class: 'inline-form' },
        field('Name', nameInput),
        saveName),
      nameErr,
      h('div', { class: 'page-meta' },
        h('span', null, 'Your role: ', roleBadge(ws.role)),
        ws.slug ? h('span', null, 'Slug: ', h('code', null, ws.slug)) : null)));

    var tableBox = h('div', null, skeleton(2));
    var membersCard = h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Members', helpIcon('Owners manage members and settings. Editors add and change data. Viewers can read everything but change nothing.')),
      tableBox);
    view.appendChild(membersCard);

    var roleOptions = [{ value: 'viewer', label: 'Viewer' }, { value: 'editor', label: 'Editor' }, { value: 'owner', label: 'Owner' }];

    async function loadMembers() {
      var members;
      try {
        members = await api('GET', '/api/workspaces/' + ws.id + '/members');
      } catch (e) {
        if (!ctx.alive()) return;
        tableBox.textContent = '';
        tableBox.appendChild(errorCallout(e, loadMembers));
        return;
      }
      if (!ctx.alive()) return;
      tableBox.textContent = '';
      tableBox.appendChild(h('div', { class: 'table-scroll' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', null, 'Email'), h('th', null, 'Role'), owner ? h('th', { class: 'actions' }, h('span', { class: 'sr-only' }, 'Actions')) : null)),
        h('tbody', null, members.map(function (mb) {
          var isMe = String(mb.user_id) === String(me.id);
          var roleCell;
          if (owner) {
            var sel = selectEl(roleOptions, mb.role, { 'aria-label': 'Role of ' + (mb.name || mb.email) });
            sel.addEventListener('change', async function () {
              var prev = mb.role;
              if (isMe && prev === 'owner' && sel.value !== 'owner') {
                var keep = sel.value;
                sel.value = prev;
                var ok = await confirmDialog({
                  title: 'Give up owner rights?',
                  message: 'You will become ' + (keep === 'editor' ? 'an editor' : 'a viewer') + ' of ' + ws.name + ' and can no longer manage members or settings. Only another owner can make you an owner again.',
                  confirmLabel: 'Change my role',
                  busyLabel: 'Changing…'
                });
                if (!ok) return;
                sel.value = keep;
              }
              sel.disabled = true;
              try {
                await api('PATCH', '/api/workspaces/' + ws.id + '/members/' + mb.user_id, { role: sel.value });
                mb.role = sel.value;
                toast((mb.name || mb.email) + ' is now ' + (sel.value === 'owner' ? 'an owner' : sel.value === 'editor' ? 'an editor' : 'a viewer'));
                if (isMe) { await refreshMe(); route(true); }
              } catch (e) {
                sel.value = prev;
                if (e.status !== 401) toast('Role not changed: ' + e.message, 'error');
              } finally {
                sel.disabled = false;
              }
            });
            roleCell = sel;
          } else {
            roleCell = roleBadge(mb.role);
          }
          return h('tr', null,
            h('td', null, h('span', { class: 'cell-name' }, h('span', { class: 'avatar', style: { width: '24px', height: '24px', fontSize: '0.62rem' } }, initials(mb.name || mb.email)), mb.name || '', isMe ? badge('You', 'badge-accent') : null)),
            h('td', { class: 'muted' }, mb.email),
            h('td', null, roleCell),
            owner ? h('td', { class: 'actions' }, isMe ? null : iconButton('trash', 'Remove ' + (mb.name || mb.email), function () {
              confirmDialog({
                title: 'Remove member?',
                message: (mb.name || mb.email) + ' will lose access to ' + ws.name + '. Their account stays, and you can invite them again later.',
                confirmLabel: 'Remove',
                busyLabel: 'Removing…',
                action: async function () {
                  await api('DELETE', '/api/workspaces/' + ws.id + '/members/' + mb.user_id);
                  toast((mb.name || mb.email) + ' removed');
                  loadMembers();
                }
              });
            }, { danger: true })) : null);
        })))));
    }

    var pendingBox = h('div');
    async function loadPending() {
      var list;
      try {
        list = await api('GET', '/api/workspaces/' + ws.id + '/invitations');
      } catch (e) {
        if (!ctx.alive()) return;
        pendingBox.textContent = '';
        pendingBox.appendChild(errorCallout(e, loadPending));
        return;
      }
      if (!ctx.alive()) return;
      pendingBox.textContent = '';
      if (!list.length) return;
      pendingBox.appendChild(h('div', { class: 'divider' }));
      pendingBox.appendChild(h('div', { class: 'card-title' }, 'Waiting for an answer', helpIcon('These people were invited but have not accepted yet. An invitation to an email with no account waits until someone signs up with that email.')));
      pendingBox.appendChild(h('div', { class: 'table-scroll' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, 'Email'), h('th', null, 'Role'), h('th', null, 'Invited'), h('th', { class: 'actions' }, h('span', { class: 'sr-only' }, 'Actions')))),
        h('tbody', null, list.map(function (inv) {
          return h('tr', null,
            h('td', null, inv.email),
            h('td', null, roleBadge(inv.role)),
            h('td', { class: 'muted' }, fmtDate(inv.created_at) + (inv.invited_by ? ' by ' + inv.invited_by : '')),
            h('td', { class: 'actions' }, iconButton('trash', 'Cancel the invitation to ' + inv.email, function () {
              confirmDialog({
                title: 'Cancel invitation?',
                message: inv.email + ' will not be able to join ' + ws.name + ' with this invitation. You can invite them again later.',
                confirmLabel: 'Cancel invitation',
                busyLabel: 'Canceling…',
                action: async function () {
                  await api('DELETE', '/api/workspaces/' + ws.id + '/invitations/' + inv.id);
                  toast('Invitation to ' + inv.email + ' canceled');
                  loadPending();
                }
              });
            }, { danger: true })));
        })))));
    }

    if (owner) {
      var email = h('input', { type: 'email', placeholder: 'colleague@lab.org', autocomplete: 'off' });
      var role = selectEl(roleOptions, 'editor', { 'aria-label': 'Role for the new member' });
      var addBtn = button('Invite', { cls: 'btn-accent', icon: 'plus' });
      var addErr = h('div', { class: 'field-error', role: 'alert', hidden: true });
      var add = async function () {
        formError(addErr, null);
        var e1 = email.value.trim();
        if (!validEmail(e1)) { formError(addErr, 'Enter the email address of the person to invite.'); email.focus(); return; }
        setBusy(addBtn, true, 'Inviting…');
        try {
          await api('POST', '/api/workspaces/' + ws.id + '/invitations', { email: e1, role: role.value });
          toast('Invitation recorded for ' + e1);
          email.value = '';
          loadPending();
        } catch (e) {
          if (e.status !== 401) formError(addErr, e.message);
        } finally {
          setBusy(addBtn, false);
        }
      };
      addBtn.addEventListener('click', add);
      email.addEventListener('keydown', function (e) { if (e.key === 'Enter') add(); });
      membersCard.appendChild(pendingBox);
      membersCard.appendChild(h('div', { class: 'divider' }));
      membersCard.appendChild(h('div', { class: 'inline-form' },
        field('Invite by email', email),
        h('div', { class: 'form-row narrow' }, h('label', { class: 'form-label', for: role.id = uid('f') }, 'Role'), role),
        addBtn));
      membersCard.appendChild(h('div', { class: 'hint' }, 'They join when they accept the invitation after signing in to BOB with this email. BOB does not send email, so let them know yourself.'));
      membersCard.appendChild(addErr);
    } else {
      membersCard.appendChild(h('div', { class: 'readonly-note', style: { marginTop: '12px', marginBottom: '0' } }, icon('lock'), OWNER_REASON + ' Owners add and remove members.'));
    }

    if (owner) {
      view.appendChild(h('section', { class: 'card' },
        h('div', { class: 'card-title' }, 'Delete workspace'),
        h('p', { class: 'muted', style: { fontSize: '0.88rem', marginBottom: '14px' } }, 'Deletes the workspace with all of its investigations, studies, samples, assays, raw files, and mappings. Members keep their accounts.'),
        button('Delete workspace…', { cls: 'btn-danger', icon: 'trash', onClick: function () { deleteWorkspaceModal(ws); } })));
    }

    await Promise.all([loadMembers(), owner ? loadPending() : null]);
  }

  function deleteWorkspaceModal(ws) {
    var typed = h('input', { type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder: ws.name });
    var ctl = openModal({
      title: 'Delete ' + ws.name + '?',
      icon: 'warning',
      body: h('div', null,
        h('p', { class: 'modal-text' }, 'This permanently deletes the workspace and everything in it. It cannot be undone. To confirm, type ', h('strong', null, ws.name), ' below.'),
        field('Workspace name', typed)),
      actions: [
        { label: 'Cancel', cls: 'btn-quiet' },
        {
          label: 'Delete workspace', cls: 'btn-danger-solid', primary: true, busyLabel: 'Deleting…',
          onClick: async function (m) {
            if (typed.value.trim() !== ws.name) { m.setError('Type the workspace name exactly as shown to confirm.'); typed.focus(); return false; }
            await api('DELETE', '/api/workspaces/' + ws.id);
            state.invCache.clear();
            state.wsId = null;
            await refreshMe();
            toast('Workspace deleted');
            showWorkspace(true);
          }
        }
      ]
    });
    var del = ctl.primary();
    del.disabled = true;
    typed.addEventListener('input', function () { del.disabled = typed.value.trim() !== ws.name; });
  }

  /* ===================================================================
     Account
     =================================================================== */

  async function viewAccount(view, ctx) {
    var user = state.me.user;

    var name = h('input', { type: 'text', value: user.name || '', maxlength: '120', autocomplete: 'name' });
    var email = h('input', { type: 'email', value: user.email || '', readonly: true });
    var saveName = button('Save', { cls: 'btn-accent' });
    var nameErr = h('div', { class: 'field-error', role: 'alert', hidden: true });
    saveName.addEventListener('click', async function () {
      formError(nameErr, null);
      var n = name.value.trim();
      if (!n) { formError(nameErr, 'Your name cannot be empty.'); return; }
      setBusy(saveName, true, 'Saving…');
      try {
        var res = await api('PATCH', '/api/auth/me', { name: n });
        state.me.user = (res && res.user) || Object.assign({}, state.me.user, { name: n });
        renderHeader();
        toast('Profile saved');
      } catch (e) {
        if (e.status !== 401) formError(nameErr, e.message);
      } finally {
        setBusy(saveName, false);
      }
    });
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Profile'),
      h('div', { class: 'form-grid' },
        field('Name', name),
        field('Email', email, { hint: 'Your email is your sign-in name and cannot be changed here.' })),
      nameErr,
      h('div', { class: 'form-actions' }, saveName),
      h('div', { class: 'page-meta' }, user.created_at ? h('span', null, 'Member since ' + fmtDate(user.created_at)) : null)));

    view.appendChild(synbiohubCard(ctx));

    if (!systemTransparencySettingWorks()) {
      var rt = toggleSwitch('Reduce transparency', store('bob.reduceTransparency') === true, {
        help: 'Makes bars, menus, and cards solid instead of frosted. Most browsers follow the system setting for this; this one does not, so the switch is offered here. It applies to this browser only.',
        onChange: function (on) { store('bob.reduceTransparency', on); applyTransparencyChoice(); }
      });
      view.appendChild(h('section', { class: 'card' }, h('div', { class: 'card-title' }, 'Display'), rt.row));
    }

    var cur = h('input', { type: 'password', autocomplete: 'current-password' });
    var next = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'At least 8 characters' });
    var again = h('input', { type: 'password', autocomplete: 'new-password' });
    var pwBtn = button('Change password', { cls: 'btn-accent' });
    var pwErr = h('div', { class: 'field-error', role: 'alert', hidden: true });
    var revokeAll = toggleSwitch('Also revoke all API tokens', true, { help: 'Recommended if someone else may know your password: any token they created stops working. Leave it off to keep your scripts running.' });
    pwBtn.addEventListener('click', async function () {
      formError(pwErr, null);
      if (!cur.value) { formError(pwErr, 'Enter your current password.'); cur.focus(); return; }
      if (next.value.length < 8) { formError(pwErr, 'The new password needs at least 8 characters.'); next.focus(); return; }
      if (next.value !== again.value) { formError(pwErr, 'The new passwords do not match.'); again.focus(); return; }
      setBusy(pwBtn, true, 'Changing…');
      try {
        var revoke = revokeAll.input.checked;
        await api('PATCH', '/api/auth/me', { current_password: cur.value, new_password: next.value, revoke_tokens: revoke }, { authCall: true });
        cur.value = next.value = again.value = '';
        if (revoke) { revealedId = null; reveal.textContent = ''; loadTokens(); }
        toast(revoke ? 'Password changed. Other devices were signed out and your API tokens revoked.' : 'Password changed. Other devices were signed out.');
      } catch (e) {
        formError(pwErr, e.status === 401 || e.status === 403 ? (e.message || 'The current password is not correct.') : e.message);
      } finally {
        setBusy(pwBtn, false);
      }
    });
    var everywhereBtn = button('Sign out everywhere', { cls: 'btn-quiet' });
    everywhereBtn.addEventListener('click', async function () {
      var ok = await confirmDialog({
        title: 'Sign out everywhere?',
        message: 'This ends every session signed in to your account, including this one. API tokens keep working; revoke them below if needed.',
        confirmLabel: 'Sign out everywhere',
        busyLabel: 'Signing out…',
        action: function () { return api('POST', '/api/auth/logout-all', undefined, { authCall: true }); }
      });
      if (!ok) return;
      endSession('You are signed out on every device.');
    });
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'Password'),
      h('div', { class: 'form-grid' },
        field('Current password', cur, { cls: 'span-2' }),
        field('New password', next),
        field('Repeat new password', again)),
      revokeAll.row,
      pwErr,
      h('div', { class: 'form-actions' }, everywhereBtn, pwBtn)));

    var tokenList = h('div', null, skeleton(1));
    var tokenName = h('input', { type: 'text', placeholder: 'e.g. Analysis notebook', maxlength: '120' });
    var createBtn = button('Create token', { cls: 'btn-accent', icon: 'plus' });
    var tokErr = h('div', { class: 'field-error', role: 'alert', hidden: true });
    var reveal = h('div');
    var revealedId = null;
    view.appendChild(h('section', { class: 'card' },
      h('div', { class: 'card-title' }, 'API tokens', helpIcon('Tokens let scripts and the BOB Python package use the API as you, with your access. Create one per script so you can revoke it on its own.')),
      reveal,
      tokenList,
      h('div', { class: 'divider' }),
      h('div', { class: 'inline-form' }, field('New token name', tokenName), createBtn),
      tokErr));

    async function loadTokens() {
      var tokens;
      try {
        tokens = await api('GET', '/api/auth/tokens');
      } catch (e) {
        if (!ctx.alive()) return;
        tokenList.textContent = '';
        tokenList.appendChild(errorCallout(e, loadTokens));
        return;
      }
      if (!ctx.alive()) return;
      tokenList.textContent = '';
      if (!tokens.length) {
        tokenList.appendChild(h('p', { class: 'muted', style: { fontSize: '0.86rem' } }, 'No tokens yet. Create one to use BOB from a script.'));
        return;
      }
      tokenList.appendChild(h('div', { class: 'table-scroll' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', null, 'Created'), h('th', null, 'Last used'), h('th', { class: 'actions' }, h('span', { class: 'sr-only' }, 'Actions')))),
        h('tbody', null, tokens.map(function (t) {
          return h('tr', null,
            h('td', null, h('span', { class: 'cell-name' }, icon('key'), t.name)),
            h('td', { class: 'muted' }, fmtDate(t.created_at)),
            h('td', { class: 'muted' }, t.last_used_at ? fmtDateTime(t.last_used_at) : 'Never'),
            h('td', { class: 'actions' }, iconButton('trash', 'Revoke ' + t.name, function () {
              confirmDialog({
                title: 'Revoke token?',
                message: 'Scripts using “' + t.name + '” will stop working immediately.',
                confirmLabel: 'Revoke token',
                busyLabel: 'Revoking…',
                action: async function () {
                  await api('DELETE', '/api/auth/tokens/' + t.id);
                  if (String(t.id) === String(revealedId)) { revealedId = null; reveal.textContent = ''; }
                  toast('Token revoked');
                  loadTokens();
                }
              });
            }, { danger: true })));
        })))));
    }

    var create = async function () {
      formError(tokErr, null);
      var n = tokenName.value.trim();
      if (!n) { formError(tokErr, 'Name the token after the script or machine that will use it.'); tokenName.focus(); return; }
      setBusy(createBtn, true, 'Creating…');
      try {
        var res = await api('POST', '/api/auth/tokens', { name: n });
        tokenName.value = '';
        var input = h('input', { type: 'text', readonly: true, value: res.token, 'aria-label': 'New API token' });
        input.addEventListener('focus', function () { input.select(); });
        revealedId = res.id;
        reveal.textContent = '';
        reveal.appendChild(h('div', { class: 'token-box', role: 'status' },
          h('div', { class: 'callout-title', style: { display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--warning)' } }, icon('warning'), 'Copy this token now. It will not be shown again.'),
          h('div', { class: 'hint', style: { marginTop: '4px' } }, 'Store it like a password. Anyone with it can use BOB as you. If it is lost, revoke it and create a new one.'),
          h('div', { class: 'token-row' }, input, copyButton(res.token, 'token')),
          h('div', { class: 'form-actions', style: { marginTop: '10px' } }, button('I saved it', { cls: 'btn-sm btn-quiet', onClick: function () { reveal.textContent = ''; } }))));
        input.focus();
        toast('Token ' + (res.name || n) + ' created');
        loadTokens();
      } catch (e) {
        if (e.status !== 401) formError(tokErr, e.message);
      } finally {
        setBusy(createBtn, false);
      }
    };
    createBtn.addEventListener('click', create);
    tokenName.addEventListener('keydown', function (e) { if (e.key === 'Enter') create(); });

    await loadTokens();
  }

  /* ===================================================================
     Boot
     =================================================================== */

  /* Safari and Firefox ignore prefers-reduced-transparency: neither of its values ever matches. */
  function systemTransparencySettingWorks() {
    return !!window.matchMedia && (matchMedia('(prefers-reduced-transparency: reduce)').matches || matchMedia('(prefers-reduced-transparency: no-preference)').matches);
  }

  function applyTransparencyChoice() {
    document.documentElement.classList.toggle('reduce-transparency', !systemTransparencySettingWorks() && store('bob.reduceTransparency') === true);
  }

  function bootFailed(e) {
    var spinner = $('#boot .spinner');
    if (spinner) spinner.remove();
    $('#boot-text').textContent = 'BOB could not start in this browser (' + (e && e.message ? e.message : String(e)) + '). Reload the page. If this message comes back, reload without the cache: Ctrl+Shift+R, or Cmd+Shift+R on a Mac.';
  }

  async function boot() {
    var slow = setTimeout(function () { $('#boot-text').textContent = 'Still connecting to BOB. If nothing changes, reload the page.'; }, 8000);
    try {
      applyTransparencyChoice();
      bindTooltips();
      bindAuth();
      bindHeader();
      bindRouter();
    } catch (e) {
      clearTimeout(slow);
      bootFailed(e);
      return;
    }
    try {
      state.health = await api('GET', '/health', undefined, { authCall: true });
    } catch (e) {
      state.health = null;
    }
    try {
      await enterApp();
    } catch (e) {
      if (e.status === 401) showAuth();
      else if (e.status === 0) showAuth('Cannot reach the BOB server. Check that it is running, then reload this page.', true);
      else if (e instanceof ApiError) showAuth('The server answered with an error: ' + e.message, true);
      else bootFailed(e);
    } finally {
      clearTimeout(slow);
    }
  }

  window.addEventListener('DOMContentLoaded', boot);
})();
