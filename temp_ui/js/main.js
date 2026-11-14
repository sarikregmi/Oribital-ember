/* App wiring: controls, tabs, rendering and training lifecycle. */
(function (FIF) {
  const C = FIF.config, P = FIF.physics, I = FIF.insights, M = FIF.model, CH = FIF.charts;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const pct = (p) => Math.round(p * 100) + '%';
  const FLOW_MIN = C.FLOW_RANGE[0], FLOW_MAX = C.FLOW_RANGE[1];
  const flowFromSlider = (v) => FLOW_MIN * Math.pow(FLOW_MAX / FLOW_MIN, v / 100);
  const sliderFromFlow = (f) => (Math.log(f / FLOW_MIN) / Math.log(FLOW_MAX / FLOW_MIN)) * 100;

  const state = { fuel: 'cellulose', gravity: 0, o2: 21, pressure: 1, flow: 10, thickness: 0.1 };
  let dataset = null;
  let activeTab = 'overview';

  const PRESETS = {
    iss: { o2: 21, pressure: 1.0, flow: 10, gravity: 0 },
    lowp: { o2: 34, pressure: 0.56, flow: 10, gravity: 0 },
    rich: { o2: 30, pressure: 1.0, flow: 20, gravity: 0 },
  };

  const scenario = () => ({ ...state });

  // ---- loader ---------------------------------------------------------
  function setProgress(frac, msg) {
    $('loader-bar').style.width = Math.round(frac * 100) + '%';
    if (msg) $('loader-msg').textContent = msg;
  }
  function showLoader(show) {
    $('loader').classList.toggle('hidden', !show);
  }

  // ---- controls ---------------------------------------------------------
  function buildControls() {
    $('fuel').innerHTML = P.FUEL_KEYS.map((k) => `<option value="${k}">${esc(P.FUELS[k].label)}</option>`).join('');
    $('gravity').innerHTML = C.GRAVITY_LEVELS.map((l, i) => `<option value="${i}">${esc(l.label)}</option>`).join('');

    $('fuel').onchange = (e) => { state.fuel = e.target.value; syncControls(); refresh(); };
    $('gravity').onchange = (e) => { state.gravity = C.GRAVITY_LEVELS[+e.target.value].g; refresh(); };
    $('o2').oninput = (e) => { state.o2 = +e.target.value; syncControls(); refresh(); };
    $('pressure').oninput = (e) => { state.pressure = +e.target.value; syncControls(); refresh(); };
    $('flow').oninput = (e) => { state.flow = flowFromSlider(+e.target.value); syncControls(); refresh(); };
    $('thickness').oninput = (e) => { state.thickness = +e.target.value; syncControls(); refresh(); };

    $('presets').onclick = (e) => {
      const key = e.target.dataset && e.target.dataset.preset;
      if (!key) return;
      Object.assign(state, PRESETS[key]);
      syncControls();
      refresh();
    };
    syncControls();
  }

  function syncControls() {
    $('fuel').value = state.fuel;
    $('fuel-desc').textContent = P.FUELS[state.fuel].description;
    $('gravity').value = String(Math.max(0, C.GRAVITY_LEVELS.findIndex((l) => l.g === state.gravity)));
    $('o2').value = state.o2;
    $('o2-out').textContent = state.o2.toFixed(1) + ' %';
    $('pressure').value = state.pressure;
    $('pressure-out').textContent = state.pressure.toFixed(2) + ' atm';
    $('flow').value = sliderFromFlow(state.flow);
    $('flow-out').textContent = state.flow.toFixed(1) + ' cm/s';
    $('thickness').value = state.thickness;
    $('thickness-out').textContent = state.thickness.toFixed(2) + ' mm';
  }

  // ---- tabs -------------------------------------------------------------
  function buildTabs() {
    document.querySelectorAll('.tab-btn').forEach((btn) => {
      btn.onclick = () => selectTab(btn.dataset.tab);
    });
  }
  function selectTab(name) {
    activeTab = name;
    document.querySelectorAll('.tab-btn').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
    CH.hideTip();
    refresh();
  }

  // ---- rendering ----------------------------------------------------------
  let pending = false;
  function refresh() {
    if (pending || !M.ready) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      ({ assessment: renderAssessment, map: renderMap, model: renderModel, data: renderData }[activeTab] || (() => {}))();
    });
  }

  function metricCard(label, value, sub, cls = '') {
    return `<div class="card metric"><div class="label">${esc(label)}</div><div class="value ${cls}">${value}</div><div class="sub">${sub}</div></div>`;
  }

  function renderAssessment() {
    const s = scenario();
    const pred = I.predict(s);
    $('metrics').innerHTML =
      metricCard('Risk level', pred.risk.toUpperCase(), 'low, moderate or high', 'risk-' + pred.risk) +
      metricCard('Flame sustain probability', pct(pred.pSustained), 'chance the flame persists') +
      metricCard('Expected spread rate', pred.pSustained >= C.P_LOW ? pred.spread.toFixed(1) + ' mm/s' : 'n/a', 'if the flame persists');

    $('insights').innerHTML = I.generateInsights(s)
      .map((i) => `<div class="insight ${i.level}"><b>${esc(i.title)}</b><p>${esc(i.text)}</p></div>`).join('');

    const rows = I.gravityComparison(s);
    CH.gravityBars($('gravity-chart'), rows);
    $('gravity-table').innerHTML =
      '<tr><th>Environment</th><th>P(sustain)</th><th>Spread</th><th>Risk</th></tr>' +
      rows.map((r) => `<tr><td>${esc(r.short)} (${r.g} g)</td><td>${pct(r.pSustained)}</td><td>${r.spread.toFixed(1)} mm/s</td><td class="risk-${r.risk}">${r.risk}</td></tr>`).join('');
  }

  function renderMap() {
    const s = scenario();
    const o2s = Array.from({ length: 57 }, (_, i) => 12 + (i * 28) / 56);
    const flows = Array.from({ length: 45 }, (_, i) => FLOW_MIN * Math.pow(FLOW_MAX / FLOW_MIN, i / 44));
    const marker = { o2: s.o2, flow: s.flow };
    CH.heatmap($('map-micro'), { o2s, flows, z: I.predictGrid({ ...s, gravity: 0 }, o2s, flows), marker });
    CH.heatmap($('map-earth'), { o2s, flows, z: I.predictGrid({ ...s, gravity: 1 }, o2s, flows), marker });

    const xs = Array.from({ length: 40 }, (_, i) => 14 + (i * 26) / 39);
    const line = (g) => xs.map((o2) => {
      const p = I.predict({ ...s, gravity: g, o2 });
      return p.pSustained >= 0.5 ? p.spread : 0;
    });
    CH.lineChart($('spread-chart'), {
      xs, xLabel: 'Oxygen (vol-%)', yLabel: 'Expected spread rate (mm/s)',
      series: [
        { name: 'Microgravity', color: 'var(--accent)', values: line(0) },
        { name: 'Earth (1 g)', color: 'var(--muted)', values: line(1), dash: true },
      ],
    });
  }

  const INPUT_LABELS = { fuel: 'Material', o2: 'Oxygen', pressure: 'Pressure', flow: 'Ventilation flow', gravity: 'Gravity', thickness: 'Thickness' };

  function renderModel() {
    const m = M.metrics;
    $('model-caption').textContent =
      `Data source: ${m.dataSource} · trained on ${m.nTrain} experiments, tested on ${m.nTest} held-out · ${new Date(m.trainedAt).toLocaleString()}`;
    $('model-metrics').innerHTML =
      metricCard('Accuracy', (m.classifier.accuracy * 100).toFixed(1) + '%', 'flame persists or not') +
      metricCard('ROC AUC', m.classifier.rocAuc.toFixed(3), '1.0 is perfect') +
      metricCard('Spread R²', m.regressor.r2.toFixed(2), 'variance explained') +
      metricCard('Spread error', m.regressor.maeMmS.toFixed(2) + ' mm/s', 'mean absolute');
    CH.hBars($('importance-chart'),
      Object.entries(m.featureImportance).map(([k, v]) => ({ label: INPUT_LABELS[k], value: v })),
      'Drop in ROC AUC when the input is shuffled');
    $('gravity-acc').innerHTML =
      '<tr><th>Gravity</th><th>Accuracy</th></tr>' +
      Object.entries(m.classifier.accuracyByGravity).map(([g, a]) => `<tr><td>${g} g</td><td>${(a * 100).toFixed(1)}%</td></tr>`).join('');
  }

  function renderData() {
    const groups = C.GRAVITY_LEVELS.map((lvl) => {
      const sel = dataset.filter((r) => Math.abs(r.gravity - lvl.g) < 1e-9);
      const g = { label: lvl.g + ' g', low: 0, moderate: 0, high: 0 };
      sel.forEach((r) => g[r.risk]++);
      return g;
    }).filter((g) => g.low + g.moderate + g.high > 0);
    CH.stackedBars($('dist-chart'), groups);

    const head = ['fuel', 'o2 %', 'pressure atm', 'flow cm/s', 'g', 'thickness mm', 'sustained', 'spread mm/s', 'risk'];
    $('data-table').innerHTML =
      '<tr>' + head.map((h) => `<th>${h}</th>`).join('') + '</tr>' +
      dataset.slice(0, 100).map((r) =>
        `<tr><td>${r.fuel}</td><td>${r.o2.toFixed(1)}</td><td>${r.pressure.toFixed(2)}</td><td>${r.flow.toFixed(1)}</td><td>${r.gravity}</td><td>${r.thickness.toFixed(2)}</td><td>${r.sustained}</td><td>${r.spread.toFixed(2)}</td><td class="risk-${r.risk}">${r.risk}</td></tr>`).join('');
  }

  // ---- training ---------------------------------------------------------
  async function trainOn(rows, seed, source, label) {
    showLoader(true);
    setProgress(0, label);
    await new Promise((r) => setTimeout(r, 30));
    dataset = rows;
    await M.train({ rows, seed, source, onProgress: setProgress });
    showLoader(false);
    refresh();
  }

  function buildTraining() {
    $('retrain').onclick = async () => {
      const n = +$('samples').value, seed = Math.max(1, +$('seed').value || C.SEED);
      $('retrain').disabled = true;
      $('retrain-msg').textContent = '';
      await trainOn(FIF.data.generate(n, seed), seed, 'synthetic', 'Generating data…');
      $('retrain').disabled = false;
      $('retrain-msg').className = 'msg good';
      $('retrain-msg').textContent = `Retrained on ${n} synthetic experiments.`;
    };

    $('csv-file').onchange = async (e) => {
      const file = e.target.files[0];
      const msg = $('csv-msg');
      if (!file) return;
      try {
        const rows = FIF.data.parseCSV(await file.text());
        msg.className = 'msg';
        msg.textContent = 'Training…';
        await trainOn(rows, C.SEED, 'user-supplied: ' + file.name, 'Training on your data…');
        msg.className = 'msg good';
        msg.textContent = `Trained on ${rows.length} rows from ${file.name}.`;
      } catch (err) {
        showLoader(false);
        msg.className = 'msg error';
        msg.textContent = err.message;
      }
      e.target.value = '';
    };

    $('download-csv').onclick = () => {
      const blob = new Blob([FIF.data.toCSV(dataset)], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'combustion_dataset.csv';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
  }

  // ---- theme ---------------------------------------------------------------
  function buildTheme() {
    let saved = null;
    try { saved = localStorage.getItem('fif-theme'); } catch (e) { /* ignore */ }
    if (saved) document.documentElement.dataset.theme = saved;
    $('theme-toggle').onclick = () => {
      const cur = document.documentElement.dataset.theme || 'dark';
      const next = cur === 'light' ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('fif-theme', next); } catch (e) { /* ignore */ }
      refresh();
    };
  }

  // ---- start ----------------------------------------------------------------
  async function init() {
    buildTheme();
    buildControls();
    buildTabs();
    buildTraining();
    window.addEventListener('resize', () => refresh());

    // The dataset is cheap to regenerate; the trained model is cached in the browser.
    dataset = FIF.data.generate(C.DEFAULT_SAMPLES, C.SEED);
    if (M.loadSaved()) {
      showLoader(false);
    } else {
      await trainOn(dataset, C.SEED, 'synthetic', 'Training the model in your browser (first visit only)…');
    }
    refresh();
  }

  init().catch((err) => {
    $('loader-msg').textContent = 'Something went wrong: ' + err.message;
    console.error(err);
  });

  FIF.app = { state, selectTab };
})(window.FIF);
