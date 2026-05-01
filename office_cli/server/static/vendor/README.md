# Vendored frontend dependencies

`fuse.js` here is **not** the upstream Fuse.js library — it is a minimal
in-house fuzzy-search shim that exposes the subset of the Fuse.js API
(`new Fuse(items, options)`, `.search(query) -> [{item, score}]`) the
seat map needs. See the file header for the matching semantics it
implements.

We chose this over vendoring upstream Fuse.js to avoid pulling ~12KB of
minified third-party code into the repo. If the search experience needs
to grow — typo tolerance beyond a single character, n-gram weighting,
result highlighting — swap in the upstream library
([fusejs.io](https://fusejs.io)) here without any consumer-side change.

Upstream Fuse.js is MIT-licensed; if we replace this shim with the real
thing, copy the upstream `LICENSE` next to `fuse.js`.
