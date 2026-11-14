/*
 * Turns model predictions into fire-safety insights by asking "what-if" questions:
 * how does the same scenario behave on Earth, which airflow is worst, how much would
 * oxygen need to drop to make a persistent flame unlikely.
 *
 * A scenario is { fuel, o2, pressure, flow, gravity, thickness }.
 */
(function (FIF) {
  const C = FIF.config;
  const P = FIF.physics;
  const M = FIF.model;

  const WORST_CASE_FLOWS = [1, 2, 5, 10, 20, 40, 80];
  const pct = (p) => Math.round(p * 100) + '%';
  const fixed = (v, d = 1) => v.toFixed(d);

  function predict(s) {
    return M.predict(s);
  }

  /** Probability of a sustained flame over a (flow x O2) grid; rows = flows, cols = O2. */
  function predictGrid(s, o2s, flows) {
    return flows.map((flow) => o2s.map((o2) => M.predictProb({ ...s, flow, o2 })));
  }

  /** Highest O2 (vol-%) at which the sustain probability stays below maxP; null if none. */
  function safeO2Threshold(s, maxP = 0.1) {
    let last = null;
    for (let o2 = 10; o2 <= 50.001; o2 += 0.25) {
      if (M.predictProb({ ...s, o2 }) >= maxP) return last;
      last = o2;
    }
    return 50;
  }

  function gravityComparison(s) {
    return C.GRAVITY_LEVELS.map((lvl) => ({ ...lvl, ...predict({ ...s, gravity: lvl.g }) }));
  }

  function worstCaseFlow(s) {
    let best = { flow: WORST_CASE_FLOWS[0], p: -1 };
    for (const flow of WORST_CASE_FLOWS) {
      const p = M.predictProb({ ...s, flow });
      if (p > best.p) best = { flow, p };
    }
    return best;
  }

  function generateInsights(s) {
    const fuel = P.FUELS[s.fuel].label;
    const here = predict(s);
    const earth = predict({ ...s, gravity: 1 });
    const out = [];

    const head = {
      high: ['critical', 'High fire risk', 'A flame is likely to persist and spread quickly'],
      moderate: ['warning', 'Moderate fire risk', 'A flame may persist but spreads slowly'],
      low: ['ok', 'Low fire risk', 'A flame is unlikely to persist'],
    }[here.risk];
    out.push({
      level: head[0], title: head[1],
      text: `${head[2]} for ${fuel}. Estimated sustain probability is ${pct(here.pSustained)}` +
        (here.pSustained >= C.P_LOW ? `, with a spread rate near ${fixed(here.spread)} mm/s.` : '.'),
    });

    if (s.gravity < 0.9) {
      const delta = here.pSustained - earth.pSustained;
      if (delta > 0.15) {
        out.push({
          level: 'critical', title: 'Earth tests underestimate this hazard',
          text: `Under 1 g the same conditions give a ${pct(earth.pSustained)} sustain probability, versus ${pct(here.pSustained)} here. A material that passes a normal-gravity screen may still burn in reduced gravity.`,
        });
      } else if (delta < -0.15) {
        out.push({
          level: 'info', title: 'Reduced gravity is more forgiving here',
          text: `Without buoyant flow the flame is starved: sustain probability falls from ${pct(earth.pSustained)} (1 g) to ${pct(here.pSustained)}. Do not rely on this if fans raise the airflow.`,
        });
      } else {
        out.push({
          level: 'info', title: 'Similar to Earth behaviour',
          text: `Sustain probability is ${pct(here.pSustained)} here versus ${pct(earth.pSustained)} at 1 g.`,
        });
      }
    }

    const threshold = safeO2Threshold(s);
    if (threshold === null) {
      out.push({ level: 'warning', title: 'No safe oxygen level in range', text: 'Even at 10% oxygen the model still gives a non-trivial chance of flame persistence for these other conditions.' });
    } else if (s.o2 > threshold) {
      out.push({ level: 'warning', title: 'Reduce oxygen to lower risk', text: `Lowering oxygen from ${fixed(s.o2)}% to about ${fixed(threshold)}% brings the sustain probability under 10% for these conditions.` });
    } else {
      out.push({ level: 'ok', title: 'Oxygen below the safe threshold', text: `Current oxygen is under the ~${fixed(threshold)}% level at which the model puts sustain probability at 10%.` });
    }

    const worst = worstCaseFlow(s);
    if (worst.p - here.pSustained > 0.15) {
      out.push({
        level: 'warning', title: 'Ventilation speed matters',
        text: `Airflow near ${worst.flow} cm/s is the worst case tested, raising sustain probability to ${pct(worst.p)} (from ${pct(here.pSustained)} at ${fixed(s.flow)} cm/s). Check fan and duct layouts near this material.`,
      });
    }

    const lowerP = predict({ ...s, pressure: Math.max(C.PRESSURE_RANGE[0], s.pressure * 0.8) });
    if (here.pSustained - lowerP.pSustained > 0.15) {
      out.push({
        level: 'info', title: 'Lower cabin pressure helps',
        text: `A 20% pressure reduction cuts sustain probability from ${pct(here.pSustained)} to ${pct(lowerP.pSustained)}. Pressure and oxygen should be reviewed together.`,
      });
    }
    return out;
  }

  FIF.insights = { predict, predictGrid, safeO2Threshold, gravityComparison, worstCaseFlow, generateInsights };
})(window.FIF);
