/* MapView Editor — client-side floorplan editor */

const state = {
  mapinfo: null,
  currentMap: null,
  currentData: null,
  tool: "select",
  selection: null,      // { type: "device"|"zone", index: number }
  pan: { x: 0, y: 0 },
  zoom: 1,
  isPanning: false,
  panStart: null,
  isDragging: false,
  dragStart: null,
  drawPoints: [],       // for zone drawing
  editingVertex: null,  // { zoneIndex, vertexIndex }
  dirty: false,
  labels: null,         // { devices, models, zones, zonesByParent } from /api/labels
  showDeviceLabels: true,
  familyColors: {},     // device family -> dot color, assigned when labels load
  pendingFocus: null,   // { id, x, y } — device to center/highlight after a map loads
  missingImages: [],    // map keys with no floorplan PNG — export is refused until fixed
};

// Every response that carries the map index also says which maps have no
// floorplan image; keep both together so the list and the export agree.
function setMapinfo(mi) {
  state.mapinfo = mi;
  state.missingImages = (mi && mi.missingImages) || [];
}

// Colorblind-safe categorical palette (Okabe-Ito + extras) for device families.
const FAMILY_PALETTE = [
  "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2",
  "#D55E00", "#CC79A7", "#FFFFFF", "#B2DF8A", "#FB9A99",
];

// Group nLight model names into device families — a real site can have 20+
// distinct models on one floor, far more than any palette can distinguish.
// Prefixes are vendor product lines, not site conventions. Anything
// unrecognized becomes its own group named by its first model token.
function modelFamily(model) {
  const m = String(model).trim().toUpperCase();
  if (/^N?CM\b|^N?CM-|^NES\b|^NES-|^NWSX/.test(m)) return "Sensors";
  if (m.startsWith("NPOD")) return "WallPods";
  if (m.startsWith("NPP")) return "Power packs";
  if (m.startsWith("NPS")) return "Power supplies";
  if (m.startsWith("NIO")) return "I/O interfaces";
  if (m.startsWith("NBRG") || m.startsWith("NGWY") || m.startsWith("NECY")) {
    return "Backbone (bridge/gateway)";
  }
  return String(model).trim().split(/[-\s]/)[0];
}

// DOM refs
const $ = (sel) => document.querySelector(sel);
const dropZone = $("#dropZone");
const fileInput = $("#fileInput");
const welcomeScreen = $("#welcomeScreen");
const sidebar = $("#sidebar");
const mapList = $("#mapList");
const toolbar = $("#toolbar");
const canvasWrap = $("#canvasWrap");
const canvasInner = $("#canvasInner");
const floorplanImg = $("#floorplanImg");
const overlaySvg = $("#overlaySvg");
const propsPanel = $("#propsPanel");
const btnExport = $("#btnExport");
const btnSortMaps = $("#btnSortMaps");
const btnAddMap = $("#btnAddMap");
const btnDeleteSelected = $("#btnDeleteSelected");
const btnReplaceImage = $("#btnReplaceImage");
const imageInput = $("#imageInput");
const toolInfo = $("#toolInfo");
const statusText = $("#statusText");
const tooltip = $("#tooltip");
const searchWrap = $("#searchWrap");
const searchBox = $("#searchBox");
const searchResults = $("#searchResults");
const btnLoadDb = $("#btnLoadDb");
const dbInput = $("#dbInput");
const labelsBadge = $("#labelsBadge");
const labelsBadgeText = $("#labelsBadgeText");
const btnClearLabels = $("#btnClearLabels");
const btnToggleLabels = $("#btnToggleLabels");

// ─── File upload ───

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

async function uploadFile(file) {
  statusText.textContent = "Loading...";
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok) {
      setMapinfo(data.mapinfo);
      adoptRevision(data);
      showEditor();
      const n = state.missingImages.length;
      toast("Loaded " + state.mapinfo.maps.length + " maps" +
            (n ? ` · ${n} without a floorplan image (⚠ in the list) — export is blocked until fixed` : ""));
    } else {
      toast("Error: " + (data.error || "Upload failed"));
    }
  } catch (err) {
    toast("Upload failed: " + err.message);
  }
  statusText.textContent = "";
}

function showEditor() {
  welcomeScreen.style.display = "none";
  sidebar.style.display = "flex";
  btnExport.style.display = "";
  btnLoadDb.style.display = "";
  searchWrap.style.display = "";
  renderMapList();
}

// ─── Database labels (read-only overlay from a .svdb / sensor.mdb) ───

function deviceLabel(id) {
  if (!state.labels) return null;
  return state.labels.devices[String(id || "").trim().toUpperCase()] || null;
}

function deviceModel(id) {
  if (!state.labels) return null;
  return state.labels.models[String(id || "").trim().toUpperCase()] || null;
}

function zoneLabel(z) {
  if (!state.labels) return null;
  const byId = state.labels.zones[String(z.id)];
  if (byId) return byId;
  const key = `${String(z.ParentDeviceID || "").trim().toUpperCase()}:${z.Port}`;
  return state.labels.zonesByParent[key] || null;
}

function applyLabels(data) {
  state.labels = {
    devices: data.devices || {},
    models: data.models || {},
    zones: data.zones || {},
    zonesByParent: data.zonesByParent || {},
  };
  state.familyColors = {};
  const families = [...new Set(Object.values(state.labels.models).map(modelFamily))].sort();
  families.forEach((f, i) => { state.familyColors[f] = FAMILY_PALETTE[i % FAMILY_PALETTE.length]; });
  const s = data.stats || {};
  labelsBadgeText.textContent =
    `${data.source} — ${s.devicesMatched ?? 0}/${s.devicesTotal ?? 0} devices, ` +
    `${s.zonesMatched ?? 0}/${s.zonesTotal ?? 0} zones matched`;
  labelsBadge.style.display = "flex";
  btnToggleLabels.style.display = "";
  btnToggleLabels.classList.toggle("active", state.showDeviceLabels);
  renderOverlay();
  updatePropsPanel();
}

btnLoadDb.addEventListener("click", () => dbInput.click());
dbInput.addEventListener("change", async () => {
  const file = dbInput.files[0];
  if (!file) return;
  statusText.textContent = "Reading database...";
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/labels", { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok) {
      adoptRevision(data);
      lastLabelsSource = data.source;
      applyLabels(data);
      toast("Database labels loaded");
    } else {
      toast(data.error || "Could not read database");
    }
  } catch (err) {
    toast("Database load failed: " + err.message);
  }
  statusText.textContent = "";
  dbInput.value = "";
});

btnClearLabels.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/labels", { method: "DELETE" });
    adoptRevision(await res.json());
    lastLabelsSource = null;
  } catch { /* server state is best-effort; clear the UI regardless */ }
  state.labels = null;
  state.familyColors = {};
  labelsBadge.style.display = "none";
  btnToggleLabels.style.display = "none";
  renderOverlay();
  updatePropsPanel();
});

btnToggleLabels.addEventListener("click", () => {
  state.showDeviceLabels = !state.showDeviceLabels;
  btnToggleLabels.classList.toggle("active", state.showDeviceLabels);
  renderOverlay();
});

async function rehydrateLabels() {
  try {
    const res = await fetch("/api/labels");
    const data = await res.json();
    if (data.loaded) {
      applyLabels(data);
    } else if (state.labels) {
      // Cleared outside this browser (MCP/API) — drop the overlay too.
      state.labels = null;
      state.familyColors = {};
      labelsBadge.style.display = "none";
      btnToggleLabels.style.display = "none";
      renderOverlay();
      updatePropsPanel();
    }
  } catch { /* no labels loaded */ }
}

// ─── Live sync (external edits from the MCP server / API) ───
//
// Every mutating server response carries a revision number; the browser adopts
// the ones it caused itself. A 2-second poll spots revisions it didn't cause —
// an MCP tool or curl changed something — and reloads the affected state so
// external edits appear in the open editor as they happen.

let lastRevision = null;
let lastLabelsSource = null;

function adoptRevision(data) {
  if (data && typeof data.revision === "number") lastRevision = data.revision;
}

async function checkRevision() {
  if (!state.mapinfo) return;
  let info;
  try {
    info = await (await fetch("/api/revision")).json();
  } catch { return; /* server briefly unreachable */ }
  if (lastRevision === null) {
    lastRevision = info.revision;
    lastLabelsSource = info.labelsSource;
    return;
  }
  if (info.revision === lastRevision) return;
  lastRevision = info.revision;
  const labelsChanged = info.labelsSource !== lastLabelsSource;
  lastLabelsSource = info.labelsSource;
  await onRemoteChange(labelsChanged);
}

async function onRemoteChange(labelsChanged) {
  try {
    const mi = await (await fetch("/api/mapinfo")).json();
    setMapinfo(mi);
    renderMapList();
    if (labelsChanged) await rehydrateLabels();

    if (!state.currentMap) return;
    if (!mi.maps.some(m => m.file === state.currentMap)) {
      // The open map was deleted externally.
      state.currentMap = null;
      state.currentData = null;
      state.selection = null;
      toolbar.style.display = "none";
      canvasWrap.style.display = "none";
      propsPanel.classList.remove("visible");
      toast("The open map was removed outside the editor");
      return;
    }
    if (state.dirty) {
      // Don't clobber local unsaved work; Marcus decides which version wins.
      toast("Map changed outside the editor — Ctrl+S keeps your local edits");
      return;
    }
    const res = await fetch(`/api/map/${state.currentMap}/data`);
    state.currentData = await res.json();
    flipDevicesFromStorage(state.currentData);
    if (state.selection?.type === "device" &&
        state.selection.index >= (state.currentData.devices || []).length) state.selection = null;
    if (state.selection?.type === "zone" &&
        state.selection.index >= (state.currentData.zones || []).length) state.selection = null;
    renderOverlay();
    updatePropsPanel();
    statusText.textContent = "Synced external change";
    setTimeout(() => { if (statusText.textContent === "Synced external change") statusText.textContent = ""; }, 2000);
  } catch { /* transient — next poll retries */ }
}

setInterval(checkRevision, 2000);

// ─── Device search (Ctrl+F) ───

function mapDisplayName(fileKey) {
  const entry = state.mapinfo?.maps.find(m => m.file === fileKey);
  return entry ? `${entry.group ? entry.group + " / " : ""}${entry.name}` : fileKey;
}

async function fetchDeviceIndex() {
  // Flush unsaved edits so the index reflects what's on screen.
  if (state.dirty && state.currentMap) await saveCurrentMap();
  const res = await fetch("/api/index");
  return (await res.json()).devices || [];
}

function searchRow({ label, id, mapKey, note, onClick }) {
  const row = document.createElement("div");
  row.className = "search-row";
  const name = document.createElement("span");
  name.className = "sr-name";
  name.textContent = label || "(no name)";
  const idEl = document.createElement("span");
  idEl.className = "sr-id";
  idEl.textContent = id;
  const mapEl = document.createElement("span");
  mapEl.className = note ? "sr-dup" : "sr-map";
  mapEl.textContent = note || mapDisplayName(mapKey);
  row.appendChild(name);
  row.appendChild(idEl);
  row.appendChild(mapEl);
  row.addEventListener("mousedown", (e) => { e.preventDefault(); onClick(); });
  return row;
}

function renderSearchNote(text) {
  const note = document.createElement("div");
  note.className = "search-note";
  note.textContent = text;
  searchResults.appendChild(note);
}

async function runSearch(query) {
  const q = query.trim().toUpperCase();
  searchResults.innerHTML = "";
  searchResults.style.display = "block";
  let index;
  try {
    index = await fetchDeviceIndex();
  } catch {
    renderSearchNote("Search unavailable — is a .mvdb loaded?");
    return;
  }

  if (!q) {
    // Empty query: offer the duplicate check.
    const dupRow = document.createElement("div");
    dupRow.className = "search-row";
    dupRow.textContent = "Check for duplicate device IDs on the same map";
    dupRow.addEventListener("mousedown", (e) => { e.preventDefault(); showDuplicates(index); });
    searchResults.appendChild(dupRow);
    renderSearchNote("Type a device ID or name to search all maps.");
    return;
  }

  const matches = index.filter(d => {
    const id = String(d.id || "").toUpperCase();
    if (id.includes(q)) return true;
    const lbl = deviceLabel(d.id);
    return lbl ? lbl.toUpperCase().includes(q) : false;
  });

  if (!matches.length) {
    renderSearchNote(`No devices match "${query.trim()}".`);
    return;
  }
  const MAX = 50;
  for (const m of matches.slice(0, MAX)) {
    searchResults.appendChild(searchRow({
      label: deviceLabel(m.id),
      id: m.id,
      mapKey: m.map,
      onClick: () => { closeSearch(); jumpToDevice(m); },
    }));
  }
  const extra = matches.length > MAX ? ` — showing first ${MAX}` : "";
  renderSearchNote(`${matches.length} match${matches.length === 1 ? "" : "es"}${extra}.`);
}

function showDuplicates(index) {
  searchResults.innerHTML = "";
  const counts = {};
  for (const d of index) {
    const key = `${d.map}|${String(d.id || "").toUpperCase()}`;
    (counts[key] = counts[key] || []).push(d);
  }
  const dups = Object.values(counts).filter(list => list.length > 1);
  if (!dups.length) {
    renderSearchNote("No duplicate device IDs found on any single map.");
    return;
  }
  for (const list of dups) {
    for (const d of list) {
      searchResults.appendChild(searchRow({
        label: deviceLabel(d.id),
        id: d.id,
        mapKey: d.map,
        note: `x${list.length} on ${mapDisplayName(d.map)}`,
        onClick: () => { closeSearch(); jumpToDevice(d); },
      }));
    }
  }
  renderSearchNote(`${dups.length} duplicated ID${dups.length === 1 ? "" : "s"} (same device on different maps is not flagged).`);
}

function focusDevice(dev) {
  // Center the view on the device, select it, and pulse a ring around it.
  // `dev` comes from /api/index in STORAGE convention; in-memory device y is
  // image-space, so flip for the exact-position match.
  const devices = state.currentData.devices || [];
  let idx = devices.findIndex(d => d.id === dev.id && d.x === dev.x && d.y === flipY(dev.y));
  if (idx === -1) idx = devices.findIndex(d => d.id === dev.id);
  if (idx === -1) return;
  const target = devices[idx];
  state.zoom = Math.max(state.zoom, 0.6);
  state.pan.x = canvasWrap.clientWidth / 2 - target.x * state.zoom;
  state.pan.y = canvasWrap.clientHeight / 2 - target.y * state.zoom;
  applyTransform();
  state.selection = { type: "device", index: idx };
  renderOverlay();
  updatePropsPanel();
  btnDeleteSelected.style.display = "";
  const ring = svgEl("circle", { cx: target.x, cy: target.y, class: "pulse-ring" });
  overlaySvg.appendChild(ring);
  setTimeout(() => ring.remove(), 4000);
}

function jumpToDevice(dev) {
  if (dev.map === state.currentMap && state.currentData) {
    focusDevice(dev);
  } else {
    // Map loads async; floorplanImg.onload applies the pending focus after fit.
    state.pendingFocus = { id: dev.id, x: dev.x, y: dev.y };
    loadMap(dev.map);
  }
}

function closeSearch() {
  searchResults.style.display = "none";
  searchBox.blur();
}

let searchDebounce = null;
searchBox.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => runSearch(searchBox.value), 200);
});
searchBox.addEventListener("focus", () => runSearch(searchBox.value));
searchBox.addEventListener("blur", () => setTimeout(() => { searchResults.style.display = "none"; }, 150));
searchBox.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { searchBox.value = ""; closeSearch(); }
  if (e.key === "Enter") {
    const first = searchResults.querySelector(".search-row");
    if (first) first.dispatchEvent(new Event("mousedown"));
  }
});

// ─── Map list ───

// The list is the navigation tree SensorView shows in its MapView drop-down:
// group order and the order of maps inside a group are exactly the order of
// entries in mapinfo. Drag a map to reorder it or move it to another group,
// drag a group header to reorder groups, double-click a header to rename the
// group. Every change is written back through PUT /api/mapinfo.

function groupedMaps() {
  const groups = new Map();
  for (const m of state.mapinfo.maps) {
    const g = m.group || "";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(m);
  }
  return groups;
}

function renderMapList() {
  mapList.innerHTML = "";
  const missing = new Set(state.missingImages || []);
  for (const [group, maps] of groupedMaps()) {
    const hdr = document.createElement("div");
    hdr.className = "map-group-header";
    hdr.dataset.group = group;
    hdr.draggable = true;
    hdr.title = "Drag to reorder groups · double-click to rename · drop a map here to move it into this group";
    const label = document.createElement("span");
    label.textContent = group || "(no group)";
    const count = document.createElement("span");
    count.className = "group-count";
    count.textContent = maps.length;
    hdr.appendChild(label);
    hdr.appendChild(count);
    hdr.addEventListener("dblclick", () => renameGroup(group));
    wireGroupDrag(hdr, group);
    mapList.appendChild(hdr);

    for (const m of maps) {
      const item = document.createElement("div");
      item.className = "map-item" + (state.currentMap === m.file ? " active" : "");
      item.dataset.file = m.file;
      item.draggable = true;

      const nameSpan = document.createElement("span");
      nameSpan.className = "map-name";
      nameSpan.textContent = m.name;
      nameSpan.title = m.name + " — drag to reorder or move to another group";

      if (missing.has(m.file)) {
        const warn = document.createElement("span");
        warn.className = "map-warn";
        warn.textContent = "⚠";
        warn.title = "No floorplan image — export is blocked until one is added (Replace Image) or the map is deleted";
        item.appendChild(warn);
      }

      const delBtn = document.createElement("button");
      delBtn.className = "map-delete";
      delBtn.textContent = "×";
      delBtn.title = "Delete map";
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteMap(m.file, m.name);
      });

      item.insertBefore(nameSpan, item.firstChild);
      item.appendChild(delBtn);
      item.addEventListener("click", () => loadMap(m.file));
      item.addEventListener("dblclick", () => renameMap(m.file));
      wireMapDrag(item, m.file);
      mapList.appendChild(item);
    }
  }
}

// ─── Navigation tree editing ───

const drag = { kind: null, key: null };   // kind: "map" | "group"

function clearDropMarks() {
  mapList.querySelectorAll(".drop-before, .drop-after, .drop-into")
    .forEach(el => el.classList.remove("drop-before", "drop-after", "drop-into"));
}

function dropHalf(e, el) {
  const r = el.getBoundingClientRect();
  return (e.clientY - r.top) < r.height / 2 ? "before" : "after";
}

function wireMapDrag(item, fileKey) {
  item.addEventListener("dragstart", (e) => {
    drag.kind = "map"; drag.key = fileKey;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", fileKey);
    item.classList.add("dragging");
  });
  item.addEventListener("dragend", () => { item.classList.remove("dragging"); clearDropMarks(); });
  item.addEventListener("dragover", (e) => {
    if (drag.kind !== "map" || drag.key === fileKey) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    clearDropMarks();
    item.classList.add(dropHalf(e, item) === "before" ? "drop-before" : "drop-after");
  });
  item.addEventListener("dragleave", () => item.classList.remove("drop-before", "drop-after"));
  item.addEventListener("drop", async (e) => {
    if (drag.kind !== "map" || drag.key === fileKey) return;
    e.preventDefault();
    const half = dropHalf(e, item);
    clearDropMarks();
    const maps = state.mapinfo.maps.slice();
    const moving = maps.find(m => m.file === drag.key);
    const target = maps.find(m => m.file === fileKey);
    maps.splice(maps.indexOf(moving), 1);
    let at = maps.indexOf(target) + (half === "after" ? 1 : 0);
    maps.splice(at, 0, moving);
    const movedGroup = moving.group !== target.group;
    moving.group = target.group;
    await commitMapOrder(maps, movedGroup ? `Moved to ${target.group || "(no group)"}` : "Reordered");
  });
}

function wireGroupDrag(hdr, group) {
  hdr.addEventListener("dragstart", (e) => {
    drag.kind = "group"; drag.key = group;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", group);
    hdr.classList.add("dragging");
  });
  hdr.addEventListener("dragend", () => { hdr.classList.remove("dragging"); clearDropMarks(); });
  hdr.addEventListener("dragover", (e) => {
    if (drag.kind === "map") {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      clearDropMarks();
      hdr.classList.add("drop-into");
    } else if (drag.kind === "group" && drag.key !== group) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      clearDropMarks();
      hdr.classList.add(dropHalf(e, hdr) === "before" ? "drop-before" : "drop-after");
    }
  });
  hdr.addEventListener("dragleave", () => hdr.classList.remove("drop-before", "drop-after", "drop-into"));
  hdr.addEventListener("drop", async (e) => {
    e.preventDefault();
    const half = dropHalf(e, hdr);
    clearDropMarks();
    if (drag.kind === "map") {
      // Drop on a header = move the map to the end of that group.
      const maps = state.mapinfo.maps.slice();
      const moving = maps.find(m => m.file === drag.key);
      maps.splice(maps.indexOf(moving), 1);
      moving.group = group;
      let at = maps.length;
      for (let i = maps.length - 1; i >= 0; i--) {
        if ((maps[i].group || "") === group) { at = i + 1; break; }
      }
      if (at === maps.length && !maps.some(m => (m.group || "") === group)) at = maps.length;
      maps.splice(at, 0, moving);
      await commitMapOrder(maps, `Moved to ${group || "(no group)"}`);
    } else if (drag.kind === "group" && drag.key !== group) {
      const groups = Array.from(groupedMaps().keys());
      groups.splice(groups.indexOf(drag.key), 1);
      let at = groups.indexOf(group) + (half === "after" ? 1 : 0);
      groups.splice(at, 0, drag.key);
      const byGroup = groupedMaps();
      const maps = [];
      for (const g of groups) maps.push(...byGroup.get(g));
      await commitMapOrder(maps, "Groups reordered");
    }
  });
}

async function commitMapOrder(maps, msg) {
  try {
    const res = await fetch("/api/mapinfo", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maps }),
    });
    const data = await res.json();
    if (!res.ok) { toast("Error: " + (data.error || res.status)); return; }
    setMapinfo(data.mapinfo);
    adoptRevision(data);
    renderMapList();
    if (msg) toast(msg);
  } catch (err) {
    toast("Error: " + err.message);
  }
}

function renameGroup(group) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>Rename Group</h3>
      <label>Building Group (applies to every map in it)</label>
      <input type="text" id="renameGroupName">
      <div class="modal-actions">
        <button class="btn" id="modalCancel">Cancel</button>
        <button class="btn primary" id="modalOk">Save</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const input = overlay.querySelector("#renameGroupName");
  input.value = group;
  input.focus(); input.select();
  overlay.querySelector("#modalCancel").addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  const doSave = async () => {
    const name = input.value.trim();
    overlay.remove();
    if (name === group) return;
    const maps = state.mapinfo.maps.map(m => ((m.group || "") === group ? { ...m, group: name } : m));
    await commitMapOrder(maps, `Group renamed to ${name || "(no group)"}`);
  };
  overlay.querySelector("#modalOk").addEventListener("click", doSave);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") doSave(); });
}

btnSortMaps.addEventListener("click", async () => {
  if (!state.mapinfo) return;
  if (!confirm("Sort every building's maps by level and write names as LEVEL nn (e.g. 'Level 01_Lobby' becomes 'LEVEL 01 - LOBBY')?\nGroups keep their order. Ctrl+Z does not undo this; re-drag if needed.")) return;
  try {
    const res = await fetch("/api/mapinfo/sort", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ normalize: true }),
    });
    const data = await res.json();
    if (!res.ok) { toast("Error: " + (data.error || res.status)); return; }
    setMapinfo(data.mapinfo);
    adoptRevision(data);
    renderMapList();
    const n = (data.renamed || []).length;
    toast("Sorted by level" + (n ? ` · ${n} name${n === 1 ? "" : "s"} normalised` : ""));
  } catch (err) {
    toast("Error: " + err.message);
  }
});

async function loadMap(fileKey) {
  if (state.dirty && state.currentMap) {
    await saveCurrentMap();
  }
  state.currentMap = fileKey;
  state.selection = null;
  state.drawPoints = [];
  state.editingVertex = null;
  statusText.textContent = "Loading map...";

  try {
    const res = await fetch(`/api/map/${fileKey}/data`);
    state.currentData = await res.json();
    flipDevicesFromStorage(state.currentData);
  } catch {
    state.currentData = { width: 4000, height: 3000, zones: [], subzones: [], devices: [] };
  }

  floorplanImg.src = `/api/map/${fileKey}/image?t=${Date.now()}`;
  floorplanImg.onload = () => {
    const w = state.currentData.width || floorplanImg.naturalWidth;
    const h = state.currentData.height || floorplanImg.naturalHeight;
    floorplanImg.style.width = w + "px";
    floorplanImg.style.height = h + "px";
    overlaySvg.setAttribute("width", w);
    overlaySvg.setAttribute("height", h);
    overlaySvg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    fitToView(w, h);
    renderOverlay();
    toolbar.style.display = "flex";
    canvasWrap.style.display = "block";
    statusText.textContent = "";
    state.dirty = false;
    renderMapList();
    updatePropsPanel();
    updateToolInfo();
    if (state.pendingFocus) {
      focusDevice(state.pendingFocus);
      state.pendingFocus = null;
    }
  };
  floorplanImg.onerror = () => {
    toolbar.style.display = "flex";
    canvasWrap.style.display = "block";
    floorplanImg.style.width = "4000px";
    floorplanImg.style.height = "3000px";
    overlaySvg.setAttribute("width", 4000);
    overlaySvg.setAttribute("height", 3000);
    overlaySvg.setAttribute("viewBox", "0 0 4000 3000");
    fitToView(4000, 3000);
    renderOverlay();
    statusText.textContent = "No image — upload a floorplan PNG";
    renderMapList();
    if (state.pendingFocus) {
      focusDevice(state.pendingFocus);
      state.pendingFocus = null;
    }
  };
}

function fitToView(w, h) {
  const cw = canvasWrap.clientWidth;
  const ch = canvasWrap.clientHeight;
  if (!cw || !ch) return;
  state.zoom = Math.min(cw / w, ch / h) * 0.95;
  state.pan.x = (cw - w * state.zoom) / 2;
  state.pan.y = (ch - h * state.zoom) / 2;
  applyTransform();
}

function applyTransform() {
  canvasInner.style.transform = `translate(${state.pan.x}px, ${state.pan.y}px) scale(${state.zoom})`;
}

// ─── Save ───

async function saveCurrentMap() {
  if (!state.currentMap || !state.currentData) return;
  try {
    // Serialize back to storage convention (device y-up); in-memory stays image-space.
    const payload = {
      ...state.currentData,
      devices: (state.currentData.devices || []).map(d => ({ ...d, y: flipY(d.y) })),
    };
    const res = await fetch(`/api/map/${state.currentMap}/data`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    adoptRevision(await res.json());
    state.dirty = false;
  } catch (err) {
    toast("Save failed: " + err.message);
  }
}

// ─── Overlay rendering ───

function renderOverlay() {
  if (!state.currentData) return;
  overlaySvg.innerHTML = "";

  // Zones
  const zones = state.currentData.zones || [];
  zones.forEach((z, i) => {
    const points = parsePolygon(z.coords);
    if (!points.length) return;
    const poly = svgEl("polygon", {
      points: points.map(p => `${p[0]},${p[1]}`).join(" "),
      class: "zone-poly" + (state.selection?.type === "zone" && state.selection.index === i ? " selected" : ""),
    });
    poly.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.tool === "select" || state.tool === "edit-zone") {
        state.selection = { type: "zone", index: i };
        renderOverlay();
        updatePropsPanel();
        btnDeleteSelected.style.display = "";
      }
    });
    overlaySvg.appendChild(poly);

    // Zone label
    const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
    const cy = points.reduce((s, p) => s + p[1], 0) / points.length;
    const label = svgEl("text", {
      x: cx, y: cy,
      fill: "#fff",
      "font-size": "14",
      "text-anchor": "middle",
      "dominant-baseline": "middle",
      "pointer-events": "none",
      opacity: "0.7",
    });
    label.textContent = zoneLabel(z) || z.id;
    overlaySvg.appendChild(label);

    // Vertex handles when editing
    if (state.tool === "edit-zone" && state.selection?.type === "zone" && state.selection.index === i) {
      points.forEach((p, vi) => {
        const circle = svgEl("circle", {
          cx: p[0], cy: p[1], r: 6,
          class: "zone-vertex" + (state.editingVertex?.zoneIndex === i && state.editingVertex?.vertexIndex === vi ? " selected" : ""),
        });
        circle.addEventListener("mousedown", (e) => {
          e.stopPropagation();
          state.editingVertex = { zoneIndex: i, vertexIndex: vi };
          state.isDragging = true;
          renderOverlay();
        });
        overlaySvg.appendChild(circle);
      });
    }
  });

  // Draw preview
  if (state.tool === "draw-zone" && state.drawPoints.length > 0) {
    const pts = state.drawPoints.map(p => `${p[0]},${p[1]}`).join(" ");
    const poly = svgEl("polygon", { points: pts, class: "draw-preview" });
    overlaySvg.appendChild(poly);
    state.drawPoints.forEach((p) => {
      overlaySvg.appendChild(svgEl("circle", {
        cx: p[0], cy: p[1], r: 5,
        fill: "var(--accent2)", stroke: "#fff", "stroke-width": 1.5,
        "pointer-events": "none",
      }));
    });
  }

  // Devices — dot radius follows the map's own deviceScale setting so markers
  // stay findable when a large floorplan is zoomed to fit.
  const devices = state.currentData.devices || [];
  const baseR = (state.currentData.deviceScale || 20) / 2;
  devices.forEach((d, i) => {
    const g = svgEl("g", { class: "device-marker", "data-index": i });
    const isSelected = state.selection?.type === "device" && state.selection.index === i;
    const r = isSelected ? Math.round(baseR * 1.3) : baseR;
    const circle = svgEl("circle", {
      cx: d.x, cy: d.y, r: r,
      class: "device-dot" + (isSelected ? " selected" : ""),
    });
    // Color by device family when the database is loaded. Inline style would
    // beat the stylesheet's selected-gold, so only color unselected dots.
    const model = deviceModel(d.id);
    if (model && !isSelected && state.familyColors[modelFamily(model)]) {
      circle.style.fill = state.familyColors[modelFamily(model)];
    }
    g.appendChild(circle);

    if (state.showDeviceLabels) {
      const lbl = deviceLabel(d.id);
      if (lbl) {
        const t = svgEl("text", { x: d.x + r + 4, y: d.y + 4, class: "device-label" });
        t.textContent = lbl;
        g.appendChild(t);
      }
    }

    g.addEventListener("click", (e) => {
      e.stopPropagation();
      if (state.tool === "select" || state.tool === "move-device") {
        state.selection = { type: "device", index: i };
        renderOverlay();
        updatePropsPanel();
        btnDeleteSelected.style.display = "";
      }
    });

    g.addEventListener("mousedown", (e) => {
      if (state.tool === "move-device" || state.tool === "select") {
        state.selection = { type: "device", index: i };
        state.isDragging = true;
        state.dragStart = canvasCoords(e);
        renderOverlay();
        updatePropsPanel();
        btnDeleteSelected.style.display = "";
        e.stopPropagation();
      }
    });

    g.addEventListener("mouseenter", (e) => {
      const lbl = deviceLabel(d.id);
      const base = lbl ? `${lbl} (${d.id})` : d.id;
      tooltip.textContent = model ? `${base} — ${model}` : base;
      tooltip.style.display = "block";
      tooltip.style.left = (e.clientX + 12) + "px";
      tooltip.style.top = (e.clientY - 8) + "px";
    });
    g.addEventListener("mousemove", (e) => {
      tooltip.style.left = (e.clientX + 12) + "px";
      tooltip.style.top = (e.clientY - 8) + "px";
    });
    g.addEventListener("mouseleave", () => { tooltip.style.display = "none"; });

    overlaySvg.appendChild(g);
  });

  updateLegend(devices);
}

// Legend of device families present on the current map. Memoized on content so
// renderOverlay (which runs on every drag) doesn't rebuild the DOM needlessly.
let legendKey = null;
function updateLegend(devices) {
  const legend = document.getElementById("deviceLegend");
  const families = state.labels
    ? [...new Set(devices.map(d => deviceModel(d.id)).filter(Boolean).map(modelFamily))].sort()
    : [];
  if (!families.length) {
    legend.style.display = "none";
    legendKey = null;
    return;
  }
  const key = families.join("|");
  if (key === legendKey) return;
  legendKey = key;
  legend.innerHTML = "";
  for (const f of families) {
    const row = document.createElement("div");
    row.className = "legend-row";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = state.familyColors[f] || "var(--device)";
    const name = document.createElement("span");
    name.textContent = f; // family names can echo external model text — textContent only
    row.appendChild(swatch);
    row.appendChild(name);
    legend.appendChild(row);
  }
  legend.style.display = "block";
}

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

// MapView stores BOTH zone polygons AND device y y-up (origin bottom-left),
// while the SVG overlay and the floorplan PNG are y-down (origin top-left).
// Flip y across the map height so both align with the plan. The flip is its
// own inverse, so applying it on read and write round-trips exactly.
// (Device y was misread as y-down until v1.2.0 — dots rendered mirrored, which
// went unnoticed while they were anonymous; database labels exposed it.)
// If height is unknown (no map loaded), pass coords through unchanged.
function flipY(y) {
  const h = state.currentData && state.currentData.height;
  return h ? h - y : y;
}

// Convert freshly-fetched map JSON (storage convention) to in-memory
// image-space device coords. Everything after load — render, drag, props,
// search focus — then works in one coordinate system; saveCurrentMap flips
// back on serialize.
function flipDevicesFromStorage(data) {
  const h = data && data.height;
  if (!h) return;
  for (const d of data.devices || []) d.y = h - d.y;
}

function parsePolygon(wkt) {
  if (!wkt) return [];
  const m = wkt.match(/POLYGON\(\((.*)\)\)/i);
  if (!m) return [];
  return m[1].split(",").map(pair => {
    const [x, y] = pair.trim().split(/\s+/).map(Number);
    return [x, flipY(y)];
  }).filter(p => !isNaN(p[0]) && !isNaN(p[1]));
}

function toPolygonWKT(points) {
  const coords = points.map(p => `${p[0]} ${flipY(p[1])}`).join(",");
  return `POLYGON((${coords}))`;
}

// ─── Canvas interaction ───

canvasWrap.addEventListener("mousedown", (e) => {
  if (e.button === 1 || (e.button === 0 && e.altKey)) {
    state.isPanning = true;
    state.panStart = { x: e.clientX - state.pan.x, y: e.clientY - state.pan.y };
    canvasWrap.style.cursor = "grabbing";
    e.preventDefault();
    return;
  }
  if (e.button === 0 && state.tool === "select" && !e.target.closest(".device-marker, .zone-poly")) {
    state.isPanning = true;
    state.panStart = { x: e.clientX - state.pan.x, y: e.clientY - state.pan.y };
    canvasWrap.style.cursor = "grabbing";
  }
});

canvasWrap.addEventListener("mousemove", (e) => {
  if (state.isPanning) {
    state.pan.x = e.clientX - state.panStart.x;
    state.pan.y = e.clientY - state.panStart.y;
    applyTransform();
    return;
  }
  if (state.isDragging) {
    const coords = canvasCoords(e);
    if (state.selection?.type === "device") {
      const dev = state.currentData.devices[state.selection.index];
      if (dev) {
        dev.x = Math.round(coords.x);
        dev.y = Math.round(coords.y);
        state.dirty = true;
        renderOverlay();
        updatePropsPanel();
      }
    }
    if (state.editingVertex) {
      const zone = state.currentData.zones[state.editingVertex.zoneIndex];
      if (zone) {
        const pts = parsePolygon(zone.coords);
        pts[state.editingVertex.vertexIndex] = [coords.x, coords.y];
        zone.coords = toPolygonWKT(pts);
        state.dirty = true;
        renderOverlay();
      }
    }
  }
});

canvasWrap.addEventListener("mouseup", (e) => {
  if (state.isPanning) {
    state.isPanning = false;
    canvasWrap.style.cursor = "";
  }
  if (state.isDragging) {
    state.isDragging = false;
    state.editingVertex = null;
  }
});

canvasWrap.addEventListener("wheel", (e) => {
  e.preventDefault();
  const rect = canvasWrap.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const prevZoom = state.zoom;
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  state.zoom = Math.max(0.05, Math.min(10, state.zoom * delta));
  state.pan.x = mx - (mx - state.pan.x) * (state.zoom / prevZoom);
  state.pan.y = my - (my - state.pan.y) * (state.zoom / prevZoom);
  applyTransform();
}, { passive: false });

canvasWrap.addEventListener("click", (e) => {
  const coords = canvasCoords(e);

  if (state.tool === "add-device" && !e.target.closest(".device-marker")) {
    showAddDeviceModal(Math.round(coords.x), Math.round(coords.y));
    return;
  }

  if (state.tool === "draw-zone") {
    state.drawPoints.push([Math.round(coords.x), Math.round(coords.y)]);
    renderOverlay();
    updateToolInfo();
    return;
  }

  if (!e.target.closest(".device-marker, .zone-poly, .zone-vertex")) {
    state.selection = null;
    btnDeleteSelected.style.display = "none";
    renderOverlay();
    updatePropsPanel();
  }
});

canvasWrap.addEventListener("dblclick", (e) => {
  if (state.tool === "draw-zone" && state.drawPoints.length >= 3) {
    finishDrawZone();
  }
});

canvasWrap.addEventListener("contextmenu", (e) => e.preventDefault());

function canvasCoords(e) {
  const rect = canvasWrap.getBoundingClientRect();
  return {
    x: (e.clientX - rect.left - state.pan.x) / state.zoom,
    y: (e.clientY - rect.top - state.pan.y) / state.zoom,
  };
}

// ─── Tools ───

document.querySelectorAll(".tool-btn[data-tool]").forEach(btn => {
  btn.addEventListener("click", () => {
    setTool(btn.dataset.tool);
  });
});

function setTool(tool) {
  if (state.tool === "draw-zone" && state.drawPoints.length > 0 && tool !== "draw-zone") {
    if (state.drawPoints.length >= 3) {
      finishDrawZone();
    } else {
      state.drawPoints = [];
    }
  }
  state.tool = tool;
  state.editingVertex = null;
  document.querySelectorAll(".tool-btn[data-tool]").forEach(b => {
    b.classList.toggle("active", b.dataset.tool === tool);
  });
  updateToolInfo();
  renderOverlay();
}

function updateToolInfo() {
  const msgs = {
    select: "Click to select. Drag to pan.",
    "move-device": "Click a device, then drag to move.",
    "add-device": "Click on the map to place a device.",
    "draw-zone": state.drawPoints.length > 0
      ? `${state.drawPoints.length} points — double-click to finish`
      : "Click to add points. Double-click to close polygon.",
    "edit-zone": "Select a zone, then drag vertices to reshape.",
  };
  toolInfo.textContent = msgs[state.tool] || "";
}

function finishDrawZone() {
  if (state.drawPoints.length < 3) return;
  const pts = [...state.drawPoints, state.drawPoints[0]];
  const existingIds = (state.currentData.zones || []).map(z => z.id);
  let newId = 1;
  while (existingIds.includes(newId)) newId++;

  state.currentData.zones = state.currentData.zones || [];
  state.currentData.zones.push({
    id: newId,
    ParentDeviceID: "",
    Port: 0,
    coords: toPolygonWKT(pts),
  });
  state.drawPoints = [];
  state.dirty = true;
  state.selection = { type: "zone", index: state.currentData.zones.length - 1 };
  renderOverlay();
  updatePropsPanel();
  updateToolInfo();
  btnDeleteSelected.style.display = "";
  toast("Zone " + newId + " created");
}

// ─── Delete selected ───

btnDeleteSelected.addEventListener("click", () => {
  if (!state.selection || !state.currentData) return;
  const { type, index } = state.selection;
  if (type === "device") {
    const dev = state.currentData.devices[index];
    if (!confirm(`Delete device ${dev.id}?`)) return;
    state.currentData.devices.splice(index, 1);
  } else if (type === "zone") {
    const zone = state.currentData.zones[index];
    if (!confirm(`Delete zone ${zone.id}?`)) return;
    state.currentData.zones.splice(index, 1);
  }
  state.selection = null;
  state.dirty = true;
  btnDeleteSelected.style.display = "none";
  renderOverlay();
  updatePropsPanel();
});

// ─── Add device modal ───

function showAddDeviceModal(x, y) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>Add Device</h3>
      <label>Device ID (hex)</label>
      <input type="text" id="newDeviceId" placeholder="e.g. 01C48262" maxlength="8"
             style="text-transform:uppercase; font-family:monospace">
      <div class="prop-row">
        <div><label>X</label><input type="number" id="newDeviceX" value="${x}"></div>
        <div><label>Y</label><input type="number" id="newDeviceY" value="${y}"></div>
      </div>
      <div class="modal-actions">
        <button class="btn" id="modalCancel">Cancel</button>
        <button class="btn primary" id="modalOk">Add</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const idInput = overlay.querySelector("#newDeviceId");
  idInput.focus();

  overlay.querySelector("#modalCancel").addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  const doAdd = () => {
    const id = idInput.value.trim().toUpperCase();
    const dx = parseInt(overlay.querySelector("#newDeviceX").value);
    const dy = parseInt(overlay.querySelector("#newDeviceY").value);
    if (!id) { toast("Device ID required"); return; }
    state.currentData.devices = state.currentData.devices || [];
    if (state.currentData.devices.some(d => d.id === id)) {
      if (!confirm(`Device ${id} is already on this map. Add it again anyway?`)) return;
    }
    state.currentData.devices.push({ id, x: dx, y: dy });
    state.dirty = true;
    state.selection = { type: "device", index: state.currentData.devices.length - 1 };
    renderOverlay();
    updatePropsPanel();
    btnDeleteSelected.style.display = "";
    overlay.remove();
    toast("Device " + id + " added");
  };
  overlay.querySelector("#modalOk").addEventListener("click", doAdd);
  idInput.addEventListener("keydown", (e) => { if (e.key === "Enter") doAdd(); });
}

// ─── Add map ───

btnAddMap.addEventListener("click", () => {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>Add Map</h3>
      <label>Building Group</label>
      <input type="text" id="newMapGroup" placeholder="e.g. BUILDING A" value="">
      <label>Map Name</label>
      <input type="text" id="newMapName" placeholder="e.g. LEVEL 05">
      <div class="modal-actions">
        <button class="btn" id="modalCancel">Cancel</button>
        <button class="btn primary" id="modalOk">Create</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector("#newMapName").focus();

  overlay.querySelector("#modalCancel").addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  overlay.querySelector("#modalOk").addEventListener("click", async () => {
    const group = overlay.querySelector("#newMapGroup").value.trim();
    const name = overlay.querySelector("#newMapName").value.trim();
    if (!name) { toast("Name required"); return; }
    try {
      const res = await fetch("/api/map/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group, name }),
      });
      const data = await res.json();
      if (data.ok) {
        setMapinfo(data.mapinfo);
        adoptRevision(data);
        renderMapList();
        loadMap(data.file);
        toast("Map created: " + name);
      }
    } catch (err) {
      toast("Error: " + err.message);
    }
    overlay.remove();
  });
});

// ─── Delete / Rename map ───

async function deleteMap(fileKey, name) {
  if (!confirm(`Delete map "${name}"?\nThis cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/map/${fileKey}`, { method: "DELETE" });
    const data = await res.json();
    if (data.ok) {
      setMapinfo(data.mapinfo);
      adoptRevision(data);
      if (state.currentMap === fileKey) {
        state.currentMap = null;
        state.currentData = null;
        toolbar.style.display = "none";
        canvasWrap.style.display = "none";
        propsPanel.classList.remove("visible");
      }
      renderMapList();
      toast("Deleted: " + name);
    }
  } catch (err) {
    toast("Error: " + err.message);
  }
}

function renameMap(fileKey) {
  const entry = state.mapinfo.maps.find(m => m.file === fileKey);
  if (!entry) return;

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>Rename Map</h3>
      <label>Building Group</label>
      <input type="text" id="renameGroup" value="${entry.group}">
      <label>Map Name</label>
      <input type="text" id="renameName" value="${entry.name}">
      <div class="modal-actions">
        <button class="btn" id="modalCancel">Cancel</button>
        <button class="btn primary" id="modalOk">Save</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector("#renameName").focus();
  overlay.querySelector("#renameName").select();

  overlay.querySelector("#modalCancel").addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  overlay.querySelector("#modalOk").addEventListener("click", async () => {
    entry.group = overlay.querySelector("#renameGroup").value.trim();
    entry.name = overlay.querySelector("#renameName").value.trim();
    try {
      const res = await fetch("/api/mapinfo", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ maps: state.mapinfo.maps }),
      });
      adoptRevision(await res.json());
      renderMapList();
      toast("Renamed");
    } catch (err) {
      toast("Error: " + err.message);
    }
    overlay.remove();
  });
}

// ─── Replace image ───

btnReplaceImage.addEventListener("click", () => imageInput.click());
imageInput.addEventListener("change", async () => {
  const file = imageInput.files[0];
  if (!file || !state.currentMap) return;
  const fd = new FormData();
  fd.append("image", file);
  statusText.textContent = "Uploading image...";
  try {
    const res = await fetch(`/api/map/${state.currentMap}/image`, { method: "POST", body: fd });
    const data = await res.json();
    if (data.ok) {
      adoptRevision(data);
      try { setMapinfo(await (await fetch("/api/mapinfo")).json()); renderMapList(); } catch { /* keep list */ }
      const newSrc = `/api/map/${state.currentMap}/image?t=${Date.now()}`;
      floorplanImg.src = newSrc;
      floorplanImg.onload = () => {
        const w = data.width || floorplanImg.naturalWidth;
        const h = data.height || floorplanImg.naturalHeight;
        state.currentData.width = w;
        state.currentData.height = h;
        floorplanImg.style.width = w + "px";
        floorplanImg.style.height = h + "px";
        overlaySvg.setAttribute("width", w);
        overlaySvg.setAttribute("height", h);
        overlaySvg.setAttribute("viewBox", `0 0 ${w} ${h}`);
        fitToView(w, h);
        state.dirty = true;
        renderOverlay();
        toast("Image replaced (" + w + " x " + h + ")");
      };
    }
  } catch (err) {
    toast("Error: " + err.message);
  }
  statusText.textContent = "";
  imageInput.value = "";
});

// ─── Properties panel ───

function updatePropsPanel() {
  if (!state.selection || !state.currentData) {
    propsPanel.classList.remove("visible");
    return;
  }
  propsPanel.classList.add("visible");
  const { type, index } = state.selection;

  if (type === "device") {
    const dev = state.currentData.devices[index];
    if (!dev) { propsPanel.classList.remove("visible"); return; }
    const devLabelRow = state.labels
      ? `<label>Label (from database)</label>
      <input type="text" id="propDevLabel" readonly style="opacity:.7">`
      : "";
    propsPanel.innerHTML = `
      <h3>Device</h3>
      <label>ID</label>
      <input type="text" value="${dev.id}" id="propDevId" style="font-family:monospace;text-transform:uppercase" maxlength="8">
      ${devLabelRow}
      <div class="prop-row">
        <div><label>X</label><input type="number" value="${dev.x}" id="propDevX"></div>
        <div><label>Y</label><input type="number" value="${dev.y}" id="propDevY"></div>
      </div>
      <br>
      <button class="btn danger" id="propDelete">Delete Device</button>`;
    if (state.labels) {
      // DB labels are external data — assign via .value, never innerHTML.
      propsPanel.querySelector("#propDevLabel").value = deviceLabel(dev.id) || "(no match)";
    }

    const updateDev = () => {
      dev.id = propsPanel.querySelector("#propDevId").value.trim().toUpperCase();
      dev.x = parseInt(propsPanel.querySelector("#propDevX").value) || 0;
      dev.y = parseInt(propsPanel.querySelector("#propDevY").value) || 0;
      state.dirty = true;
      if (state.currentData.devices.filter(d => d.id === dev.id).length > 1) {
        toast(`Note: ${dev.id} now appears more than once on this map`);
      }
      renderOverlay();
    };
    propsPanel.querySelector("#propDevId").addEventListener("change", updateDev);
    propsPanel.querySelector("#propDevX").addEventListener("change", updateDev);
    propsPanel.querySelector("#propDevY").addEventListener("change", updateDev);
    propsPanel.querySelector("#propDelete").addEventListener("click", () => btnDeleteSelected.click());
  }

  if (type === "zone") {
    const zone = state.currentData.zones[index];
    if (!zone) { propsPanel.classList.remove("visible"); return; }
    const pts = parsePolygon(zone.coords);
    const zoneLabelRow = state.labels
      ? `<label>Label (from database)</label>
      <input type="text" id="propZoneLabel" readonly style="opacity:.7">`
      : "";
    propsPanel.innerHTML = `
      <h3>Zone</h3>
      <label>Zone ID</label>
      <input type="number" value="${zone.id}" id="propZoneId">
      ${zoneLabelRow}
      <label>Parent Device ID</label>
      <input type="text" value="${zone.ParentDeviceID || ""}" id="propZoneParent" style="font-family:monospace;text-transform:uppercase">
      <label>Port</label>
      <input type="number" value="${zone.Port || 0}" id="propZonePort">
      <label>Vertices: ${pts.length}</label>
      <br>
      <button class="btn danger" id="propDelete">Delete Zone</button>`;
    if (state.labels) {
      propsPanel.querySelector("#propZoneLabel").value = zoneLabel(zone) || "(no match)";
    }

    const updateZone = () => {
      zone.id = parseInt(propsPanel.querySelector("#propZoneId").value) || zone.id;
      zone.ParentDeviceID = propsPanel.querySelector("#propZoneParent").value.trim().toUpperCase();
      zone.Port = parseInt(propsPanel.querySelector("#propZonePort").value) || 0;
      state.dirty = true;
      renderOverlay();
    };
    propsPanel.querySelector("#propZoneId").addEventListener("change", updateZone);
    propsPanel.querySelector("#propZoneParent").addEventListener("change", updateZone);
    propsPanel.querySelector("#propZonePort").addEventListener("change", updateZone);
    propsPanel.querySelector("#propDelete").addEventListener("click", () => btnDeleteSelected.click());
  }
}

// ─── Export ───

btnExport.addEventListener("click", async () => {
  if (state.dirty && state.currentMap) {
    await saveCurrentMap();
  }
  statusText.textContent = "Exporting...";
  try {
    const res = await fetch("/api/export", { method: "POST" });
    if (!res.ok) {
      let msg = "Export failed";
      try { const err = await res.json(); if (err.error) msg = err.error; } catch { /* not JSON */ }
      try { setMapinfo(await (await fetch("/api/mapinfo")).json()); renderMapList(); } catch { /* keep list */ }
      throw new Error(msg);
    }
    const before = parseInt(res.headers.get("X-Images-Before-Bytes") || "0");
    const after = parseInt(res.headers.get("X-Images-After-Bytes") || "0");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "MapViewExport_edited.mvdb";
    a.click();
    URL.revokeObjectURL(url);
    if (before > 0 && after > 0) {
      const pct = Math.round((1 - after / before) * 100);
      const mb = (n) => (n / 1024 / 1024).toFixed(1);
      toast(`Exported — images optimized ${mb(before)} MB → ${mb(after)} MB (${pct}% smaller)`);
    } else {
      toast("Export downloaded");
    }
  } catch (err) {
    toast("Export error: " + err.message);
  }
  statusText.textContent = "";
});

// ─── Keyboard shortcuts ───

document.addEventListener("keydown", (e) => {
  if (e.key === "f" && (e.ctrlKey || e.metaKey)) {
    if (searchWrap.style.display !== "none") {
      e.preventDefault();
      searchBox.focus();
      searchBox.select();
    }
    return;
  }
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

  if (e.key === "Escape") {
    if (state.tool === "draw-zone") {
      state.drawPoints = [];
      renderOverlay();
      updateToolInfo();
    }
    state.selection = null;
    btnDeleteSelected.style.display = "none";
    renderOverlay();
    updatePropsPanel();
  }
  if (e.key === "Delete" || e.key === "Backspace") {
    if (state.selection) btnDeleteSelected.click();
  }
  if (e.key === "1") setTool("select");
  if (e.key === "2") setTool("move-device");
  if (e.key === "3") setTool("add-device");
  if (e.key === "4") setTool("draw-zone");
  if (e.key === "5") setTool("edit-zone");
  if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    saveCurrentMap().then(() => toast("Saved"));
  }
  if (e.key === "f") {
    if (state.currentData) {
      const w = state.currentData.width || 4000;
      const h = state.currentData.height || 3000;
      fitToView(w, h);
    }
  }
});

// ─── Auto-save on map switch ───

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    saveCurrentMap();
    e.returnValue = "Unsaved changes";
  }
});

// ─── Toast ───

function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ─── Version badge ───

async function loadVersionBadge() {
  const badge = document.getElementById("versionBadge");
  try {
    const res = await fetch("/api/version");
    const v = await res.json();
    const dirtyFlag = v.dirty ? "+" : "";
    const git = v.commit && v.commit !== "unknown" ? ` (${v.branch}@${v.commit}${dirtyFlag})` : "";
    badge.textContent = `v${v.version || "?"}${git}`;
    badge.title = `Version: ${v.version || "unknown"}\nCommit: ${v.commit}${dirtyFlag}\nBranch: ${v.branch}\nDate: ${v.commitDate || "unknown"}`;
  } catch {
    badge.textContent = "";
  }
}

// ─── Init ───

// Restore a live session on page load: the server keeps its state across
// browser refreshes (and the MCP server may have loaded maps already), so if
// maps exist, skip the welcome screen instead of demanding a re-upload.
async function rehydrateMaps() {
  try {
    const mi = await (await fetch("/api/mapinfo")).json();
    if (mi.maps && mi.maps.length) {
      setMapinfo(mi);
      showEditor();
    }
  } catch { /* fresh server, nothing to restore */ }
}

updateToolInfo();
loadVersionBadge();
rehydrateMaps();
rehydrateLabels();
