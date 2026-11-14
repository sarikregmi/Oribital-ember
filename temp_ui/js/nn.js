/*
 * A small dependency-free neural network (multi-layer perceptron) with Adam.
 * 'binary' kind  -> sigmoid output, cross-entropy loss (classification)
 * 'linear' kind  -> linear output, squared-error loss (regression)
 */
(function (FIF) {
  class MLP {
    constructor(sizes, kind, rng) {
      this.sizes = sizes;
      this.kind = kind;
      this.W = [];
      this.b = [];
      if (rng) {
        for (let l = 0; l < sizes.length - 1; l++) {
          const fanIn = sizes[l], fanOut = sizes[l + 1];
          const scale = Math.sqrt(2 / fanIn);
          const w = new Float64Array(fanIn * fanOut);
          for (let i = 0; i < w.length; i++) w[i] = FIF.data.normal(rng) * scale;
          this.W.push(w);
          this.b.push(new Float64Array(fanOut));
        }
      }
    }

    predict(x) {
      let a = x;
      const L = this.sizes.length - 1;
      for (let l = 0; l < L; l++) {
        const nIn = this.sizes[l], nOut = this.sizes[l + 1];
        const W = this.W[l], b = this.b[l];
        const z = new Float64Array(nOut);
        for (let j = 0; j < nOut; j++) {
          let s = b[j];
          for (let i = 0; i < nIn; i++) s += a[i] * W[i * nOut + j];
          z[j] = l === L - 1 ? s : s > 0 ? s : 0;
        }
        a = z;
      }
      return this.kind === 'binary' ? 1 / (1 + Math.exp(-a[0])) : a[0];
    }

    /** Train with minibatch Adam. Yields to the browser between epochs. */
    async fit(X, y, { epochs = 40, batch = 64, lr = 0.004, rng, onEpoch } = {}) {
      const L = this.sizes.length - 1;
      const n = X.length;
      const m = this.W.map((w) => new Float64Array(w.length));
      const v = this.W.map((w) => new Float64Array(w.length));
      const mb = this.b.map((b) => new Float64Array(b.length));
      const vb = this.b.map((b) => new Float64Array(b.length));
      const gW = this.W.map((w) => new Float64Array(w.length));
      const gb = this.b.map((b) => new Float64Array(b.length));
      const order = Array.from({ length: n }, (_, i) => i);
      const beta1 = 0.9, beta2 = 0.999, eps = 1e-8;
      let step = 0;

      for (let epoch = 0; epoch < epochs; epoch++) {
        for (let i = n - 1; i > 0; i--) {
          const j = Math.floor(rng() * (i + 1));
          [order[i], order[j]] = [order[j], order[i]];
        }
        const rate = lr * (0.5 * (1 + Math.cos((Math.PI * epoch) / epochs)) * 0.9 + 0.1); // cosine decay
        for (let start = 0; start < n; start += batch) {
          const end = Math.min(start + batch, n);
          for (let l = 0; l < L; l++) { gW[l].fill(0); gb[l].fill(0); }

          for (let k = start; k < end; k++) {
            const idx = order[k];
            // forward, keeping activations
            const acts = [X[idx]];
            for (let l = 0; l < L; l++) {
              const nIn = this.sizes[l], nOut = this.sizes[l + 1];
              const W = this.W[l], b = this.b[l], a = acts[l];
              const z = new Float64Array(nOut);
              for (let j = 0; j < nOut; j++) {
                let s = b[j];
                for (let i = 0; i < nIn; i++) s += a[i] * W[i * nOut + j];
                z[j] = l === L - 1 ? s : s > 0 ? s : 0;
              }
              acts.push(z);
            }
            const out = this.kind === 'binary' ? 1 / (1 + Math.exp(-acts[L][0])) : acts[L][0];
            let delta = new Float64Array([out - y[idx]]);
            // backward
            for (let l = L - 1; l >= 0; l--) {
              const nIn = this.sizes[l], nOut = this.sizes[l + 1];
              const W = this.W[l], a = acts[l];
              const prev = l > 0 ? new Float64Array(nIn) : null;
              for (let i = 0; i < nIn; i++) {
                const ai = a[i];
                for (let j = 0; j < nOut; j++) {
                  gW[l][i * nOut + j] += ai * delta[j];
                  if (prev) prev[i] += W[i * nOut + j] * delta[j];
                }
              }
              for (let j = 0; j < nOut; j++) gb[l][j] += delta[j];
              if (prev) {
                for (let i = 0; i < nIn; i++) if (a[i] <= 0) prev[i] = 0;
                delta = prev;
              }
            }
          }

          // Adam update
          step++;
          const inv = 1 / (end - start);
          const c1 = 1 - Math.pow(beta1, step), c2 = 1 - Math.pow(beta2, step);
          for (let l = 0; l < L; l++) {
            const W = this.W[l], b = this.b[l];
            for (let i = 0; i < W.length; i++) {
              const g = gW[l][i] * inv;
              m[l][i] = beta1 * m[l][i] + (1 - beta1) * g;
              v[l][i] = beta2 * v[l][i] + (1 - beta2) * g * g;
              W[i] -= (rate * (m[l][i] / c1)) / (Math.sqrt(v[l][i] / c2) + eps);
            }
            for (let i = 0; i < b.length; i++) {
              const g = gb[l][i] * inv;
              mb[l][i] = beta1 * mb[l][i] + (1 - beta1) * g;
              vb[l][i] = beta2 * vb[l][i] + (1 - beta2) * g * g;
              b[i] -= (rate * (mb[l][i] / c1)) / (Math.sqrt(vb[l][i] / c2) + eps);
            }
          }
        }
        if (onEpoch) onEpoch(epoch, epochs);
        await new Promise((r) => setTimeout(r, 0));
      }
    }

    toJSON() {
      return { sizes: this.sizes, kind: this.kind, W: this.W.map((w) => Array.from(w)), b: this.b.map((b) => Array.from(b)) };
    }
    static fromJSON(o) {
      const net = new MLP(o.sizes, o.kind, null);
      net.W = o.W.map((w) => Float64Array.from(w));
      net.b = o.b.map((b) => Float64Array.from(b));
      return net;
    }
  }

  FIF.nn = { MLP };
})(window.FIF);
