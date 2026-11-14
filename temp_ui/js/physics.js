/*
 * Reduced-order physics for flame spread over solid fuels in reduced gravity.
 *
 * A surrogate of the qualitative behaviour reported in spacecraft fire research
 * (NASA Saffire / SoFIE-type experiments), not a CFD code:
 *  - U-shaped flammability boundary in flow speed (starved at low flow, blown off at high flow)
 *  - in 1 g buoyancy adds flow and convective cooling
 *  - spread rate grows with the oxygen margin above the limit
 * All parameters are illustrative.
 */
(function (FIF) {
  const C = FIF.config;

  const FUELS = {
    cellulose: {
      key: 'cellulose', label: 'Cellulose (ashless filter paper)',
      description: 'Thin cellulosic sheet; a standard benchmark fuel in combustion research.',
      locMin: 15.5, radiative: 18.0, blowoff: 5.0, spread: 3.2,
    },
    cotton_fiberglass: {
      key: 'cotton_fiberglass', label: 'Cotton-fiberglass blend (SIBAL-type)',
      description: 'Fabric representative of spacecraft textiles, used in large-scale fire tests.',
      locMin: 19.0, radiative: 22.0, blowoff: 5.5, spread: 1.9,
    },
    pmma: {
      key: 'pmma', label: 'PMMA (acrylic)',
      description: 'Clear plastic used in windows and enclosures; a common thermoplastic reference.',
      locMin: 17.5, radiative: 24.0, blowoff: 6.0, spread: 1.6,
    },
    polyethylene: {
      key: 'polyethylene', label: 'Polyethylene film',
      description: 'Packaging-type polymer film found in cargo and wiring insulation.',
      locMin: 18.5, radiative: 20.0, blowoff: 5.5, spread: 2.1,
    },
    nomex: {
      key: 'nomex', label: 'Aramid fabric (Nomex-style)',
      description: 'Flame-resistant crew clothing fabric; hard to ignite but not immune.',
      locMin: 24.0, radiative: 28.0, blowoff: 7.0, spread: 0.9,
    },
  };
  const FUEL_KEYS = Object.keys(FUELS);

  /** Forced flow combined with buoyancy-induced flow (cm/s). */
  function effectiveFlow(flow, gravity) {
    const b = C.BUOYANT_FLOW * Math.cbrt(gravity);
    return Math.sqrt(flow * flow + b * b);
  }

  /** Limiting oxygen concentration (vol-%) below which a flame cannot persist. */
  function limitingOxygen(s) {
    const f = FUELS[s.fuel];
    const u = Math.max(effectiveFlow(s.flow, s.gravity), C.MIN_FLOW);
    const loc =
      f.locMin + f.radiative / u + f.blowoff * Math.pow(u / 100, 2) + C.BUOYANT_COOLING * Math.cbrt(s.gravity);
    const pressureFactor = Math.pow(s.pressure, -C.PRESSURE_EXPONENT);
    const thicknessFactor = 1 + 0.25 * Math.log(s.thickness / C.REF_THICKNESS);
    return loc * pressureFactor * thicknessFactor;
  }

  /** Spread rate (mm/s) given an already computed limiting oxygen. */
  function spreadGivenLoc(s, loc) {
    const margin = Math.max(s.o2 - loc, 0);
    const u = effectiveFlow(s.flow, s.gravity);
    const thicknessTerm = Math.pow(C.REF_THICKNESS / s.thickness, 0.8);
    return FUELS[s.fuel].spread * Math.sqrt(margin) * (u / (u + 8)) * Math.pow(s.pressure, 0.3) * thicknessTerm;
  }

  function classifyRisk(sustained, spread) {
    if (!sustained) return 'low';
    return spread >= C.HIGH_SPREAD ? 'high' : 'moderate';
  }

  FIF.physics = { FUELS, FUEL_KEYS, effectiveFlow, limitingOxygen, spreadGivenLoc, classifyRisk };
})(window.FIF);
