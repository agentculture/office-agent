// office — search-first seat map (vanilla ES module).
//
// State model:
//   - URL is canonical: /offices/{office}/floors/{floor}?seat={seat}&asOf={date}
//   - On load + on history pop, sync state from URL.
//   - User actions (search click, floor switch, seat click) push history state.
//   - The merged view is fetched via /api/floors/{id} and the SVG via /floors/{id}.svg.
//
// Fuse.js is loaded as a separate module via index.html so window.Fuse exists.

const FUSE_OPTIONS = {
  threshold: 0.35,
  ignoreLocation: true,
  keys: ["seat_id", "employee_email", "cluster", "floor", "name", "role"],
};

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
  currentFloorId: null,
  currentOfficeId: null,
  seats: [],
  fuse: null,
};

function urlState() {
  const path = window.location.pathname;
  const m = path.match(/^\/offices\/([^/]+)\/floors\/([^/]+)\/?$/);
  const params = new URLSearchParams(window.location.search);
  return {
    office: m ? m[1] : null,
    floor: m ? m[2] : null,
    seat: params.get("seat"),
    asOf: params.get("asOf"),
  };
}

function pushUrl(office, floor, seat) {
  const params = new URLSearchParams(window.location.search);
  if (seat) {
    params.set("seat", seat);
  } else {
    params.delete("seat");
  }
  const qs = params.toString();
  const next = `/offices/${office}/floors/${floor}${qs ? "?" + qs : ""}`;
  if (next !== window.location.pathname + window.location.search) {
    history.pushState({ office, floor, seat }, "", next);
  }
}

async function fetchJSON(path) {
  const r = await fetch(path);
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} for ${path}`);
  }
  return r.json();
}

async function fetchText(path) {
  const r = await fetch(path);
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} for ${path}`);
  }
  return r.text();
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

function renderResults(matches) {
  if (!matches.length) {
    els.results.innerHTML = '<p class="empty">No matches.</p>';
    return;
  }
  const html = matches
    .map((m) => {
      const s = m.item.raw;
      const who = s.hidden && s.employee_email
        ? "(private)"
        : s.employee_email || "(vacant)";
      return `
        <div class="result-item" tabindex="0" data-seat="${s.seat_id}">
          <div class="seat-id">${s.seat_id}</div>
          <div class="meta">${who} — ${s.floor}</div>
        </div>`;
    })
    .join("");
  els.results.innerHTML = html;
  for (const node of els.results.querySelectorAll(".result-item")) {
    node.addEventListener("click", () => selectSeat(node.dataset.seat));
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        selectSeat(node.dataset.seat);
      }
    });
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
  const target = els.map.querySelector(`#${CSS.escape(seatId)}`);
  if (!target) return;
  target.classList.add("highlighted");
  target.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
}

function renderDetail(seatId) {
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
  els.detail.hidden = false;
  els.detail.innerHTML = `
    <h2>${s.seat_id}</h2>
    <dl>
      <dt>Floor</dt><dd>${s.floor}</dd>
      <dt>Person</dt><dd>${who}</dd>
      <dt>Last updated</dt><dd>${s.last_updated || "—"}</dd>
      ${s.notes ? `<dt>Notes</dt><dd>${s.notes}</dd>` : ""}
    </dl>
    <div>
      ${s.hidden ? '<span class="chip">private</span>' : ""}
    </div>
  `;
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
    els.results.innerHTML = '<p class="empty">Type to search…</p>';
    return;
  }
  const matches = state.fuse ? state.fuse.search(q).slice(0, 50) : [];
  renderResults(matches);
}, 150);

async function loadFloor(officeId, floorId) {
  const data = await fetchJSON(`/api/floors/${floorId}`);
  state.currentOfficeId = officeId;
  state.currentFloorId = floorId;
  state.seats = data.seats;
  state.fuse = window.Fuse ? new window.Fuse(state.seats.map(searchableSeat), FUSE_OPTIONS) : null;

  const svgText = await fetchText(data.svg_url);
  els.map.innerHTML = svgText;
  applySeatClasses();

  // Bind seat clicks in the SVG.
  for (const node of els.map.querySelectorAll(".seat, .room")) {
    node.style.cursor = "pointer";
    node.addEventListener("click", () => selectSeat(node.id));
  }
}

async function loadOffices() {
  const data = await fetchJSON("/api/offices");
  state.offices = data.offices;
  // Populate the floor picker with all floors across all offices.
  const opts = [];
  for (const office of state.offices) {
    for (const floor of office.floors) {
      opts.push(
        `<option value="${office.id}|${floor.id}">${office.name} / ${floor.id}</option>`,
      );
    }
  }
  els.floorPicker.innerHTML = opts.join("");
  els.floorPicker.addEventListener("change", () => {
    const [officeId, floorId] = els.floorPicker.value.split("|");
    loadFloor(officeId, floorId);
    pushUrl(officeId, floorId, null);
  });
}

function setFloorPickerValue(officeId, floorId) {
  els.floorPicker.value = `${officeId}|${floorId}`;
}

function showAsOfBanner(date) {
  if (!date) {
    els.banner.hidden = true;
    return;
  }
  els.banner.hidden = false;
  els.banner.textContent = `as-of ${date} is parsed but not yet enforced (Stage 6).`;
}

async function syncFromUrl() {
  const u = urlState();
  showAsOfBanner(u.asOf);
  if (!u.office || !u.floor) return;
  if (state.currentFloorId !== u.floor) {
    await loadFloor(u.office, u.floor);
    setFloorPickerValue(u.office, u.floor);
  }
  if (u.seat) {
    highlight(u.seat);
    renderDetail(u.seat);
  } else {
    renderDetail(null);
  }
}

window.addEventListener("popstate", syncFromUrl);
els.search.addEventListener("input", onSearch);

(async function main() {
  els.results.innerHTML = '<p class="empty">Type to search…</p>';
  await loadOffices();
  await syncFromUrl();
})().catch((err) => {
  console.error(err);
  els.banner.hidden = false;
  els.banner.textContent = `Failed to load: ${err.message}`;
});
