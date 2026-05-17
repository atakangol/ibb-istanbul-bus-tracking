/** Sidebar state, search, and line slot management. */

const MAX_SLOTS = 3;
const SEARCH_DEBOUNCE_MS = 300;

const slots = [null, null, null];

const searchInput = document.getElementById("line-search");
const searchResults = document.getElementById("search-results");
const searchStatus = document.getElementById("search-status");
const lineSlotsEl = document.getElementById("line-slots");
const toastEl = document.getElementById("toast");

let searchTimer = null;
let toastTimer = null;

function showToast(message, { error = false } = {}) {
  toastEl.textContent = message;
  toastEl.classList.toggle("error", error);
  toastEl.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add("hidden"), 4000);
}

function activeCount() {
  return slots.filter(Boolean).length;
}

function firstEmptySlotIndex() {
  return slots.findIndex((s) => s === null);
}

function findSlotByRoute(code, direction) {
  return slots.findIndex(
    (s) => s && s.code === code && s.direction === direction,
  );
}

function usedDirectionsForCode(code) {
  const dirs = new Set();
  slots.forEach((s) => {
    if (s && s.code === code) {
      dirs.add(s.direction);
    }
  });
  return dirs;
}

function defaultDirectionForNewLine(code) {
  const used = usedDirectionsForCode(code);
  if (!used.has("D")) return "D";
  if (!used.has("G")) return "G";
  return "D";
}

function setSearchStatus(text, visible = true) {
  searchStatus.textContent = text;
  searchStatus.classList.toggle("hidden", !visible);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

async function searchLines(query) {
  const params = new URLSearchParams({ q: query, limit: "20" });
  return fetchJson(`/api/lines/search?${params}`);
}

async function fetchRoute(code, direction) {
  const params = new URLSearchParams({ direction });
  return fetchJson(`/api/lines/${encodeURIComponent(code)}/route?${params}`);
}

function renderSearchResults(results) {
  searchResults.innerHTML = "";
  if (!results.length) {
    searchResults.classList.add("hidden");
    setSearchStatus("No lines found.", true);
    return;
  }

  setSearchStatus("", false);
  searchResults.classList.remove("hidden");

  results.forEach((line) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.innerHTML =
      `<span class="line-code">${escapeHtml(line.code)}</span>` +
      `<span class="line-name">${escapeHtml(line.name || "")}</span>`;
    btn.addEventListener("click", () => addLine(line.code));
    li.appendChild(btn);
    searchResults.appendChild(li);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function addLine(code) {
  const direction = defaultDirectionForNewLine(code);
  if (findSlotByRoute(code, direction) >= 0) {
    showToast(
      `Line ${code} direction ${direction} is already on the map. Pick another direction in that slot.`,
      { error: true },
    );
    return;
  }

  const slotIndex = firstEmptySlotIndex();
  if (slotIndex < 0) {
    showToast("Maximum 3 routes. Remove one to add another.", { error: true });
    return;
  }

  searchResults.classList.add("hidden");
  searchInput.value = "";
  setSearchStatus("Loading route (street snap)…", true);

  try {
    const route = await fetchRoute(code, direction);
    slots[slotIndex] = {
      code: route.code,
      name: route.name,
      direction: route.direction,
    };
    IstanbulMap.renderRoute(slotIndex, route);
    renderSlots();
    IstanbulMap.fitAllSlots();
    setSearchStatus("", false);
  } catch (err) {
    showToast(err.message || "Failed to load line.", { error: true });
    setSearchStatus("", false);
  }
}

async function changeDirection(slotIndex, direction, selectEl) {
  const slot = slots[slotIndex];
  if (!slot || slot.direction === direction) return;

  const duplicate = findSlotByRoute(slot.code, direction);
  if (duplicate >= 0 && duplicate !== slotIndex) {
    showToast(
      `Line ${slot.code} direction ${direction} is already in slot ${duplicate + 1}.`,
      { error: true },
    );
    if (selectEl) {
      selectEl.value = slot.direction;
    }
    return;
  }

  try {
    const route = await fetchRoute(slot.code, direction);
    slot.direction = direction;
    slot.name = route.name || slot.name;
    IstanbulMap.renderRoute(slotIndex, route);
    renderSlots();
    IstanbulMap.fitAllSlots();
  } catch (err) {
    showToast(err.message || "Failed to load direction.", { error: true });
  }
}

function removeSlot(slotIndex) {
  slots[slotIndex] = null;
  IstanbulMap.clearSlot(slotIndex);
  renderSlots();
  IstanbulMap.fitAllSlots();
}

function renderSlots() {
  lineSlotsEl.innerHTML = "";

  for (let i = 0; i < MAX_SLOTS; i += 1) {
    const slot = slots[i];
    const el = document.createElement("div");
    el.className = "slot" + (slot ? "" : " empty");

    if (!slot) {
      el.textContent = `Slot ${i + 1} — empty`;
      lineSlotsEl.appendChild(el);
      continue;
    }

    const color = document.createElement("span");
    color.className = "slot-color";
    color.style.background = IstanbulMap.colorForSlot(i);

    const info = document.createElement("div");
    info.className = "slot-info";
    info.innerHTML =
      `<div class="slot-code">${escapeHtml(slot.code)} · ${escapeHtml(slot.direction)}</div>` +
      (slot.name
        ? `<div class="slot-name">${escapeHtml(slot.name)}</div>`
        : "");

    const select = document.createElement("select");
    select.className = "slot-direction";
    select.title = "Direction";
    ["D", "G"].forEach((dir) => {
      const opt = document.createElement("option");
      opt.value = dir;
      opt.textContent = dir;
      if (dir === slot.direction) opt.selected = true;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => changeDirection(i, select.value, select));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "slot-remove";
    remove.textContent = "×";
    remove.title = "Remove line";
    remove.addEventListener("click", () => removeSlot(i));

    el.append(color, info, select, remove);
    lineSlotsEl.appendChild(el);
  }
}

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();

  if (!query) {
    searchResults.classList.add("hidden");
    setSearchStatus("", false);
    return;
  }

  if (activeCount() >= MAX_SLOTS) {
    searchResults.classList.add("hidden");
    setSearchStatus("All 3 slots are in use. Remove a line to search.", true);
    return;
  }

  searchTimer = setTimeout(async () => {
    setSearchStatus("Searching…", true);
    try {
      const data = await searchLines(query);
      renderSearchResults(data);
    } catch (err) {
      searchResults.classList.add("hidden");
      setSearchStatus(err.message || "Search failed.", true);
    }
  }, SEARCH_DEBOUNCE_MS);
});

document.addEventListener("click", (event) => {
  if (
    !searchResults.contains(event.target) &&
    event.target !== searchInput
  ) {
    searchResults.classList.add("hidden");
  }
});

IstanbulMap.init();
renderSlots();
