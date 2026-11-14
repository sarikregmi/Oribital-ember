/*
 * Synthetic combustion dataset generation plus CSV import / export.
 * Real experiment data can replace the synthetic set if it follows C.CSV_COLUMNS.
 */
(function (FIF) {
  const C = FIF.config;
  const P = FIF.physics;

  /** Small seeded PRNG so every run is reproducible. */
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function normal(rng) {
    let u = 0;
    while (u === 0) u = rng();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rng());
  }
  const uniform = (rng, [lo, hi]) => lo + (hi - lo) * rng();
  const logUniform = (rng, [lo, hi]) => Math.exp(Math.log(lo) + (Math.log(hi) - Math.log(lo)) * rng());
  function weightedChoice(rng, values, probs) {
    let r = rng(), acc = 0;
    for (let i = 0; i < values.length; i++) {
      acc += probs[i];
      if (r < acc) return values[i];
    }
    return values[values.length - 1];
  }

  /** Sample experiment conditions and simulate noisy outcomes. */
  function generate(n, seed) {
    const rng = mulberry32(seed);
    const rows = new Array(n);
    for (let i = 0; i < n; i++) {
      const s = {
        fuel: P.FUEL_KEYS[Math.floor(rng() * P.FUEL_KEYS.length)],
        o2: uniform(rng, C.O2_RANGE),
        pressure: uniform(rng, C.PRESSURE_RANGE),
        flow: logUniform(rng, C.FLOW_RANGE),
        gravity: weightedChoice(rng, C.SAMPLED_GRAVITY, C.SAMPLED_GRAVITY_PROBS),
        thickness: logUniform(rng, C.THICKNESS_RANGE),
      };
      const loc = P.limitingOxygen(s) + C.LOC_NOISE * normal(rng);
      const sustained = s.o2 > loc;
      let spread = 0;
      if (sustained) spread = P.spreadGivenLoc(s, loc) * Math.exp(C.SPREAD_NOISE * normal(rng));
      spread = Math.round(spread * 1e4) / 1e4;
      rows[i] = { ...s, sustained: sustained ? 1 : 0, spread, risk: P.classifyRisk(sustained, spread) };
    }
    return rows;
  }

  // ---- CSV -------------------------------------------------------------
  const FIELD_MAP = {
    fuel: 'fuel', o2_percent: 'o2', pressure_atm: 'pressure', flow_cm_s: 'flow',
    gravity_g: 'gravity', thickness_mm: 'thickness', flame_sustained: 'sustained', spread_rate_mm_s: 'spread',
  };

  function toCSV(rows) {
    const lines = [C.CSV_COLUMNS.join(',')];
    for (const r of rows) {
      lines.push(C.CSV_COLUMNS.map((c) => {
        const v = r[FIELD_MAP[c]];
        return typeof v === 'number' ? +v.toFixed(5) : v;
      }).join(','));
    }
    return lines.join('\n');
  }

  /** Parse and validate a CSV string. Throws Error with a readable message. */
  function parseCSV(text) {
    const lines = text.replace(/\r/g, '').split('\n').filter((l) => l.trim() !== '');
    if (lines.length < 2) throw new Error('The file has no data rows.');
    const header = lines[0].split(',').map((h) => h.trim());
    const missing = C.CSV_COLUMNS.filter((c) => !header.includes(c));
    if (missing.length) throw new Error('Missing required columns: ' + missing.join(', '));
    const idx = Object.fromEntries(header.map((h, i) => [h, i]));

    const rows = [];
    for (let li = 1; li < lines.length; li++) {
      const cells = lines[li].split(',');
      const get = (c) => (cells[idx[c]] ?? '').trim();
      const fail = (msg) => { throw new Error(`Row ${li + 1}: ${msg}`); };

      const fuel = get('fuel');
      if (!P.FUELS[fuel]) fail(`unknown fuel "${fuel}" (expected one of ${P.FUEL_KEYS.join(', ')})`);
      const num = (c) => {
        const v = Number(get(c));
        if (get(c) === '' || !Number.isFinite(v)) fail(`"${c}" is not a number`);
        return v;
      };
      const row = {
        fuel, o2: num('o2_percent'), pressure: num('pressure_atm'), flow: num('flow_cm_s'),
        gravity: num('gravity_g'), thickness: num('thickness_mm'),
        sustained: num('flame_sustained'), spread: num('spread_rate_mm_s'),
      };
      if (row.o2 <= 0 || row.pressure <= 0 || row.thickness <= 0) fail('o2_percent, pressure_atm and thickness_mm must be positive');
      if (row.gravity < 0 || row.flow < 0 || row.spread < 0) fail('gravity_g, flow_cm_s and spread_rate_mm_s must not be negative');
      if (row.sustained !== 0 && row.sustained !== 1) fail('flame_sustained must be 0 or 1');
      row.risk = P.classifyRisk(row.sustained === 1, row.spread);
      rows.push(row);
    }
    if (rows.length < 200) throw new Error(`Only ${rows.length} rows found; at least 200 are needed to train.`);
    return rows;
  }

  FIF.data = { mulberry32, normal, generate, toCSV, parseCSV };
})(window.FIF);
