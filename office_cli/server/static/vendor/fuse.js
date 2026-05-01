// Minimal fuzzy-search shim — exposes window.Fuse with the same .search() shape
// app.js expects. Not a drop-in replacement for the full Fuse.js library; it
// implements:
//
//   - Case-insensitive substring matching across the configured `keys`,
//   - A simple Damerau-style score (lower is better) so exact matches rank
//     above prefix matches above substring matches,
//   - A `threshold` like Fuse.js (results with score > threshold are dropped).
//
// We vendor this rather than the upstream Fuse.js to avoid pulling ~12KB of
// minified third-party code into the repo. For a v1 seat map at the
// hundreds-of-rows scale this is plenty; if the search experience grows
// (typo tolerance, n-gram weighting), swap in the real library here without
// any consumer-side change.

(function () {
  function getStr(item, key) {
    const v = item[key];
    return v == null ? "" : String(v).toLowerCase();
  }

  function bestMatch(haystack, needle) {
    // 0.0 = exact whole-string match
    // 0.1 = prefix match
    // 0.3 = substring match
    // 1.0 = no match
    if (!haystack) return 1.0;
    if (haystack === needle) return 0.0;
    if (haystack.startsWith(needle)) return 0.1;
    if (haystack.includes(needle)) return 0.3;
    // 1-char-deletion fuzz: try removing each char from haystack and
    // checking substring. Catches "dor" → "Dror".
    for (let i = 0; i < haystack.length; i++) {
      const trimmed = haystack.slice(0, i) + haystack.slice(i + 1);
      if (trimmed.includes(needle)) return 0.5;
    }
    return 1.0;
  }

  class Fuse {
    constructor(items, options) {
      this.items = items;
      this.options = Object.assign({ threshold: 0.6, keys: [] }, options || {});
    }
    search(query) {
      const q = String(query || "").toLowerCase().trim();
      if (!q) return [];
      const out = [];
      for (const item of this.items) {
        let best = 1.0;
        for (const key of this.options.keys) {
          const score = bestMatch(getStr(item, key), q);
          if (score < best) best = score;
        }
        if (best <= this.options.threshold) {
          out.push({ item, score: best });
        }
      }
      out.sort((a, b) => a.score - b.score);
      return out;
    }
  }

  window.Fuse = Fuse;
})();
