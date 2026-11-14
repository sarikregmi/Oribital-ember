/* Central configuration: constants, ranges and thresholds shared by every module. */
(function (FIF) {
  FIF.config = {
    SEED: 42,
    DEFAULT_SAMPLES: 6000,
    TEST_FRACTION: 0.2,
    MODEL_VERSION: 'v1',

    GRAVITY_LEVELS: [
      { label: 'Microgravity (ISS / free-fall)', short: 'Microgravity', g: 0 },
      { label: 'Lunar (0.16 g)', short: 'Lunar', g: 0.16 },
      { label: 'Martian (0.38 g)', short: 'Martian', g: 0.38 },
      { label: 'Earth (1 g)', short: 'Earth', g: 1 },
    ],

    // Reduced-order physics parameters (illustrative)
    BUOYANT_FLOW: 15.0,       // cm/s, buoyant flow scale at 1 g (scales with g^(1/3))
    BUOYANT_COOLING: 1.2,     // vol-% O2 convective-cooling penalty at 1 g
    MIN_FLOW: 0.5,            // cm/s
    REF_THICKNESS: 0.1,       // mm
    PRESSURE_EXPONENT: 0.4,

    // Sampling ranges for the synthetic dataset
    O2_RANGE: [15, 35],
    PRESSURE_RANGE: [0.5, 1.2],
    FLOW_RANGE: [0.5, 150],
    THICKNESS_RANGE: [0.05, 1.0],
    SAMPLED_GRAVITY: [0, 0.16, 0.38, 1.0],
    SAMPLED_GRAVITY_PROBS: [0.4, 0.15, 0.15, 0.3],
    LOC_NOISE: 0.6,
    SPREAD_NOISE: 0.12,

    // Risk classification
    HIGH_SPREAD: 4.0,   // mm/s
    P_LOW: 0.25,
    P_HIGH: 0.5,

    // CSV schema (also the contract for real experiment data)
    CSV_COLUMNS: ['fuel', 'o2_percent', 'pressure_atm', 'flow_cm_s', 'gravity_g', 'thickness_mm', 'flame_sustained', 'spread_rate_mm_s'],
  };
})((window.FIF = window.FIF || {}));
