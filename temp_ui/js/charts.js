/*
 * Dependency-free charts: a canvas heatmap and small SVG charts.
 * All colours come from CSS variables so charts follow the page theme.
 */
(function (FIF) {
  const RISK_COLOR = { low: 'var(--ok)', moderate: 'var(--warn)', high: 'var(--bad)' };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // ---- tooltip -----------------------------------------------------------
  function showTip(html, x, y) {
    const tip = document.getElementById('tooltip');
    tip.innerHTML = html;
    tip.style.display = 'block';
    const w = tip.offsetWidth;
    tip.style.left = Math.min(x + 14, window.innerWidth - w - 8) + 'px';
    tip.style.top = y + 14 + 'px';
  }
  function hideTip() {
    document.getElementById('tooltip').style.display = 'none';
  }

  // ---- heatmap ------------------------------------------------------------
  const STOPS = [[0, [21, 48, 74]], [0.5, [242, 166, 90]], [1, [255, 77, 46]]];
  function colorAt(v) {
    v = Math.max(0, Math.min(1, v));
    for (let i = 1; i < STOPS.length; i++) {
      if (v <= STOPS[i][0]) {
        const [t0, c0] = STOPS[i - 1], [t1, c1] = STOPS[i];
        const k = (v - t0) / (t1 - t0);
        return `rgb(${c0.map((c, j) => Math.round(c + (c1[j] - c) * k)).join(',')})`;
      }
    }
    return 'rgb(255,77,46)';
  }

  /** Draw P(flame sustained) over oxygen (x) and ventilation flow (y, log scale). */
  function heatmap(canvas, { o2s, flows, z, marker }) {
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth || 420, H = 340;
    canvas.width = W * dpr; canvas.height = H * dpr; canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const L = 52, R = 10, T = 8, B = 38;
    const pw = W - L - R, ph = H - T - B;
    const nx = o2s.length, ny = flows.length;
    const cw = pw / nx, ch = ph / ny;
    const yOf = (i) => T + ph - (i + 1) * ch;

    for (let i = 0; i < ny; i++) {
      for (let j = 0; j < nx; j++) {
        ctx.fillStyle = colorAt(z[i][j]);
        ctx.fillRect(L + j * cw, yOf(i), cw + 0.6, ch + 0.6);
      }
    }
    // 50% contour: edges between cells on different sides of 0.5
    ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2; ctx.beginPath();
    for (let i = 0; i < ny; i++) {
      for (let j = 0; j < nx; j++) {
        const on = z[i][j] >= 0.5;
        if (j + 1 < nx && on !== z[i][j + 1] >= 0.5) { ctx.moveTo(L + (j + 1) * cw, yOf(i)); ctx.lineTo(L + (j + 1) * cw, yOf(i) + ch); }
        if (i + 1 < ny && on !== z[i + 1][j] >= 0.5) { ctx.moveTo(L + j * cw, yOf(i)); ctx.lineTo(L + (j + 1) * cw, yOf(i)); }
      }
    }
    ctx.stroke();

    const css = getComputedStyle(document.documentElement);
    const muted = css.getPropertyValue('--muted').trim() || '#8b96a8';
    ctx.fillStyle = muted; ctx.strokeStyle = muted; ctx.font = '11px system-ui, sans-serif'; ctx.lineWidth = 1;

    const o2min = o2s[0], o2max = o2s[nx - 1];
    const xPos = (o2) => L + ((o2 - o2min) / (o2max - o2min)) * pw;
    const lf0 = Math.log(flows[0]), lf1 = Math.log(flows[ny - 1]);
    const yPos = (f) => T + ph - ((Math.log(f) - lf0) / (lf1 - lf0)) * ph;

    ctx.textAlign = 'center';
    for (let o2 = 12; o2 <= o2max; o2 += 4) ctx.fillText(o2, xPos(o2), H - B + 15);
    ctx.fillText('Oxygen (vol-%)', L + pw / 2, H - 6);
    ctx.textAlign = 'right';
    for (const f of [1, 2, 5, 10, 20, 50, 100]) ctx.fillText(f, L - 6, yPos(f) + 4);
    ctx.save(); ctx.translate(12, T + ph / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center';
    ctx.fillText('Ventilation flow (cm/s)', 0, 0); ctx.restore();

    if (marker) {
      const mx = xPos(Math.min(Math.max(marker.o2, o2min), o2max));
      const my = yPos(Math.min(Math.max(marker.flow, flows[0]), flows[ny - 1]));
      ctx.beginPath(); ctx.arc(mx, my, 7, 0, 7);
      ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = 2.5; ctx.strokeStyle = '#000'; ctx.stroke();
    }

    canvas.onmousemove = (e) => {
      const r = canvas.getBoundingClientRect();
      const px = e.clientX - r.left, py = e.clientY - r.top;
      const j = Math.floor((px - L) / cw), row = Math.floor((T + ph - py) / ch);
      if (j < 0 || j >= nx || row < 0 || row >= ny) return hideTip();
      showTip(`O₂ ${o2s[j].toFixed(1)}% · flow ${flows[row].toFixed(1)} cm/s<br><b>${Math.round(z[row][j] * 100)}%</b> chance flame persists`, e.clientX, e.clientY);
    };
    canvas.onmouseleave = hideTip;
  }

  const widthOf = (el) => Math.max(320, Math.round(el.clientWidth || 560));

  // ---- SVG helpers ----------------------------------------------------------
  const svgOpen = (W, H, label) =>
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}" preserveAspectRatio="xMidYMid meet">`;
  const grid = (ticks, x0, x1, yOf, fmt) =>
    ticks.map((t) => `<line class="grid" x1="${x0}" x2="${x1}" y1="${yOf(t)}" y2="${yOf(t)}"/><text class="tick" x="${x0 - 6}" y="${yOf(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join('');

  /** Vertical bars of sustain probability coloured by risk. */
  function gravityBars(el, rows) {
    const W = widthOf(el), H = 290, L = 46, R = 10, T = 22, B = 46;
    const pw = W - L - R, ph = H - T - B, bw = pw / rows.length;
    const yOf = (v) => T + ph - v * ph;
    let s = svgOpen(W, H, 'Probability a flame is sustained in each gravity environment');
    s += grid([0, 0.25, 0.5, 0.75, 1], L, W - R, yOf, (t) => Math.round(t * 100) + '%');
    rows.forEach((r, i) => {
      const x = L + i * bw + bw * 0.18, w = bw * 0.64, y = yOf(r.pSustained);
      s += `<g><title>${esc(r.label)}: ${Math.round(r.pSustained * 100)}% sustain, ${r.spread.toFixed(1)} mm/s, ${r.risk} risk</title>` +
        `<rect x="${x}" y="${y}" width="${w}" height="${Math.max(1, yOf(0) - y)}" rx="4" fill="${RISK_COLOR[r.risk]}"/>` +
        `<text class="val" x="${x + w / 2}" y="${y - 6}" text-anchor="middle">${Math.round(r.pSustained * 100)}%</text>` +
        `<text class="tick" x="${x + w / 2}" y="${H - 24}" text-anchor="middle">${esc(r.short)}</text>` +
        `<text class="tick dim" x="${x + w / 2}" y="${H - 10}" text-anchor="middle">${r.g} g</text></g>`;
    });
    el.innerHTML = s + '</svg>';
  }

  /** Two-line chart: expected spread rate vs oxygen. */
  function lineChart(el, { xs, series, xLabel, yLabel }) {
    const W = widthOf(el), H = 300, L = 46, R = 14, T = 38, B = 42;
    const pw = W - L - R, ph = H - T - B;
    const ymax = Math.max(1, ...series.flatMap((s) => s.values)) * 1.1;
    const xmin = xs[0], xmax = xs[xs.length - 1];
    const xOf = (v) => L + ((v - xmin) / (xmax - xmin)) * pw;
    const yOf = (v) => T + ph - (v / ymax) * ph;
    const yt = [0, 1, 2, 3, 4, 5].map((k) => (k * ymax) / 5);
    let s = svgOpen(W, H, yLabel + ' versus ' + xLabel);
    s += grid(yt, L, W - R, yOf, (t) => t.toFixed(1));
    for (let x = Math.ceil(xmin / 5) * 5; x <= xmax; x += 5) s += `<text class="tick" x="${xOf(x)}" y="${H - 22}" text-anchor="middle">${x}</text>`;
    s += `<text class="axis" x="${L + pw / 2}" y="${H - 5}" text-anchor="middle">${esc(xLabel)}</text>`;
    s += `<text class="axis" x="${L}" y="16">${esc(yLabel)}</text>`;
    series.forEach((ser, k) => {
      const d = xs.map((x, i) => `${i ? 'L' : 'M'}${xOf(x).toFixed(1)},${yOf(ser.values[i]).toFixed(1)}`).join('');
      s += `<path d="${d}" fill="none" stroke="${ser.color}" stroke-width="3" ${ser.dash ? 'stroke-dasharray="7 5"' : ''} stroke-linejoin="round"/>`;
      const lx = W - R - 250 + k * 130;
      s += `<line x1="${lx}" x2="${lx + 22}" y1="12" y2="12" stroke="${ser.color}" stroke-width="3" ${ser.dash ? 'stroke-dasharray="5 3"' : ''}/>` +
        `<text class="tick" x="${lx + 28}" y="16">${esc(ser.name)}</text>`;
    });
    el.innerHTML = s + '</svg>';
  }

  /** Horizontal bars (feature importance). */
  function hBars(el, items, xLabel) {
    const W = widthOf(el), rowH = 38, T = 8, L = 100, R = 50, B = 34;
    const H = T + items.length * rowH + B;
    const max = Math.max(...items.map((i) => i.value), 1e-6) * 1.05;
    let s = svgOpen(W, H, xLabel);
    items.forEach((it, i) => {
      const y = T + i * rowH, w = ((W - L - R) * it.value) / max;
      s += `<g><title>${esc(it.label)}: ${it.value.toFixed(3)}</title><text class="tick" x="${L - 10}" y="${y + 22}" text-anchor="end">${esc(it.label)}</text>` +
        `<rect x="${L}" y="${y + 6}" width="${Math.max(2, w)}" height="22" rx="4" fill="var(--accent)"/>` +
        `<text class="val" x="${L + w + 8}" y="${y + 22}">${it.value.toFixed(3)}</text></g>`;
    });
    s += `<text class="axis" x="${L}" y="${H - 8}">${esc(xLabel)}</text>`;
    el.innerHTML = s + '</svg>';
  }

  /** Stacked bars of outcome counts per gravity level. */
  function stackedBars(el, groups) {
    const W = widthOf(el), H = 270, L = 46, R = 10, T = 22, B = 56;
    const pw = W - L - R, ph = H - T - B, bw = pw / groups.length;
    const max = Math.max(...groups.map((g) => g.low + g.moderate + g.high)) * 1.08 || 1;
    const yOf = (v) => T + ph - (v / max) * ph;
    const ticks = [0, 1, 2, 3, 4].map((k) => Math.round((k * max) / 4));
    let s = svgOpen(W, H, 'Outcome counts by gravity');
    s += grid(ticks, L, W - R, yOf, (t) => t);
    groups.forEach((g, i) => {
      const x = L + i * bw + bw * 0.2, w = bw * 0.6;
      let base = 0;
      for (const k of ['low', 'moderate', 'high']) {
        const v = g[k];
        s += `<rect x="${x}" y="${yOf(base + v)}" width="${w}" height="${Math.max(0, yOf(base) - yOf(base + v))}" fill="${RISK_COLOR[k]}"><title>${g.label}: ${v} ${k}</title></rect>`;
        base += v;
      }
      s += `<text class="tick" x="${x + w / 2}" y="${H - 38}" text-anchor="middle">${esc(g.label)}</text>`;
    });
    s += ['low', 'moderate', 'high'].map((k, i) =>
      `<rect x="${L + i * 90}" y="${H - 22}" width="12" height="12" rx="2" fill="${RISK_COLOR[k]}"/><text class="tick" x="${L + i * 90 + 18}" y="${H - 12}">${k}</text>`).join('');
    el.innerHTML = s + '</svg>';
  }

  FIF.charts = { heatmap, gravityBars, lineChart, hBars, stackedBars, hideTip };
})(window.FIF);
