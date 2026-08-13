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
};

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
const btnAddMap = $("#btnAddMap");
const btnDeleteSelected = $("#btnDeleteSelected");
const btnReplaceImage = $("#btnReplaceImage");
const imageInput = $("#imageInput");
const toolInfo = $("#toolInfo");
const statusText = $("#statusText");
const tooltip = $("#tooltip");
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
      state.mapinfo = data.mapinfo;
      showEditor();
      toast("Loaded " + state.mapinfo.maps.length + " maps");
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
    await fetch("/api/labels", { method: "DELETE" });
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
    if (data.loaded) applyLabels(data);
  } catch { /* no labels loaded */ }
}

// ─── Map list ───

function renderMapList() {
  mapList.innerHTML = "";
  const groups = {};
  for (const m of state.mapinfo.maps) {
    const g = m.group || "Other";
    if (!groups[g]) groups[g] = [];
    groups[g].push(m);
  }
  for (const [group, maps] of Object.entries(groups)) {
    const hdr = document.createElement("div");
    hdr.className = "map-group-header";
    hdr.textContent = group;
    mapList.appendChild(hdr);

    for (const m of maps) {
      const item = document.createElement("div");
      item.className = "map-item" + (state.currentMap === m.file ? " active" : "");
      item.dataset.file = m.file;

      const nameSpan = document.createElement("span");
      nameSpan.className = "map-name";
      nameSpan.textContent = m.name;
      nameSpan.title = m.name;

      const delBtn = document.createElement("button");
      delBtn.className = "map-delete";
      delBtn.textContent = "×";
      delBtn.title = "Delete map";
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteMap(m.file, m.name);
      });

      item.appendChild(nameSpan);
      item.appendChild(delBtn);
      item.addEventListener("click", () => loadMap(m.file));
      item.addEventListener("dblclick", () => renameMap(m.file));
      mapList.appendChild(item);
    }
  }
}

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
    await fetch(`/api/map/${state.currentMap}/data`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.currentData),
    });
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

// MapView stores zone polygons y-up (origin bottom-left), while the SVG overlay,
// the floorplan PNG, and device x/y are y-down (origin top-left). Flip y across
// the map height so zones align with the plan. The flip is its own inverse, so
// applying it on both read (parse) and write (serialize) round-trips exactly.
// If height is unknown (no map loaded), pass coords through unchanged.
function flipY(y) {
  const h = state.currentData && state.currentData.height;
  return h ? h - y : y;
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
        state.mapinfo = data.mapinfo;
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
      state.mapinfo = data.mapinfo;
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
      await fetch("/api/mapinfo", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ maps: state.mapinfo.maps }),
      });
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
    if (!res.ok) throw new Error("Export failed");
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
updateToolInfo();
loadVersionBadge();
rehydrateLabels();
