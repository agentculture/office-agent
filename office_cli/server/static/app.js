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
  results: document.getElementById("results"),
  map: document.getElementById("map"),
  detail: document.getElementById("detail"),
  banner: document.getElementById("banner"),
  floorPicker: document.getElementById("floor-picker"),
};

const state = {
  offices: [],
  knownFloorIds: new Set(),
  currentFloorId: null,
  currentOfficeId: null,
  currentAsOf: null,
  seats: [],
  fuse: null,
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
  els.results.replaceChildren();
  if (!matches.length) {
    els.results.appendChild(el("p", { className: "empty" }, "No matches."));
    return;
  }
  for (const m of matches) {
    const s = m.item.raw;
    const who = s.hidden && s.employee_email
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
    row.addEventListener("click", () => selectSeat(s.seat_id));
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSeat(s.seat_id);
      }
    });
    els.results.appendChild(row);
  }
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
    if (s.hidden && s.employee_email) {
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
  const who = s.hidden && s.employee_email
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

const onSearch = debounce(() => {
  const q = els.search.value.trim();
  if (!q) {
    els.results.replaceChildren(el("p", { className: "empty" }, "Type to search…"));
    return;
  }
  const matches = state.fuse ? state.fuse.search(q).slice(0, 50) : [];
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
  state.currentOfficeId = officeId;
  state.currentFloorId = floorId;
  state.currentAsOf = asOf || null;
  state.seats = data.seats;
  state.fuse = globalThis.Fuse
    ? new globalThis.Fuse(state.seats.map(searchableSeat), FUSE_OPTIONS)
    : null;

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
  state.knownFloorIds = new Set();
  els.floorPicker.replaceChildren();
  for (const office of state.offices) {
    for (const floor of office.floors) {
      state.knownFloorIds.add(floor.id);
      els.floorPicker.appendChild(
        el(
          "option",
          { value: `${office.id}|${floor.id}` },
          `${office.name} / ${floor.id}`,
        ),
      );
    }
  }
  els.floorPicker.addEventListener("change", async () => {
    const [officeId, floorId] = els.floorPicker.value.split("|");
    try {
      await loadFloor(officeId, floorId, urlState().asOf);
      pushUrl(officeId, floorId, null);
    } catch (err) {
      showError(err);
    }
  });
}

function setFloorPickerValue(officeId, floorId) {
  els.floorPicker.value = `${officeId}|${floorId}`;
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

els.results.replaceChildren(el("p", { className: "empty" }, "Type to search…"));

try {
  await loadOffices();
  await syncFromUrl();
} catch (err) {
  // eslint-disable-next-line no-console
  console.error(err);
  showError(err);
}
