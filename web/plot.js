/* BOB charts and plate map: hand-drawn SVG and DOM, no dependencies. */
(function () {
  'use strict';

  var SVGNS = 'http://www.w3.org/2000/svg';
  var ROW_LETTERS = 'ABCDEFGHIJKLMNOP';
  var SLOTS = 8;
  var CYCLE_DASH = ['', '8 4', '2 3'];

  function svg(tag, attrs, parent) {
    var node = document.createElementNS(SVGNS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) node.setAttribute(k, attrs[k]);
      }
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function isControl(type) {
    return type === 'medium' || type === 'untransformed';
  }

  /* --- Colors ---------------------------------------------------------- */

  function slotStyle(i) {
    return {
      color: 'var(--series-' + ((i % SLOTS) + 1) + ')',
      dash: CYCLE_DASH[Math.floor(i / SLOTS) % CYCLE_DASH.length],
      isControl: false
    };
  }

  function controlStyle(type) {
    return type === 'untransformed'
      ? { color: 'var(--control-untransformed)', dash: '7 4', isControl: true, badge: 'U' }
      : { color: 'var(--control-medium)', dash: '2 3', isControl: true, badge: 'M' };
  }

  /* Colors follow the sample, in the order the study lists them, so a sample
     keeps its color in the plate map, the chart and the bar chart. */
  function sampleStyles(samples) {
    var map = new Map();
    var k = 0;
    (samples || []).forEach(function (s) {
      var st;
      if (isControl(s.sample_type)) {
        st = controlStyle(s.sample_type);
      } else {
        st = slotStyle(k);
        k += 1;
        st.badge = String(k);
      }
      st.sample = s;
      map.set(s.id, st);
    });
    return map;
  }

  /* --- Numbers ----------------------------------------------------------- */

  function fmt(v, digits) {
    if (v === null || v === undefined || !isFinite(v)) return 'n/a';
    var a = Math.abs(v);
    if (digits !== undefined) return v.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    if (a === 0) return '0';
    if (a >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
    if (a >= 100) return v.toLocaleString('en-US', { maximumFractionDigits: 1 });
    if (a >= 1) return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
    return Number(v.toPrecision(3)).toString();
  }

  function niceStep(span, count) {
    var raw = span / Math.max(1, count);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
    return step * mag;
  }

  function niceTicks(lo, hi, count) {
    if (!isFinite(lo) || !isFinite(hi)) return [0, 1];
    if (lo === hi) {
      var pad = Math.abs(lo) * 0.1 || 1;
      lo -= pad;
      hi += pad;
    }
    var step = niceStep(hi - lo, count);
    var start = Math.floor(lo / step) * step;
    var end = Math.ceil(hi / step) * step;
    var ticks = [];
    for (var v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
    return ticks;
  }

  function tickLabel(v, step) {
    var a = Math.abs(v);
    if (a >= 10000) {
      if (a >= 1e6) return fmt(v / 1e6, 2) + 'M';
      return fmt(v / 1000, step >= 1000 ? 0 : 1) + 'k';
    }
    var decimals = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(step)));
    return v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  function nearestIndex(arr, t) {
    if (!arr || !arr.length) return -1;
    var lo = 0, hi = arr.length - 1;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (arr[mid] < t) lo = mid; else hi = mid;
    }
    return Math.abs(arr[lo] - t) <= Math.abs(arr[hi] - t) ? lo : hi;
  }

  function swatchEl(style) {
    var s = el('span', 'swatch' + (style.isControl ? ' control' : ''));
    if (style.isControl) s.style.borderColor = style.color;
    else s.style.background = style.color;
    return s;
  }

  function legendKey(style) {
    var k = svg('svg', { class: 'legend-key', viewBox: '0 0 18 10', 'aria-hidden': 'true' });
    svg('rect', { x: 0, y: 1, width: 18, height: 8, rx: 2, fill: style.color, 'fill-opacity': style.isControl ? 0.1 : 0.18 }, k);
    svg('line', { x1: 1, y1: 5, x2: 17, y2: 5, stroke: style.color, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-dasharray': style.dash || null }, k);
    return k;
  }

  function observeWidth(root, cb) {
    var last = -1, raf = 0;
    var ro = new ResizeObserver(function () {
      var w = Math.round(root.clientWidth);
      if (w === last) return;
      last = w;
      if (!raf) raf = requestAnimationFrame(function () { raf = 0; cb(); });
    });
    ro.observe(root);
    return function () { ro.disconnect(); };
  }

  function placeTip(root, tip, px, py) {
    var rw = root.clientWidth;
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var left = px + 16;
    if (left + tw > rw) left = px - tw - 16;
    if (left < 0) left = Math.max(0, Math.min(rw - tw, px - tw / 2));
    var top = Math.max(0, py - th / 2);
    var maxTop = Math.max(0, root.clientHeight - th);
    if (top > maxTop) top = maxTop;
    tip.style.left = Math.round(left) + 'px';
    tip.style.top = Math.round(top) + 'px';
  }

  /* --- Line chart with SD bands ------------------------------------------ */

  /* groups: [{key, label, times, mean, sd, n, positions, style}] */
  function lineChart(root, initial) {
    root.textContent = '';
    root.classList.add('chart');
    var svgEl = svg('svg', { role: 'img' }, root);
    var tip = el('div', 'chart-tip');
    tip.setAttribute('aria-hidden', 'true');
    root.appendChild(tip);
    var legend = el('div', 'legend');
    legend.setAttribute('aria-label', 'Series; select to show or hide');
    root.appendChild(legend);
    var live = el('div', 'sr-only');
    live.setAttribute('aria-live', 'polite');
    root.appendChild(live);

    var opts = initial;
    var hidden = new Set();
    var geom = null;
    var hoverIdx = -1;

    function visibleGroups() {
      return opts.groups.filter(function (g) { return !hidden.has(g.key); });
    }

    function refTimes() {
      var best = [];
      opts.groups.forEach(function (g) { if ((g.times || []).length > best.length) best = g.times; });
      return best;
    }

    function render() {
      svgEl.textContent = '';
      var width = Math.max(280, root.clientWidth);
      var height = Math.round(Math.min(430, Math.max(260, width * 0.48)));
      svgEl.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
      svgEl.setAttribute('height', height);
      svgEl.setAttribute('aria-label', (opts.yLabel || 'Value') + ' over ' + (opts.xLabel || 'time') + ', ' + opts.groups.length + ' groups');

      var groups = opts.groups;
      var vis = visibleGroups();
      var x0 = Infinity, x1 = -Infinity;
      groups.forEach(function (g) {
        (g.times || []).forEach(function (t) {
          if (t === null || t === undefined) return;
          if (t < x0) x0 = t;
          if (t > x1) x1 = t;
        });
      });
      if (!isFinite(x0)) { x0 = 0; x1 = 1; }
      if (x0 === x1) x1 = x0 + 1;

      var y0 = Infinity, y1 = -Infinity;
      vis.forEach(function (g) {
        (g.mean || []).forEach(function (m, i) {
          if (m === null || m === undefined) return;
          var s = (g.sd && g.sd[i]) || 0;
          if (m - s < y0) y0 = m - s;
          if (m + s > y1) y1 = m + s;
        });
      });
      if (!isFinite(y0)) { y0 = 0; y1 = 1; }
      y0 = Math.min(0, y0);
      y1 = Math.max(0, y1);
      var yTicks = niceTicks(y0, y1, height > 320 ? 6 : 5);
      y0 = yTicks[0];
      y1 = yTicks[yTicks.length - 1];
      var yStep = yTicks.length > 1 ? yTicks[1] - yTicks[0] : 1;
      var yLabels = yTicks.map(function (v) { return tickLabel(v, yStep); });
      var maxLabel = yLabels.reduce(function (m, s) { return Math.max(m, s.length); }, 1);

      var m = { top: 12, right: 18, bottom: 44, left: Math.max(46, maxLabel * 6.6 + 28) };
      var pw = width - m.left - m.right;
      var ph = height - m.top - m.bottom;
      var sx = function (t) { return m.left + (t - x0) / (x1 - x0) * pw; };
      var sy = function (v) { return m.top + (1 - (v - y0) / (y1 - y0)) * ph; };
      geom = { m: m, pw: pw, ph: ph, sx: sx, sy: sy, x0: x0, x1: x1 };

      var grid = svg('g', { class: 'grid' }, svgEl);
      var ticksG = svg('g', { class: 'tick' }, svgEl);
      yTicks.forEach(function (v, i) {
        var y = Math.round(sy(v)) + 0.5;
        svg('line', { x1: m.left, x2: m.left + pw, y1: y, y2: y }, grid);
        var t = svg('text', { x: m.left - 8, y: y, 'text-anchor': 'end', 'dominant-baseline': 'middle' }, ticksG);
        t.textContent = yLabels[i];
      });
      var xTicks = niceTicks(x0, x1, Math.max(3, Math.floor(pw / 80))).filter(function (v) { return v >= x0 - 1e-9 && v <= x1 + 1e-9; });
      var xStep = xTicks.length > 1 ? xTicks[1] - xTicks[0] : 1;
      xTicks.forEach(function (v) {
        var x = Math.round(sx(v)) + 0.5;
        svg('line', { class: 'axis-line', x1: x, x2: x, y1: m.top + ph, y2: m.top + ph + 5 }, svgEl);
        var t = svg('text', { x: x, y: m.top + ph + 18, 'text-anchor': 'middle' }, ticksG);
        t.textContent = tickLabel(v, xStep);
      });
      svg('line', { class: 'axis-line', x1: m.left, x2: m.left + pw, y1: Math.round(sy(y0)) + 0.5, y2: Math.round(sy(y0)) + 0.5 }, svgEl);
      if (y0 < 0 && y1 > 0) {
        svg('line', { class: 'axis-line', x1: m.left, x2: m.left + pw, y1: Math.round(sy(0)) + 0.5, y2: Math.round(sy(0)) + 0.5, 'stroke-dasharray': '2 3' }, svgEl);
      }
      var xl = svg('text', { class: 'axis-label', x: m.left + pw / 2, y: height - 6, 'text-anchor': 'middle' }, svgEl);
      xl.textContent = opts.xLabel || 'Time (h)';
      var yl = svg('text', { class: 'axis-label', x: 0, y: 0, 'text-anchor': 'middle', transform: 'translate(12 ' + (m.top + ph / 2) + ') rotate(-90)' }, svgEl);
      yl.textContent = opts.yLabel || 'Value';

      var clipId = 'clip-' + Math.random().toString(36).slice(2, 9);
      var defs = svg('defs', null, svgEl);
      var cp = svg('clipPath', { id: clipId }, defs);
      svg('rect', { x: m.left, y: m.top - 2, width: pw, height: ph + 4 }, cp);

      var seriesLayer = svg('g', { 'clip-path': 'url(#' + clipId + ')' }, svgEl);
      /* Controls first so the samples draw over them. */
      var ordered = vis.slice().sort(function (a, b) { return (b.style.isControl ? 1 : 0) - (a.style.isControl ? 1 : 0); });
      ordered.forEach(function (g) {
        var gEl = svg('g', { class: 'series', 'data-key': g.key }, seriesLayer);
        var times = g.times || [], mean = g.mean || [], sd = g.sd || [];
        var band = '', line = '';
        var upper = [], lower = [];
        var flushBand = function () {
          if (upper.length > 1) band += 'M' + upper.join('L') + 'L' + lower.reverse().join('L') + 'Z';
          upper = [];
          lower = [];
        };
        var pen = false;
        for (var i = 0; i < times.length; i++) {
          var mv = mean[i], t = times[i];
          if (mv === null || mv === undefined || t === null || t === undefined) {
            pen = false;
            flushBand();
            continue;
          }
          var X = sx(t).toFixed(1), Y = sy(mv).toFixed(1);
          line += (pen ? 'L' : 'M') + X + ' ' + Y;
          pen = true;
          var s = sd[i];
          if (s === null || s === undefined) {
            flushBand();
          } else {
            upper.push(X + ' ' + sy(mv + s).toFixed(1));
            lower.push(X + ' ' + sy(mv - s).toFixed(1));
          }
        }
        flushBand();
        if (band) svg('path', { class: 'series-band', d: band, fill: g.style.color, 'fill-opacity': g.style.isControl ? 0.08 : 0.15 }, gEl);
        if (line) {
          svg('path', {
            class: 'series-line', d: line, stroke: g.style.color,
            'stroke-dasharray': g.style.dash || null,
            'stroke-opacity': g.style.isControl ? 0.75 : 1,
            'stroke-width': g.style.isControl ? 1.6 : 2
          }, gEl);
        }
      });

      var hover = svg('g', { class: 'hover-layer' }, svgEl);
      geom.cross = svg('line', { class: 'crosshair', y1: m.top, y2: m.top + ph, visibility: 'hidden' }, hover);
      geom.dots = svg('g', null, hover);
      var overlay = svg('rect', {
        class: 'overlay', x: m.left, y: m.top, width: pw, height: ph, tabindex: 0,
        'aria-label': 'Chart values. Use the left and right arrow keys to step through time points.'
      }, svgEl);
      overlay.addEventListener('pointermove', onMove);
      overlay.addEventListener('pointerdown', onMove);
      overlay.addEventListener('pointerleave', hideHover);
      overlay.addEventListener('keydown', onKey);
      overlay.addEventListener('blur', hideHover);
      if (hoverIdx >= 0) showAt(hoverIdx, null);
    }

    function pointerX(e) {
      var r = svgEl.getBoundingClientRect();
      var vb = svgEl.viewBox.baseVal;
      var scale = vb.width / r.width;
      return { x: (e.clientX - r.left) * scale, y: (e.clientY - r.top) * scale, scale: scale };
    }

    function onMove(e) {
      if (!geom) return;
      var p = pointerX(e);
      var t = geom.x0 + (p.x - geom.m.left) / geom.pw * (geom.x1 - geom.x0);
      var ref = refTimes();
      var idx = nearestIndex(ref, t);
      if (idx < 0) return;
      hoverIdx = idx;
      showAt(idx, p.y / p.scale);
    }

    function onKey(e) {
      var ref = refTimes();
      if (!ref.length) return;
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        var step = e.shiftKey ? 10 : 1;
        if (hoverIdx < 0) hoverIdx = 0;
        else hoverIdx = Math.max(0, Math.min(ref.length - 1, hoverIdx + (e.key === 'ArrowRight' ? step : -step)));
        showAt(hoverIdx, null);
        live.textContent = summaryAt(hoverIdx);
      } else if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        hoverIdx = e.key === 'Home' ? 0 : ref.length - 1;
        showAt(hoverIdx, null);
        live.textContent = summaryAt(hoverIdx);
      } else if (e.key === 'Escape') {
        hideHover();
      }
    }

    function valueText(g, i) {
      var mv = g.mean[i], s = g.sd ? g.sd[i] : null;
      if (mv === null || mv === undefined) return 'n/a';
      return fmt(mv) + (s !== null && s !== undefined ? ' ± ' + fmt(s) : '');
    }

    function summaryAt(idx) {
      var t = refTimes()[idx];
      var parts = visibleGroups().map(function (g) {
        var i = nearestIndex(g.times, t);
        return g.label + ' ' + (i < 0 ? 'n/a' : valueText(g, i));
      });
      return fmt(t, 2) + ' hours. ' + parts.join('; ');
    }

    function showAt(idx, pyScreen) {
      if (!geom) return;
      var ref = refTimes();
      var t = ref[idx];
      if (t === undefined) return;
      var x = geom.sx(t);
      geom.cross.setAttribute('x1', x);
      geom.cross.setAttribute('x2', x);
      geom.cross.setAttribute('visibility', 'visible');
      geom.dots.textContent = '';
      tip.textContent = '';
      tip.appendChild(el('div', 'tip-head', fmt(t, 2) + ' h'));
      var ys = [];
      visibleGroups().forEach(function (g) {
        var i = nearestIndex(g.times, t);
        var row = el('div', 'tip-row');
        row.appendChild(swatchEl(g.style));
        row.appendChild(el('span', 'tip-name', g.label));
        var val = el('span', 'tip-val', i < 0 ? 'n/a' : valueText(g, i));
        var n = i >= 0 && g.n ? g.n[i] : null;
        if (n !== null && n !== undefined) val.appendChild(el('span', 'tip-n', '  n=' + n));
        row.appendChild(val);
        tip.appendChild(row);
        if (i >= 0 && g.mean[i] !== null && g.mean[i] !== undefined) {
          var y = geom.sy(g.mean[i]);
          ys.push(y);
          svg('circle', { class: 'hover-dot', cx: geom.sx(g.times[i]), cy: y, r: 4, fill: g.style.color }, geom.dots);
        }
      });
      tip.classList.add('visible');
      var r = svgEl.getBoundingClientRect();
      var vb = svgEl.viewBox.baseVal;
      var k = r.width / vb.width;
      var py = pyScreen !== null && pyScreen !== undefined ? pyScreen : (ys.length ? Math.min.apply(null, ys) * k : geom.m.top * k);
      placeTip(root, tip, x * k, py);
    }

    function hideHover() {
      hoverIdx = -1;
      tip.classList.remove('visible');
      if (geom) {
        geom.cross.setAttribute('visibility', 'hidden');
        geom.dots.textContent = '';
      }
    }

    function renderLegend() {
      legend.textContent = '';
      opts.groups.forEach(function (g) {
        var b = el('button', 'legend-item');
        b.type = 'button';
        b.setAttribute('aria-pressed', hidden.has(g.key) ? 'false' : 'true');
        b.title = hidden.has(g.key) ? 'Show ' + g.label : 'Hide ' + g.label;
        b.appendChild(legendKey(g.style));
        b.appendChild(el('span', null, g.label));
        if (g.nLabel) b.appendChild(el('span', 'legend-n', g.nLabel));
        b.addEventListener('click', function () {
          if (hidden.has(g.key)) hidden.delete(g.key); else hidden.add(g.key);
          renderLegend();
          render();
        });
        b.addEventListener('mouseenter', function () { setFocus(g.key); });
        b.addEventListener('mouseleave', function () { setFocus(null); });
        b.addEventListener('focus', function () { setFocus(g.key); });
        b.addEventListener('blur', function () { setFocus(null); });
        legend.appendChild(b);
      });
    }

    function setFocus(key) {
      if (!key || hidden.has(key)) {
        root.classList.remove('focus-mode');
        return;
      }
      root.classList.add('focus-mode');
      Array.prototype.forEach.call(svgEl.querySelectorAll('.series'), function (s) {
        s.classList.toggle('focused', s.getAttribute('data-key') === key);
      });
    }

    var stop = observeWidth(root, render);
    renderLegend();
    render();

    return {
      update: function (next) {
        opts = next;
        var keys = new Set(next.groups.map(function (g) { return g.key; }));
        hidden.forEach(function (k) { if (!keys.has(k)) hidden.delete(k); });
        hideHover();
        renderLegend();
        render();
      },
      destroy: function () { stop(); root.textContent = ''; }
    };
  }

  /* --- Horizontal bar chart: mean ± SD ------------------------------------ */

  /* groups: [{key, label, mean, sd, n, style}] */
  function barChart(root, initial) {
    root.textContent = '';
    root.classList.add('chart', 'bar-chart');
    var svgEl = svg('svg', { role: 'img' }, root);
    var tip = el('div', 'chart-tip');
    tip.setAttribute('aria-hidden', 'true');
    root.appendChild(tip);
    var opts = initial;

    function render() {
      svgEl.textContent = '';
      var groups = opts.groups;
      var width = Math.max(260, root.clientWidth);
      var rowH = 30, top = 6, bottom = 30;
      var height = top + groups.length * rowH + bottom;
      svgEl.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
      svgEl.setAttribute('height', height);
      svgEl.setAttribute('aria-label', 'Mean expression per group' + (opts.unitLabel ? ', ' + opts.unitLabel : ''));

      var labelW = Math.min(150, Math.max(80, width * 0.28));
      var valueW = Math.min(118, Math.max(84, width * 0.24));
      var px0 = labelW + 10, px1 = width - valueW;
      var lo = 0, hi = 0;
      groups.forEach(function (g) {
        if (g.mean === null || g.mean === undefined) return;
        var s = g.sd || 0;
        lo = Math.min(lo, g.mean - s);
        hi = Math.max(hi, g.mean + s);
      });
      if (lo === hi) hi = lo + 1;
      var ticks = niceTicks(lo, hi, Math.max(2, Math.floor((px1 - px0) / 70)));
      lo = ticks[0];
      hi = ticks[ticks.length - 1];
      var step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
      var sx = function (v) { return px0 + (v - lo) / (hi - lo) * (px1 - px0); };

      var grid = svg('g', { class: 'grid' }, svgEl);
      var tickG = svg('g', { class: 'tick' }, svgEl);
      ticks.forEach(function (v) {
        var x = Math.round(sx(v)) + 0.5;
        svg('line', { x1: x, x2: x, y1: top, y2: top + groups.length * rowH }, grid);
        var t = svg('text', { x: x, y: height - 10, 'text-anchor': 'middle' }, tickG);
        t.textContent = tickLabel(v, step);
      });
      var zx = Math.round(sx(0)) + 0.5;
      svg('line', { class: 'zero-line', x1: zx, x2: zx, y1: top - 2, y2: top + groups.length * rowH + 2 }, svgEl);

      var maxChars = Math.max(6, Math.floor(labelW / 7));
      groups.forEach(function (g, i) {
        var cy = top + i * rowH + rowH / 2;
        var row = svg('g', { class: 'bar-row' }, svgEl);
        var hit = svg('rect', { class: 'bar-hit', x: 0, y: cy - rowH / 2, width: width, height: rowH, rx: 6 }, row);
        var label = svg('text', { class: 'bar-label', x: labelW, y: cy, 'text-anchor': 'end', 'dominant-baseline': 'middle' }, row);
        label.textContent = g.label.length > maxChars ? g.label.slice(0, maxChars - 1) + '…' : g.label;
        svg('title', null, label).textContent = g.label;
        var vtext = svg('text', { class: 'bar-value', x: width - 2, y: cy, 'text-anchor': 'end', 'dominant-baseline': 'middle' }, row);
        if (g.mean === null || g.mean === undefined) {
          vtext.textContent = 'No data';
        } else {
          var xa = sx(Math.min(0, g.mean)), xb = sx(Math.max(0, g.mean));
          svg('rect', {
            x: xa, y: cy - 8, width: Math.max(1, xb - xa), height: 16, rx: 4,
            fill: g.style.color, 'fill-opacity': g.style.isControl ? 0.25 : 0.9,
            stroke: g.style.isControl ? g.style.color : null,
            'stroke-dasharray': g.style.isControl ? '3 2' : null
          }, row);
          if (g.sd !== null && g.sd !== undefined && g.sd > 0) {
            var e0 = sx(g.mean - g.sd), e1 = sx(g.mean + g.sd);
            svg('line', { class: 'err', x1: e0, x2: e1, y1: cy, y2: cy }, row);
            svg('line', { class: 'err', x1: e0, x2: e0, y1: cy - 5, y2: cy + 5 }, row);
            svg('line', { class: 'err', x1: e1, x2: e1, y1: cy - 5, y2: cy + 5 }, row);
          }
          vtext.textContent = fmt(g.mean) + (g.sd !== null && g.sd !== undefined ? ' ± ' + fmt(g.sd) : '');
        }
        hit.addEventListener('pointerenter', function (e) { show(g, e); });
        hit.addEventListener('pointermove', function (e) { show(g, e); });
        hit.addEventListener('pointerleave', function () { tip.classList.remove('visible'); });
      });
    }

    function show(g, e) {
      tip.textContent = '';
      tip.appendChild(el('div', 'tip-head', g.label));
      var add = function (k, v) {
        var r = el('div', 'tip-row');
        r.style.gridTemplateColumns = '1fr auto';
        r.appendChild(el('span', 'tip-name', k));
        r.appendChild(el('span', 'tip-val', v));
        tip.appendChild(r);
      };
      add('Mean', fmt(g.mean));
      add('SD', fmt(g.sd));
      add('Wells (n)', g.n === null || g.n === undefined ? 'n/a' : String(g.n));
      tip.classList.add('visible');
      var r = root.getBoundingClientRect();
      placeTip(root, tip, e.clientX - r.left, e.clientY - r.top);
    }

    var stop = observeWidth(root, render);
    render();
    return {
      update: function (next) { opts = next; tip.classList.remove('visible'); render(); },
      destroy: function () { stop(); root.textContent = ''; }
    };
  }

  /* --- Plate map ----------------------------------------------------------- */

  function parsePos(p) {
    var m = /^([A-P])(\d{1,2})$/.exec(p || '');
    if (!m) return null;
    return { r: ROW_LETTERS.indexOf(m[1]), c: parseInt(m[2], 10) - 1 };
  }

  function posName(r, c) {
    return ROW_LETTERS[r] + (c + 1);
  }

  function plateDims(positions) {
    var rows = 8, cols = 12;
    (positions || []).forEach(function (p) {
      var q = parsePos(p);
      if (!q) return;
      rows = Math.max(rows, q.r + 1);
      cols = Math.max(cols, q.c + 1);
    });
    return { rows: rows, cols: cols };
  }

  /* opts: {positions, assignment: Map, saved: Map, styleOf(sampleId), nameOf(sampleId),
            readOnly, onSelect(Set), onHover(pos|null)} */
  function plateMap(root, opts) {
    var dims = plateDims(opts.positions);
    var hasData = new Set(opts.positions || []);
    var selection = new Set();
    var anchor = null;
    var drag = null;
    var cells = new Map();
    var focusPos = null;

    root.textContent = '';
    var plate = el('div', 'plate' + (opts.readOnly ? ' readonly' : ''));
    plate.setAttribute('role', 'grid');
    plate.setAttribute('aria-label', 'Plate map, ' + dims.rows + ' by ' + dims.cols + (opts.readOnly ? '' : '. Drag, Shift-click, or use arrow keys and Space to select wells.'));
    plate.setAttribute('aria-multiselectable', 'true');
    plate.style.gridTemplateColumns = 'var(--label-col, 22px) repeat(' + dims.cols + ', var(--well))';
    root.appendChild(plate);

    var head = el('div');
    head.setAttribute('role', 'row');
    head.style.display = 'contents';
    plate.appendChild(head);
    var corner = el('button', 'plate-corner', '');
    corner.type = 'button';
    corner.title = 'Select all wells';
    corner.setAttribute('aria-label', 'Select all wells');
    corner.appendChild(document.createTextNode('⌗'));
    corner.tabIndex = -1;
    head.appendChild(corner);
    corner.addEventListener('click', function () {
      if (opts.readOnly) return;
      var all = allWith(function () { return true; });
      setSelection(selection.size === all.length ? [] : all);
    });
    for (var c = 0; c < dims.cols; c++) {
      (function (col) {
        var b = el('button', 'plate-col', String(col + 1));
        b.type = 'button';
        b.tabIndex = -1;
        b.setAttribute('role', 'columnheader');
        b.title = 'Select column ' + (col + 1) + ' (Shift to add)';
        b.addEventListener('click', function (e) {
          if (opts.readOnly) return;
          pickLine(allWith(function (q) { return q.c === col; }), e);
        });
        head.appendChild(b);
      })(c);
    }
    for (var r = 0; r < dims.rows; r++) {
      var rowEl = el('div');
      rowEl.setAttribute('role', 'row');
      rowEl.style.display = 'contents';
      plate.appendChild(rowEl);
      (function (row) {
        var b = el('button', 'plate-row', ROW_LETTERS[row]);
        b.type = 'button';
        b.tabIndex = -1;
        b.setAttribute('role', 'rowheader');
        b.title = 'Select row ' + ROW_LETTERS[row] + ' (Shift to add)';
        b.addEventListener('click', function (e) {
          if (opts.readOnly) return;
          pickLine(allWith(function (q) { return q.r === row; }), e);
        });
        rowEl.appendChild(b);
      })(r);
      for (var cc = 0; cc < dims.cols; cc++) {
        var p = posName(r, cc);
        var w = el('div', 'well');
        w.setAttribute('role', 'gridcell');
        w.dataset.pos = p;
        w.tabIndex = -1;
        if (!hasData.has(p)) w.classList.add('nodata');
        rowEl.appendChild(w);
        cells.set(p, w);
      }
    }
    var first = (opts.positions || []).find(function (p) { return cells.has(p); });
    if (first) { cells.get(first).tabIndex = 0; focusPos = first; }

    function allWith(pred) {
      var out = [];
      cells.forEach(function (w, p) {
        if (!hasData.has(p)) return;
        if (pred(parsePos(p))) out.push(p);
      });
      return out;
    }

    function pickLine(list, e) {
      if (e.shiftKey || e.metaKey || e.ctrlKey) {
        var allIn = list.every(function (p) { return selection.has(p); });
        var next = new Set(selection);
        list.forEach(function (p) { if (allIn) next.delete(p); else next.add(p); });
        setSelection(Array.from(next));
      } else {
        setSelection(list);
      }
    }

    function rect(a, b) {
      var qa = parsePos(a), qb = parsePos(b);
      var r0 = Math.min(qa.r, qb.r), r1 = Math.max(qa.r, qb.r);
      var c0 = Math.min(qa.c, qb.c), c1 = Math.max(qa.c, qb.c);
      return allWith(function (q) { return q.r >= r0 && q.r <= r1 && q.c >= c0 && q.c <= c1; });
    }

    function setSelection(list) {
      selection = new Set(list);
      paintSelection();
      if (opts.onSelect) opts.onSelect(new Set(selection));
    }

    function paintSelection() {
      cells.forEach(function (w, p) {
        var on = selection.has(p);
        w.classList.toggle('selected', on);
        w.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }

    function paint() {
      cells.forEach(function (w, p) {
        var sid = opts.assignment.get(p);
        var st = sid ? opts.styleOf(sid) : null;
        w.classList.toggle('assigned', !!st && !st.isControl);
        w.classList.toggle('control', !!st && st.isControl);
        w.style.setProperty('--c', st ? st.color : 'transparent');
        w.textContent = st ? (st.badge || '') : '';
        var savedSid = opts.saved ? opts.saved.get(p) : sid;
        w.classList.toggle('changed', (savedSid || null) !== (sid || null));
        var name = sid ? opts.nameOf(sid) : (hasData.has(p) ? 'empty' : 'no data');
        w.setAttribute('aria-label', p + ', ' + name);
      });
      paintSelection();
    }

    function wellAt(e) {
      var t = document.elementFromPoint(e.clientX, e.clientY);
      var w = t && t.closest ? t.closest('.well') : null;
      return w && plate.contains(w) && !w.classList.contains('nodata') ? w.dataset.pos : null;
    }

    function applyDrag(cur) {
      if (!drag) return;
      var next = new Set(drag.base);
      rect(drag.start, cur).forEach(function (p) {
        if (drag.remove) next.delete(p); else next.add(p);
      });
      selection = next;
      paintSelection();
    }

    plate.addEventListener('pointerdown', function (e) {
      if (opts.readOnly || e.button > 0) return;
      var w = e.target.closest('.well');
      if (!w || w.classList.contains('nodata')) return;
      e.preventDefault();
      var p = w.dataset.pos;
      moveFocus(p, false);
      if (e.shiftKey && anchor) {
        setSelection(rect(anchor, p));
        return;
      }
      var additive = e.metaKey || e.ctrlKey;
      drag = { start: p, base: additive ? new Set(selection) : new Set(), remove: additive && selection.has(p) };
      anchor = p;
      plate.setPointerCapture(e.pointerId);
      applyDrag(p);
    });

    plate.addEventListener('pointermove', function (e) {
      var p = wellAt(e);
      if (opts.onHover) opts.onHover(p);
      if (drag && p) applyDrag(p);
    });

    function endDrag() {
      if (!drag) return;
      drag = null;
      if (opts.onSelect) opts.onSelect(new Set(selection));
    }

    plate.addEventListener('pointerup', endDrag);
    plate.addEventListener('pointercancel', endDrag);
    plate.addEventListener('pointerleave', function () { if (!drag && opts.onHover) opts.onHover(null); });

    function moveFocus(p, focus) {
      if (!cells.has(p)) return;
      if (focusPos && cells.has(focusPos)) cells.get(focusPos).tabIndex = -1;
      focusPos = p;
      var w = cells.get(p);
      w.tabIndex = 0;
      if (focus) w.focus();
      if (opts.onHover) opts.onHover(p);
    }

    plate.addEventListener('keydown', function (e) {
      var w = e.target.closest ? e.target.closest('.well') : null;
      if (!w) return;
      var q = parsePos(w.dataset.pos);
      var dr = 0, dc = 0;
      if (e.key === 'ArrowUp') dr = -1;
      else if (e.key === 'ArrowDown') dr = 1;
      else if (e.key === 'ArrowLeft') dc = -1;
      else if (e.key === 'ArrowRight') dc = 1;
      if (dr || dc) {
        e.preventDefault();
        var nr = Math.max(0, Math.min(dims.rows - 1, q.r + dr));
        var nc = Math.max(0, Math.min(dims.cols - 1, q.c + dc));
        var np = posName(nr, nc);
        moveFocus(np, true);
        if (e.shiftKey && !opts.readOnly && hasData.has(np)) {
          if (!anchor) anchor = w.dataset.pos;
          setSelection(rect(anchor, np));
        }
        return;
      }
      if (opts.readOnly) return;
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        var p = w.dataset.pos;
        if (!hasData.has(p)) return;
        if (e.shiftKey && anchor) {
          setSelection(rect(anchor, p));
        } else {
          var next = new Set(selection);
          if (next.has(p)) next.delete(p); else next.add(p);
          anchor = p;
          setSelection(Array.from(next));
        }
      } else if (e.key === 'Escape') {
        setSelection([]);
      } else if ((e.key === 'a' || e.key === 'A') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setSelection(allWith(function () { return true; }));
      }
    });

    plate.addEventListener('focusin', function (e) {
      var w = e.target.closest ? e.target.closest('.well') : null;
      if (w && opts.onHover) opts.onHover(w.dataset.pos);
    });

    paint();

    return {
      selection: function () { return new Set(selection); },
      clearSelection: function () { setSelection([]); },
      update: function (next) {
        opts.assignment = next.assignment || opts.assignment;
        opts.saved = next.saved || opts.saved;
        paint();
      }
    };
  }

  window.BOBPlot = {
    lineChart: lineChart,
    barChart: barChart,
    plateMap: plateMap,
    plateDims: plateDims,
    sampleStyles: sampleStyles,
    slotStyle: slotStyle,
    controlStyle: controlStyle,
    isControl: isControl,
    swatch: swatchEl,
    fmt: fmt
  };
})();
