// office — search-first seat map (vanilla ES module).
//
// State model:
//   - URL is canonical: /offices/{office}/floors/{floor}?seat={seat}&asOf={date}
//   - On load + on history pop, sync state from URL.
//   - User actions (search click, floor switch, seat click) push history state.
//   - The merged view is fetched via /api/floors/{id} and the SVG via /svgs/{id}.svg.
//
// Fuse.js is loaded as a separate module via index.html so globalThis.Fuse
// exists by the time main() runs.
//
// XSS posture: every API-derived string lands in the DOM via createElement +
// textContent. The SVG (operator-supplied, traced in Inkscape) is parsed via
// DOMParser, sanitized to strip <script> / <foreignObject> / on*-attributes,
// then appended — never assigned to innerHTML.

const FUSE_OPTIONS = {
  threshold: 0.35,
  ignoreLocation: true,
  keys: ["seat_id", "employee_email", "cluster", "floor", "name", "role"],
};

const URL_PATH_RE = /^\/offices\/([^/]+)\/floors\/([^/]+)\/?$/;

const els = {
  search: document.getElementById("search"),
  searchScope: document.getElementById("search-scope"),
  results: document.getElementById("results"),
  resultsList: document.getElementById("results-list"),
  map: document.getElementById("map"),
  detail: document.getElementById("detail"),
  banner: document.getElementById("banner"),
  officePicker: document.getElementById("office-picker"),
  floorPicker: document.getElementById("floor-picker"),
  userInfo: document.getElementById("user-info"),
};

const state = {
  offices: [],
  officesById: new Map(),
  floorToOffice: new Map(),
  knownFloorIds: new Set(),
  currentFloorId: null,
  currentOfficeId: null,
  currentAsOf: null,
  seats: [],
  // Fuse indexes keyed by scope. "floor" rebuilds on every loadFloor;
  // "office" / "all" are built lazily and invalidated on as_of change
  // or office switch (for "office" only).
  fuses: { floor: null, office: null, all: null },
  fuseOfficeKey: null,
  searchGen: 0,
};

function urlState() {
  const path = globalThis.location.pathname;
  const m = URL_PATH_RE.exec(path);
  const params = new URLSearchParams(globalThis.location.search);
  return {
    office: m ? m[1] : null,
    floor: m ? m[2] : null,
    seat: params.get("seat"),
    asOf: params.get("asOf"),
  };
}

function pushUrl(office, floor, seat) {
  if (!office || !floor) return;
  const params = new URLSearchParams(globalThis.location.search);
  if (seat) {
    params.set("seat", seat);
  } else {
    params.delete("seat");
  }
  const qs = params.toString();
  const next = `/offices/${office}/floors/${floor}${qs ? "?" + qs : ""}`;
  if (next !== globalThis.location.pathname + globalThis.location.search) {
    history.pushState({ office, floor, seat }, "", next);
  }
}

// One fetcher per endpoint, with a hardcoded URL prefix and a
// regex-validated token. URLs are never built from a generic `path`
// parameter — that lets the static analyzer (and any reviewer) see at
// the fetch site that the URL is constructed from constants + a
// strictly-character-classed token.
const FLOOR_ID_RE = /^[A-Za-z0-9._-]+$/;
const SVG_NAME_RE = /^[A-Za-z0-9._-]+\.svg$/;
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function checkResponse(r, label) {
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} for ${label}`);
  }
  return r;
}

async function fetchOffices() {
  const r = await fetch("/api/offices");
  return (await checkResponse(r, "/api/offices")).json();
}

const OFFICE_ID_RE = /^[A-Za-z0-9._-]+$/;

async function fetchSeats(officeId, asOf) {
  const params = new URLSearchParams();
  if (officeId) {
    if (!OFFICE_ID_RE.test(officeId)) {
      throw new Error(`invalid office id: ${officeId}`);
    }
    params.set("office", officeId);
  }
  if (asOf) {
    if (!ISO_DATE_RE.test(asOf)) {
      throw new Error(`invalid asOf: ${asOf}`);
    }
    params.set("asOf", asOf);
  }
  const qs = params.toString();
  const url = `/api/seats${qs ? "?" + qs : ""}`;
  const r = await fetch(url);
  return (await checkResponse(r, "/api/seats")).json();
}

async function fetchFloor(floorId, asOf) {
  if (!FLOOR_ID_RE.test(floorId)) {
    throw new Error(`refusing to fetch floor with unexpected id: ${floorId}`);
  }
  let url = `/api/floors/${floorId}`;
  if (asOf) {
    if (!ISO_DATE_RE.test(asOf)) {
      throw new Error(`refusing to fetch floor with unexpected as_of: ${asOf}`);
    }
    url += `?as_of=${asOf}`;
  }
  const r = await fetch(url);
  return (await checkResponse(r, url)).json();
}

async function fetchSvgByName(svgName) {
  if (!SVG_NAME_RE.test(svgName)) {
    throw new Error(`refusing to fetch SVG with unexpected name: ${svgName}`);
  }
  const r = await fetch(`/svgs/${svgName}`);
  return (await checkResponse(r, `/svgs/${svgName}`)).text();
}

function svgNameFromUrl(svgUrl) {
  // The server returns ``svg_url: "/svgs/<name>.svg"`` — extract the name
  // and validate. We do not pass the full URL to fetch().
  if (typeof svgUrl !== "string") return "";
  const m = /^\/svgs\/([A-Za-z0-9._-]+\.svg)$/.exec(svgUrl);
  return m ? m[1] : "";
}

function searchableSeat(s) {
  // Build the row Fuse will index for one assignment.
  const cluster = (s.seat_id || "").split("-")[1] || "";
  return {
    seat_id: s.seat_id,
    employee_email: s.employee_email || "",
    cluster: cluster,
    floor: s.floor,
    name: "",
    role: "",
    raw: s,
  };
}

function applyAttr(node, key, value) {
  if (key === "dataset") {
    for (const [dk, dv] of Object.entries(value)) {
      node.dataset[dk] = dv;
    }
    return;
  }
  if (key === "className") {
    node.className = value;
    return;
  }
  if (key.startsWith("on") && typeof value === "function") {
    node.addEventListener(key.slice(2), value);
    return;
  }
  if (value !== false && value !== null && value !== undefined) {
    node.setAttribute(key, value);
  }
}

function appendChildOrText(node, child) {
  if (child == null) return;
  if (typeof child === "string") {
    node.appendChild(document.createTextNode(child));
  } else {
    node.appendChild(child);
  }
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    applyAttr(node, k, v);
  }
  for (const child of children) {
    appendChildOrText(node, child);
  }
  return node;
}

function renderResults(matches) {
  els.resultsList.replaceChildren();
  if (!matches.length) {
    els.resultsList.appendChild(el("p", { className: "empty" }, "No matches."));
    return;
  }
  for (const m of matches) {
    const s = m.item.raw;
    const who = s.redacted
      ? "(private)"
      : s.employee_email || "(vacant)";
    const row = el(
      "div",
      {
        className: "result-item",
        tabindex: "0",
        dataset: { seat: s.seat_id },
      },
      el("div", { className: "seat-id" }, s.seat_id),
      el("div", { className: "meta" }, `${who} — ${s.floor}`),
    );
    row.addEventListener("click", () => selectResult(s));
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectResult(s);
      }
    });
    els.resultsList.appendChild(row);
  }
}

async function selectResult(seat) {
  // A search result may live on a different floor (office or all-offices
  // scope) — navigate there first, then highlight the seat.
  if (seat.floor && seat.floor !== state.currentFloorId) {
    const officeId = state.floorToOffice.get(seat.floor);
    if (!officeId) {
      showError(new Error(`unknown office for floor ${seat.floor}`));
      return;
    }
    try {
      await loadFloor(officeId, seat.floor, state.currentAsOf);
      setFloorPickerValue(officeId, seat.floor);
    } catch (err) {
      showError(err);
      return;
    }
  }
  selectSeat(seat.seat_id);
}

function applySeatClasses() {
  // Reset all seat/room nodes, then set occupied/private from state.
  for (const node of els.map.querySelectorAll(".seat, .room")) {
    node.classList.remove("occupied", "private", "highlighted");
  }
  const bySeatId = new Map(state.seats.map((s) => [s.seat_id, s]));
  for (const node of els.map.querySelectorAll(".seat, .room")) {
    const sid = node.id;
    const s = bySeatId.get(sid);
    if (!s) continue;
    if (s.redacted) {
      node.classList.add("private");
    } else if (s.employee_email) {
      node.classList.add("occupied");
    }
  }
}

function highlight(seatId) {
  for (const node of els.map.querySelectorAll(".highlighted")) {
    node.classList.remove("highlighted");
  }
  if (!seatId) return;
  // CSS.escape ensures we cannot end up with selector injection from the URL.
  const target = els.map.querySelector(`#${CSS.escape(seatId)}`);
  if (!target) return;
  target.classList.add("highlighted");
  target.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
}

function renderDetail(seatId) {
  els.detail.replaceChildren();
  if (!seatId) {
    els.detail.hidden = true;
    return;
  }
  const s = state.seats.find((x) => x.seat_id === seatId);
  if (!s) {
    els.detail.hidden = true;
    return;
  }
  const who = s.redacted
    ? "(private)"
    : s.employee_email || "(vacant)";
  const dl = el(
    "dl",
    null,
    el("dt", null, "Floor"),
    el("dd", null, s.floor),
    el("dt", null, "Person"),
    el("dd", null, who),
    el("dt", null, "Last updated"),
    el("dd", null, s.last_updated || "—"),
  );
  if (s.notes) {
    dl.appendChild(el("dt", null, "Notes"));
    dl.appendChild(el("dd", null, s.notes));
  }
  els.detail.hidden = false;
  els.detail.appendChild(el("h2", null, s.seat_id));
  els.detail.appendChild(dl);
  if (s.hidden) {
    els.detail.appendChild(el("div", null, el("span", { className: "chip" }, "private")));
  }
}

function selectSeat(seatId) {
  highlight(seatId);
  renderDetail(seatId);
  pushUrl(state.currentOfficeId, state.currentFloorId, seatId);
}

function debounce(fn, ms) {
  let t = null;
  return function (...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), ms);
  };
}

async function ensureFuseFor(scope) {
  // Capture (officeId, asOf) at entry so the post-await write only lands
  // when the SPA's view of the world hasn't moved on. Otherwise a slow
  // /api/seats fetch could repopulate a cache that loadFloor() invalidated
  // mid-flight, producing stale search results for the new context.
  if (!globalThis.Fuse) return null;
  if (scope === "floor") {
    return state.fuses.floor;
  }
  const officeAtStart = state.currentOfficeId;
  const asOfAtStart = state.currentAsOf;
  if (scope === "office") {
    if (!officeAtStart) return null;
    if (state.fuses.office && state.fuseOfficeKey === officeAtStart) {
      return state.fuses.office;
    }
    const data = await fetchSeats(officeAtStart, asOfAtStart);
    const fuse = new globalThis.Fuse(data.seats.map(searchableSeat), FUSE_OPTIONS);
    if (
      state.currentOfficeId === officeAtStart
      && state.currentAsOf === asOfAtStart
    ) {
      state.fuses.office = fuse;
      state.fuseOfficeKey = officeAtStart;
    }
    return fuse;
  }
  if (scope === "all") {
    if (state.fuses.all) return state.fuses.all;
    const data = await fetchSeats("", asOfAtStart);
    const fuse = new globalThis.Fuse(data.seats.map(searchableSeat), FUSE_OPTIONS);
    if (state.currentAsOf === asOfAtStart) {
      state.fuses.all = fuse;
    }
    return fuse;
  }
  return null;
}

function searchScope() {
  return els.searchScope ? els.searchScope.value : "floor";
}

const onSearch = debounce(async () => {
  const q = els.search.value.trim();
  if (!q) {
    els.resultsList.replaceChildren(el("p", { className: "empty" }, "Type to search…"));
    return;
  }
  // Monotonic generation counter — debounce only cancels the timer, not
  // already-running async work. After awaits we discard if a newer
  // onSearch invocation has started, so old results never repaint over
  // newer ones.
  state.searchGen = (state.searchGen || 0) + 1;
  const gen = state.searchGen;
  const scopeAtStart = searchScope();
  const officeAtStart = state.currentOfficeId;
  const asOfAtStart = state.currentAsOf;
  let fuse;
  try {
    fuse = await ensureFuseFor(scopeAtStart);
  } catch (err) {
    if (gen !== state.searchGen) return;
    showError(err);
    return;
  }
  if (gen !== state.searchGen) return;
  if (
    searchScope() !== scopeAtStart
    || state.currentOfficeId !== officeAtStart
    || state.currentAsOf !== asOfAtStart
  ) {
    return;
  }
  const matches = fuse ? fuse.search(q).slice(0, 50) : [];
  renderResults(matches);
}, 150);

// Sanitize an SVG document tree before inlining: drop <script> /
// <foreignObject> elements (which can execute) and any attribute whose
// name begins with "on" (event handlers). The traced floor SVGs are
// operator-supplied and pass through `office floors validate` so the
// risk surface is small, but the defense in depth keeps the inline
// path safe even if a hostile SVG were ever served.
function sanitizeSvg(rootEl) {
  const dangerous = rootEl.querySelectorAll("script, foreignObject");
  for (const node of dangerous) {
    node.remove();
  }
  const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_ELEMENT);
  let cur = walker.currentNode;
  while (cur) {
    const attrs = Array.from(cur.attributes || []);
    for (const a of attrs) {
      const name = a.name.toLowerCase();
      if (name.startsWith("on") || name === "href" && a.value.toLowerCase().startsWith("javascript:")) {
        cur.removeAttribute(a.name);
      }
    }
    cur = walker.nextNode();
  }
  return rootEl;
}

function inlineSvg(svgText) {
  const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
  const svg = doc.documentElement;
  if (svg?.nodeName.toLowerCase() !== "svg") {
    throw new Error("response is not a valid SVG document");
  }
  sanitizeSvg(svg);
  els.map.replaceChildren(svg);
  return svg;
}

async function loadFloor(officeId, floorId, asOf) {
  // Validate against the offices index so a tainted URL cannot drive a
  // fetch to an arbitrary path. fetchFloor itself also validates the id
  // and as_of.
  if (!state.knownFloorIds.has(floorId)) {
    throw new Error(`unknown floor: ${floorId}`);
  }
  const data = await fetchFloor(floorId, asOf);
  const officeChanged = state.currentOfficeId !== officeId;
  const asOfChanged = state.currentAsOf !== (asOf || null);
  state.currentOfficeId = officeId;
  state.currentFloorId = floorId;
  state.currentAsOf = asOf || null;
  state.seats = data.seats;
  renderUserInfo(data.user || null);
  state.fuses.floor = globalThis.Fuse
    ? new globalThis.Fuse(state.seats.map(searchableSeat), FUSE_OPTIONS)
    : null;
  if (officeChanged) {
    state.fuses.office = null;
    state.fuseOfficeKey = null;
  }
  if (asOfChanged) {
    state.fuses.office = null;
    state.fuses.all = null;
    state.fuseOfficeKey = null;
  }

  const svgName = svgNameFromUrl(data.svg_url);
  if (!svgName) {
    throw new Error(`server returned unexpected svg_url: ${data.svg_url}`);
  }
  const svgText = await fetchSvgByName(svgName);
  inlineSvg(svgText);
  applySeatClasses();

  // Bind seat clicks in the SVG.
  for (const node of els.map.querySelectorAll(".seat, .room")) {
    node.style.cursor = "pointer";
    node.addEventListener("click", () => selectSeat(node.id));
  }
}

async function loadOffices() {
  const data = await fetchOffices();
  state.offices = data.offices;
  state.officesById = new Map(state.offices.map((o) => [o.id, o]));
  state.knownFloorIds = new Set();
  state.floorToOffice = new Map();
  for (const office of state.offices) {
    for (const floor of office.floors) {
      state.knownFloorIds.add(floor.id);
      state.floorToOffice.set(floor.id, office.id);
    }
  }
  populateOfficePicker();
  els.officePicker.addEventListener("change", async () => {
    const officeId = els.officePicker.value;
    populateFloorPicker(officeId);
    const office = state.officesById.get(officeId);
    if (!office?.floors.length) return;
    const floorId = office.floors[0].id;
    try {
      await loadFloor(officeId, floorId, urlState().asOf);
      pushUrl(officeId, floorId, null);
    } catch (err) {
      showError(err);
    }
  });
  els.floorPicker.addEventListener("change", async () => {
    const officeId = els.officePicker.value;
    const floorId = els.floorPicker.value;
    try {
      await loadFloor(officeId, floorId, urlState().asOf);
      pushUrl(officeId, floorId, null);
    } catch (err) {
      showError(err);
    }
  });
}

function populateOfficePicker() {
  els.officePicker.replaceChildren();
  for (const office of state.offices) {
    if (!office.floors.length) continue;
    els.officePicker.appendChild(
      el("option", { value: office.id }, office.name),
    );
  }
  // Seed the floor picker with the first office's floors so it isn't
  // blank before syncFromUrl runs.
  if (els.officePicker.value) {
    populateFloorPicker(els.officePicker.value);
  }
}

function populateFloorPicker(officeId) {
  els.floorPicker.replaceChildren();
  const office = state.officesById.get(officeId);
  if (!office) return;
  for (const floor of office.floors) {
    const label = floor.status === "draft" ? `${floor.id} (draft)` : floor.id;
    els.floorPicker.appendChild(el("option", { value: floor.id }, label));
  }
}

function setFloorPickerValue(officeId, floorId) {
  els.officePicker.value = officeId;
  populateFloorPicker(officeId);
  els.floorPicker.value = floorId;
}

function renderUserInfo(user) {
  // Stage 7: header slot showing the signed-in email + role + a logout
  // link. Hidden when the API response carries `user: null` (auth-
  // disabled mode for local dev).
  if (!els.userInfo) return;
  els.userInfo.replaceChildren();
  if (!user) {
    els.userInfo.hidden = true;
    return;
  }
  els.userInfo.hidden = false;
  els.userInfo.appendChild(el("span", { className: "user-email" }, user.email || ""));
  els.userInfo.appendChild(el("span", { className: "user-role" }, ` (${user.role || "viewer"})`));
  const logout = el("button", { type: "button", className: "logout" }, "Sign out");
  logout.addEventListener("click", async () => {
    try {
      await fetch("/auth/logout", { method: "POST", redirect: "manual" });
    } finally {
      globalThis.location.reload();
    }
  });
  els.userInfo.appendChild(logout);
}

function showAsOfBanner(date) {
  if (!date) {
    els.banner.hidden = true;
    els.banner.textContent = "";
    return;
  }
  els.banner.hidden = false;
  els.banner.textContent = `Showing seat map as of ${date}.`;
}

function showError(err) {
  els.banner.hidden = false;
  els.banner.textContent = `Failed to load: ${err.message}`;
}

async function syncFromUrl() {
  const u = urlState();
  if (u.asOf && !ISO_DATE_RE.test(u.asOf)) {
    showError(new Error(`asOf must be YYYY-MM-DD, got: ${u.asOf}`));
    return;
  }
  showAsOfBanner(u.asOf);
  if (!u.office || !u.floor) return;
  if (!state.knownFloorIds.has(u.floor)) {
    showError(new Error(`unknown floor: ${u.floor}`));
    return;
  }
  if (state.currentFloorId !== u.floor || state.currentAsOf !== u.asOf) {
    await loadFloor(u.office, u.floor, u.asOf);
    setFloorPickerValue(u.office, u.floor);
  }
  if (u.seat) {
    highlight(u.seat);
    renderDetail(u.seat);
  } else {
    renderDetail(null);
  }
}

globalThis.addEventListener("popstate", () => {
  syncFromUrl().catch(showError);
});
els.search.addEventListener("input", onSearch);
if (els.searchScope) {
  els.searchScope.addEventListener("change", onSearch);
}

els.resultsList.replaceChildren(el("p", { className: "empty" }, "Type to search…"));

try {
  await loadOffices();
  await syncFromUrl();
} catch (err) {
  // eslint-disable-next-line no-console
  console.error(err);
  showError(err);
}
