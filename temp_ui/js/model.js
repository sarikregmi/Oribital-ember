/*
 * Feature engineering, training, evaluation and persistence of the two models:
 *  - classifier: probability that a flame is sustained
 *  - regressor : flame spread rate (mm/s) given that it is sustained
 */
(function (FIF) {
  const C = FIF.config;
  const P = FIF.physics;
  const { MLP } = FIF.nn;

  const NUMERIC_NAMES = ['o2', 'pressure', 'lnFlow', 'invEff', 'effSq', 'cbrtG', 'lnThick', 'ppo2'];
  const INPUT_NAMES = ['fuel', 'o2', 'pressure', 'flow', 'gravity', 'thickness'];
  const N_FEATURES = P.FUEL_KEYS.length + NUMERIC_NAMES.length;
  const STORAGE_KEY = 'fif-model-' + C.MODEL_VERSION;

  let state = null; // { clf, reg, scaler, regScale, metrics }

  /** Physically motivated numeric features for a scenario. */
  function rawNumeric(s) {
    const eff = P.effectiveFlow(s.flow, s.gravity);
    return [
      s.o2,
      s.pressure,
      Math.log(s.flow + 1),
      1 / Math.max(eff, C.MIN_FLOW),
      Math.pow(eff / 100, 2),
      Math.cbrt(s.gravity),
      Math.log(s.thickness),
      (s.o2 / 100) * s.pressure * 101.325,
    ];
  }

  function fitScaler(rows) {
    const k = NUMERIC_NAMES.length;
    const mean = new Array(k).fill(0), std = new Array(k).fill(0);
    const raw = rows.map(rawNumeric);
    for (const r of raw) for (let j = 0; j < k; j++) mean[j] += r[j] / raw.length;
    for (const r of raw) for (let j = 0; j < k; j++) std[j] += Math.pow(r[j] - mean[j], 2) / raw.length;
    return { mean, std: std.map((v) => Math.sqrt(v) || 1) };
  }

  function vectorize(s, scaler) {
    const x = new Float64Array(N_FEATURES);
    x[P.FUEL_KEYS.indexOf(s.fuel)] = 1;
    const r = rawNumeric(s);
    for (let j = 0; j < r.length; j++) x[P.FUEL_KEYS.length + j] = (r[j] - scaler.mean[j]) / scaler.std[j];
    return x;
  }

  // ---- inference -----------------------------------------------------
  function riskFrom(p, spread) {
    if (p < C.P_LOW) return 'low';
    if (p >= C.P_HIGH && spread >= C.HIGH_SPREAD) return 'high';
    return 'moderate';
  }

  function predictWith(m, s) {
    const x = vectorize(s, m.scaler);
    const p = m.clf.predict(x);
    const spread = Math.max(0, Math.expm1(m.reg.predict(x) * m.regScale.std + m.regScale.mean));
    return { pSustained: p, spread, risk: riskFrom(p, spread) };
  }
  function probWith(m, s) {
    return m.clf.predict(vectorize(s, m.scaler));
  }

  const predict = (s) => predictWith(state, s);
  const predictProb = (s) => probWith(state, s);

  // ---- evaluation ----------------------------------------------------
  function auc(probs, labels) {
    const idx = probs.map((_, i) => i).sort((a, b) => probs[a] - probs[b]);
    let rankSum = 0, pos = 0;
    idx.forEach((i, rank) => { if (labels[i] === 1) { rankSum += rank + 1; pos++; } });
    const neg = labels.length - pos;
    return pos && neg ? (rankSum - (pos * (pos + 1)) / 2) / (pos * neg) : 0.5;
  }

  function evaluate(m, test) {
    const probs = test.map((r) => probWith(m, r));
    const labels = test.map((r) => r.sustained);
    const pred = probs.map((p) => (p >= 0.5 ? 1 : 0));
    let tp = 0, fp = 0, fn = 0, correct = 0;
    pred.forEach((p, i) => {
      if (p === labels[i]) correct++;
      if (p === 1 && labels[i] === 1) tp++;
      if (p === 1 && labels[i] === 0) fp++;
      if (p === 0 && labels[i] === 1) fn++;
    });
    const byGravity = {};
    for (const g of [...new Set(test.map((r) => r.gravity))].sort((a, b) => a - b)) {
      const sel = test.map((r, i) => i).filter((i) => test[i].gravity === g);
      byGravity[g] = sel.filter((i) => pred[i] === labels[i]).length / sel.length;
    }

    const burning = test.filter((r) => r.sustained === 1);
    const yTrue = burning.map((r) => r.spread);
    const yPred = burning.map((r) => predictWith(m, r).spread);
    const meanY = yTrue.reduce((a, b) => a + b, 0) / yTrue.length;
    const ssRes = yTrue.reduce((a, y, i) => a + Math.pow(y - yPred[i], 2), 0);
    const ssTot = yTrue.reduce((a, y) => a + Math.pow(y - meanY, 2), 0);
    const mae = yTrue.reduce((a, y, i) => a + Math.abs(y - yPred[i]), 0) / yTrue.length;

    const baseAuc = auc(probs, labels);
    return {
      classifier: {
        accuracy: correct / test.length,
        f1: tp ? (2 * tp) / (2 * tp + fp + fn) : 0,
        rocAuc: baseAuc,
        accuracyByGravity: byGravity,
      },
      regressor: { r2: 1 - ssRes / ssTot, maeMmS: mae },
      baseAuc,
    };
  }

  function permutationImportance(m, test, baseAuc, rng) {
    const labels = test.map((r) => r.sustained);
    const out = {};
    for (const name of INPUT_NAMES) {
      let drop = 0;
      const repeats = 2;
      for (let rep = 0; rep < repeats; rep++) {
        const col = test.map((r) => r[name]);
        for (let i = col.length - 1; i > 0; i--) {
          const j = Math.floor(rng() * (i + 1));
          [col[i], col[j]] = [col[j], col[i]];
        }
        const probs = test.map((r, i) => probWith(m, { ...r, [name]: col[i] }));
        drop += (baseAuc - auc(probs, labels)) / repeats;
      }
      out[name] = Math.max(0, drop);
    }
    return Object.fromEntries(Object.entries(out).sort((a, b) => b[1] - a[1]));
  }

  // ---- training ------------------------------------------------------
  /**
   * Train both networks on `rows` (array of experiment rows).
   * onProgress(fraction, message) is called as training advances.
   */
  async function train({ rows, seed = C.SEED, source = 'synthetic', onProgress = () => {} }) {
    const rng = FIF.data.mulberry32(seed + 1);
    const shuffled = rows.slice();
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    const nTest = Math.round(shuffled.length * C.TEST_FRACTION);
    const test = shuffled.slice(0, nTest);
    const trainRows = shuffled.slice(nTest);

    const scaler = fitScaler(trainRows);
    const X = trainRows.map((r) => vectorize(r, scaler));
    const yClf = trainRows.map((r) => r.sustained);

    const clf = new MLP([N_FEATURES, 32, 32, 1], 'binary', rng);
    await clf.fit(X, yClf, {
      epochs: 40, batch: 64, lr: 0.004, rng,
      onEpoch: (e, n) => onProgress(0.55 * ((e + 1) / n), 'Training flame-persistence classifier'),
    });

    const burnIdx = trainRows.map((r, i) => i).filter((i) => trainRows[i].sustained === 1);
    const target = burnIdx.map((i) => Math.log1p(trainRows[i].spread));
    const tMean = target.reduce((a, b) => a + b, 0) / target.length;
    const tStd = Math.sqrt(target.reduce((a, t) => a + Math.pow(t - tMean, 2), 0) / target.length) || 1;
    const reg = new MLP([N_FEATURES, 32, 32, 1], 'linear', rng);
    await reg.fit(burnIdx.map((i) => X[i]), target.map((t) => (t - tMean) / tStd), {
      epochs: 40, batch: 64, lr: 0.003, rng,
      onEpoch: (e, n) => onProgress(0.55 + 0.35 * ((e + 1) / n), 'Training spread-rate regressor'),
    });

    const model = { clf, reg, scaler, regScale: { mean: tMean, std: tStd } };
    onProgress(0.92, 'Evaluating on held-out experiments');
    await new Promise((r) => setTimeout(r, 0));
    const metrics = evaluate(model, test);
    metrics.featureImportance = permutationImportance(model, test, metrics.baseAuc, rng);
    delete metrics.baseAuc;
    Object.assign(metrics, { nTrain: trainRows.length, nTest: test.length, dataSource: source, trainedAt: new Date().toISOString() });

    model.metrics = metrics;
    state = model;
    save();
    onProgress(1, 'Done');
    return metrics;
  }

  // ---- persistence (browser localStorage; optional) -------------------
  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        clf: state.clf.toJSON(), reg: state.reg.toJSON(), scaler: state.scaler,
        regScale: state.regScale, metrics: state.metrics,
      }));
    } catch (e) { /* storage unavailable or full: model just retrains next visit */ }
  }
  function loadSaved() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return false;
      const o = JSON.parse(raw);
      state = { clf: MLP.fromJSON(o.clf), reg: MLP.fromJSON(o.reg), scaler: o.scaler, regScale: o.regScale, metrics: o.metrics };
      return true;
    } catch (e) { return false; }
  }
  function clearSaved() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  }

  FIF.model = {
    train, predict, predictProb, loadSaved, clearSaved,
    get metrics() { return state && state.metrics; },
    get ready() { return !!state; },
  };
})(window.FIF);
