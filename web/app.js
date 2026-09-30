/* Geox UI logic — vanilla JS, Leaflet map, talks to /api/* */

const $ = (id) => document.getElementById(id);

const state = {
  mode: "fixed",            // fixed | jitter | custom | trip
  target: { lat: 49.2827, lng: -123.1207, place: "Vancouver, Canada" },
  waypoints: [],            // custom draw mode
  trip: null,               // planned itinerary {waypoints, distance_km, ...}
  tripRoutes: [],           // candidate itineraries for trip mode
  selectedRouteIndex: 0,
  tripProfile: "car",
  devices: [],
  selected: null,
  session: null,
  activeTarget: null,       // current active spoof parameters
  pickMode: false,
};

/* ---------------------------------------------------------------- settings */
const DEFAULT_SETTINGS = {
  mapTheme: "esri-dark",
  autoCenter: true,
  units: "metric",
  showHud: true,
  pollInterval: 1000,
  defaultRadius: 120,
  defaultRoamSpeed: 4.5,
  defaultTripFactor: 1.0,
  offlineMode: false,
};

let userSettings = Object.assign({}, DEFAULT_SETTINGS);

function loadSettings() {
  try {
    const raw = localStorage.getItem("geox_settings");
    if (raw) Object.assign(userSettings, JSON.parse(raw));
  } catch (e) { /* ignore */ }
}

function saveSettings() {
  try {
    localStorage.setItem("geox_settings", JSON.stringify(userSettings));
  } catch (e) { /* ignore */ }
}
loadSettings();

/* ------------------------------------------------------------------ map */
const map = L.map("map", { zoomControl: true }).setView([state.target.lat, state.target.lng], 5);

const MAP_THEMES = {
  "esri-dark": {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    options: { attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ", maxNativeZoom: 16, maxZoom: 19 },
  },
  "esri-satellite": {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    options: { attribution: "Tiles &copy; Esri", maxNativeZoom: 18, maxZoom: 19 },
  },
  "esri-streets": {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    options: { attribution: "Tiles &copy; Esri", maxNativeZoom: 18, maxZoom: 19 },
  },
  "esri-topo": {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    options: { attribution: "Tiles &copy; Esri", maxNativeZoom: 18, maxZoom: 19 },
  },
  "esri-light": {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    options: { attribution: "Tiles &copy; Esri", maxNativeZoom: 16, maxZoom: 19 },
  },
  "offline": {
    url: "/api/offline/tiles/{z}/{x}/{y}.jpg",
    options: { attribution: "Offline Tiles &copy; Esri / Geox", maxNativeZoom: 16, maxZoom: 19 },
  },
};

let currentTileLayer = null;
function setMapTheme(themeKey) {
  if (currentTileLayer && map.hasLayer(currentTileLayer)) {
    map.removeLayer(currentTileLayer);
  }
  const theme = MAP_THEMES[themeKey] || MAP_THEMES["esri-dark"];
  currentTileLayer = L.tileLayer(theme.url, theme.options).addTo(map);
  currentTileLayer.bringToBack();
}
setMapTheme(userSettings.offlineMode ? "offline" : userSettings.mapTheme);

const targetIcon = L.divIcon({
  className: "",
  html: `<div style="width:22px;height:22px;border-radius:50%;background:#22c55e;
         border:3px solid #05210f;box-shadow:0 0 0 3px rgba(34,197,94,.35),0 2px 10px #000"></div>`,
  iconSize: [22, 22], iconAnchor: [11, 11],
});
const marker = L.marker([state.target.lat, state.target.lng], {
  draggable: true, icon: targetIcon,
}).addTo(map);

const layers = L.layerGroup().addTo(map);

function redrawOverlays() {
  layers.clearLayers();
  if (state.mode === "jitter") {
    const r = Math.min(Math.max(+$("radiusInput").value || 120, 15), 2000);
    L.circle([state.target.lat, state.target.lng], {
      radius: r, color: "#22c55e", weight: 1, fillOpacity: 0.06, dashArray: "4 6",
    }).addTo(layers);
  }

  if (state.mode === "custom" && state.waypoints.length) {
    L.polyline(state.waypoints, { color: "#22c55e", weight: 3, opacity: 0.85 }).addTo(layers);
    state.waypoints.forEach((p) => {
      L.circleMarker(p, {
        radius: 5, color: "#22c55e", fillColor: "#05210f", fillOpacity: 1, weight: 2,
      }).addTo(layers);
    });
  }

  if (state.mode === "trip" && state.trip && state.trip.waypoints && state.trip.waypoints.length) {
    // 1. Draw alternative candidate routes in muted slate with click-to-select
    if (state.tripRoutes && state.tripRoutes.length > 1) {
      state.tripRoutes.forEach((alt, idx) => {
        if (idx !== state.selectedRouteIndex && alt.waypoints && alt.waypoints.length) {
          const altPoly = L.polyline(alt.waypoints, {
            color: "#64748b",
            weight: 4,
            opacity: 0.55,
            dashArray: "6 8",
          }).addTo(layers);
          altPoly.bindTooltip(`<b>${alt.summary || "Option " + (idx + 1)}</b><br>${alt.distance_km} km · ${alt.duration_min} min<br><span style="color:#22c55e;font-size:11px">Click to select this route</span>`, { sticky: true });
          altPoly.on("click", () => selectRoute(idx));
          altPoly.on("mouseover", () => altPoly.setStyle({ color: "#94a3b8", opacity: 0.9, weight: 5 }));
          altPoly.on("mouseout", () => altPoly.setStyle({ color: "#64748b", opacity: 0.55, weight: 4 }));
        }
      });
    }

    // 2. Draw active selected route in vibrant green
    const wps = state.trip.waypoints;
    const mainPoly = L.polyline(wps, {
      color: "#22c55e",
      weight: 5,
      opacity: 0.9,
    }).addTo(layers);
    mainPoly.bindTooltip(`<b>${state.trip.summary || "Selected Route"}</b><br>${state.trip.distance_km} km · ${state.trip.duration_min} min`, { sticky: true });

    // Start point marker
    L.circleMarker(wps[0], {
      radius: 6, color: "#22c55e", fillColor: "#ffffff", fillOpacity: 1, weight: 3,
    }).bindTooltip("Trip Start", { direction: "top" }).addTo(layers);

    // End point marker
    L.circleMarker(wps[wps.length - 1], {
      radius: 6, color: "#ef4444", fillColor: "#ffffff", fillOpacity: 1, weight: 3,
    }).bindTooltip(state.trip.dest_label ? `Destination: ${state.trip.dest_label}` : "Destination", { direction: "top" }).addTo(layers);
  }
}

let reverseGeocodeTimer = null;
function debouncedReverseGeocode(delay = 350) {
  clearTimeout(reverseGeocodeTimer);
  reverseGeocodeTimer = setTimeout(reverseGeocode, delay);
}

marker.on("drag", (e) => {
  const p = e.target.getLatLng();
  state.target = { lat: p.lat, lng: p.lng, place: "" };
  syncCoordInputs();
  if (typeof updateControlButtons === "function") updateControlButtons();
});
marker.on("dragend", async () => {
  await reverseGeocode();
  if (typeof updateControlButtons === "function") updateControlButtons();
});

map.on("click", (e) => {
  if (state.mode === "custom") {
    state.waypoints.push([e.latlng.lat, e.latlng.lng]);
    renderWaypoints();
  } else if (state.mode === "fixed" || state.mode === "jitter") {
    state.target = { lat: e.latlng.lat, lng: e.latlng.lng, place: "" };
    syncCoordInputs();
    redrawOverlays();
    if (typeof updateControlButtons === "function") updateControlButtons();
    debouncedReverseGeocode();
  }
});

/* ------------------------------------------------------------ utilities */
function toast(msg, kind = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = `show ${kind}`;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), 4200);
}

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function fmtCoord(v) { return (+v).toFixed(5); }

/* ------------------------------------------------------- destination UI */
function syncCoordInputs() {
  $("latInput").value = fmtCoord(state.target.lat);
  $("lngInput").value = fmtCoord(state.target.lng);
  $("placeLabel").textContent = state.target.place || "";
  marker.setLatLng([state.target.lat, state.target.lng]);
}

$("latInput").addEventListener("change", () => {
  const lat = +$("latInput").value;
  if (lat >= -90 && lat <= 90) { state.target.lat = lat; marker.setLatLng([lat, state.target.lng]); }
});
$("lngInput").addEventListener("change", () => {
  const lng = +$("lngInput").value;
  if (lng >= -180 && lng <= 180) { state.target.lng = lng; marker.setLatLng([state.target.lat, lng]); }
});

async function reverseGeocode() {
  try {
    const d = await api(`/api/reverse?lat=${state.target.lat}&lng=${state.target.lng}`);
    if (d.label) { state.target.place = d.label; $("placeLabel").textContent = d.label; }
  } catch { /* offline is fine */ }
}

let searchDebounceTimer = null;

async function doSearch(autoCommit = false) {
  const q = $("searchInput").value.trim();
  if (q.length < 2) {
    $("searchResults").classList.add("hidden");
    return;
  }

  // 1. Direct coordinates parsing: e.g. "48.8566, 2.3522" or "40.7128 -74.0060"
  const coordMatch = q.match(/^(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)$/);
  if (coordMatch) {
    const lat = parseFloat(coordMatch[1]);
    const lng = parseFloat(coordMatch[2]);
    if (lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
      const coordLabel = `Coordinates (${fmtCoord(lat)}, ${fmtCoord(lng)})`;
      if (autoCommit) {
        setTarget(lat, lng, coordLabel);
        $("searchResults").classList.add("hidden");
        toast(`Set destination to ${fmtCoord(lat)}, ${fmtCoord(lng)}`, "ok");
        return;
      }
      $("searchResults").classList.remove("hidden");
      $("searchResults").innerHTML = `<div class="res" data-lat="${lat}" data-lng="${lng}" data-label="${coordLabel}"><b>Coordinates:</b> ${fmtCoord(lat)}, ${fmtCoord(lng)}</div>`;
      $("searchResults").querySelector(".res").addEventListener("click", () => {
        setTarget(lat, lng, coordLabel);
        $("searchResults").classList.add("hidden");
      });
      return;
    }
  }

  // 2. If autoCommit and results are already displayed, select the top one
  if (autoCommit) {
    const firstRes = $("searchResults").querySelector(".res:not(.muted)");
    if (firstRes && firstRes.dataset.lat) {
      setTarget(+firstRes.dataset.lat, +firstRes.dataset.lng, firstRes.dataset.label);
      $("searchResults").classList.add("hidden");
      $("searchInput").value = firstRes.dataset.label.split(",")[0];
      toast(`Navigated to ${firstRes.dataset.label.split(",")[0]}`, "ok");
      return;
    }
  }

  $("searchResults").classList.remove("hidden");
  $("searchResults").innerHTML = `<div class="res muted">Searching…</div>`;

  try {
    const d = await api("/api/geocode", { q });
    if (!d.results || !d.results.length) {
      $("searchResults").innerHTML = `<div class="res muted">No locations found</div>`;
      return;
    }

    if (autoCommit) {
      const top = d.results[0];
      setTarget(top.lat, top.lng, top.label);
      $("searchResults").classList.add("hidden");
      $("searchInput").value = top.label.split(",")[0];
      toast(`Navigated to ${top.label.split(",")[0]}`, "ok");
      return;
    }

    $("searchResults").innerHTML = d.results
      .map((r, i) => `<div class="res" data-i="${i}" data-lat="${r.lat}" data-lng="${r.lng}" data-label="${r.label.replace(/"/g, '&quot;')}">${r.label}</div>`).join("");

    $("searchResults").querySelectorAll(".res").forEach((el) => {
      el.addEventListener("click", () => {
        const lat = +el.dataset.lat;
        const lng = +el.dataset.lng;
        const label = el.dataset.label;
        setTarget(lat, lng, label);
        $("searchResults").classList.add("hidden");
        $("searchInput").value = label.split(",")[0];
      });
    });
  } catch (e) {
    $("searchResults").innerHTML = `<div class="res muted">${e.message}</div>`;
  }
}

// Live suggestions as you type (starting at 2 chars with snappy 200ms debounce)
$("searchInput").addEventListener("input", () => {
  clearTimeout(searchDebounceTimer);
  const q = $("searchInput").value.trim();
  if (q.length >= 2) {
    searchDebounceTimer = setTimeout(() => doSearch(false), 200);
  } else {
    $("searchResults").classList.add("hidden");
  }
});

// "Go" button & Enter key immediately commits search / jumps to destination
$("searchBtn").addEventListener("click", () => doSearch(true));
$("searchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    doSearch(true);
  }
});

// Dismiss dropdown when clicking outside
document.addEventListener("click", (e) => {
  if (!$("searchInput").contains(e.target) && !$("searchResults").contains(e.target) && !$("searchBtn").contains(e.target)) {
    $("searchResults").classList.add("hidden");
  }
  const trRes = $("tripSearchResults");
  if (trRes && $("tripDestInput") && !$("tripDestInput").contains(e.target) && !trRes.contains(e.target)) {
    trRes.classList.add("hidden");
  }
});

let tripSearchDebounceTimer = null;
async function doTripDestSearch() {
  const q = $("tripDestInput").value.trim();
  const resEl = $("tripSearchResults");
  if (!resEl) return;
  if (q.length < 2) {
    resEl.classList.add("hidden");
    return;
  }
  resEl.classList.remove("hidden");
  resEl.innerHTML = `<div class="res muted">Searching…</div>`;

  try {
    const d = await api("/api/geocode", { q });
    if (!d.results || !d.results.length) {
      resEl.innerHTML = `<div class="res muted">No places found</div>`;
      return;
    }
    resEl.innerHTML = d.results
      .map((r) => `<div class="res" data-lat="${r.lat}" data-lng="${r.lng}" data-label="${r.label.replace(/"/g, '&quot;')}">${r.label}</div>`)
      .join("");

    resEl.querySelectorAll(".res").forEach((el) => {
      el.addEventListener("click", () => {
        $("tripDestInput").value = el.dataset.label.split(",")[0];
        resEl.classList.add("hidden");
        planTrip();
      });
    });
  } catch (e) {
    resEl.innerHTML = `<div class="res muted">${e.message}</div>`;
  }
}

if ($("tripDestInput")) {
  $("tripDestInput").addEventListener("input", () => {
    clearTimeout(tripSearchDebounceTimer);
    const q = $("tripDestInput").value.trim();
    if (q.length >= 2) {
      tripSearchDebounceTimer = setTimeout(doTripDestSearch, 200);
    } else if ($("tripSearchResults")) {
      $("tripSearchResults").classList.add("hidden");
    }
  });

  $("tripDestInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if ($("tripSearchResults")) $("tripSearchResults").classList.add("hidden");
      planTrip();
    }
  });
}

const PRESETS = [
  ["McMurdo, Antarctica", -77.8419, 166.6863],
  ["South Pole Station", -89.9975, 0.0],
  ["Vancouver", 49.2827, -123.1207],
  ["New York", 40.7128, -74.006],
  ["Paris", 48.8566, 2.3522],
  ["Tokyo", 35.6762, 139.6503],
  ["London", 51.5072, -0.1276],
  ["Dubai", 25.2048, 55.2708],
  ["Sydney", -33.8688, 151.2093],
  ["Honolulu", 21.3069, -157.8583],
  ["Las Vegas", 36.1699, -115.1398],
];
const presetSel = $("presetSelect");
if (presetSel) {
  for (const [label, lat, lng] of PRESETS) {
    const opt = document.createElement("option");
    opt.value = `${lat}|${lng}|${label}`;
    opt.textContent = label;
    presetSel.appendChild(opt);
  }
  presetSel.addEventListener("change", () => {
    const val = presetSel.value;
    if (!val) return;
    const [lat, lng, label] = val.split("|");
    setTarget(+lat, +lng, label);
    presetSel.selectedIndex = 0;
  });
} else if ($("presets")) {
  for (const [label, lat, lng] of PRESETS) {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = label;
    b.addEventListener("click", () => setTarget(lat, lng, label.replace(/^\S+\s/, "")));
    $("presets").appendChild(b);
  }
}

function setTarget(lat, lng, place) {
  state.target = { lat, lng, place: place || "" };
  syncCoordInputs();
  map.setView([lat, lng], Math.max(map.getZoom(), 10));
  redrawOverlays();
  if (place) $("placeLabel").textContent = place;
  if (typeof updateControlButtons === "function") updateControlButtons();
}

/* ----------------------------------------------------------------- quick copy */
const copyCoordsBtn = $("copyCoordsBtn");
if (copyCoordsBtn) {
  copyCoordsBtn.addEventListener("click", async () => {
    const text = `${fmtCoord(state.target.lat)}, ${fmtCoord(state.target.lng)}`;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const inp = document.createElement("textarea");
        inp.value = text;
        document.body.appendChild(inp);
        inp.select();
        document.execCommand("copy");
        document.body.removeChild(inp);
      }
      toast(`Copied: ${text}`, "ok");
    } catch {
      toast(`Coordinates: ${text}`);
    }
  });
}

/* ------------------------------------------------------------- mode tabs */
function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll("#modeChips .chip, #modeChips .seg-btn").forEach((c) =>
    c.classList.toggle("on", c.dataset.mode === mode));
  $("roamOpts").classList.toggle("hidden", mode !== "jitter");
  $("customOpts").classList.toggle("hidden", mode !== "custom");
  $("tripOpts").classList.toggle("hidden", mode !== "trip");
  // in Trip mode the marker is where the phone really is, not where it fakes being
  $("destHeadingText").textContent = mode === "trip" ? "Starting point" : "Destination";
  $("liveLocBtn").classList.toggle("hidden", mode !== "trip");
  if (mode !== "trip") {
    removeTripTrackingMarker();
  }
  redrawOverlays();
  if (typeof updateControlButtons === "function") updateControlButtons();
}
document.querySelectorAll("#modeChips .chip, #modeChips .seg-btn").forEach((c) =>
  c.addEventListener("click", () => setMode(c.dataset.mode)));

$("radiusInput").addEventListener("input", () => {
  redrawOverlays();
  if (typeof updateControlButtons === "function") updateControlButtons();
});
$("radiusInput").addEventListener("change", () => {
  redrawOverlays();
  if (typeof updateControlButtons === "function") updateControlButtons();
});
$("roamSpeedInput").addEventListener("input", () => {
  if (typeof updateControlButtons === "function") updateControlButtons();
});
$("roamSpeedInput").addEventListener("change", () => {
  if (typeof updateControlButtons === "function") updateControlButtons();
});

/* --------------------------------------------------------- custom route */
function renderWaypoints() {
  const el = $("wpList");
  el.innerHTML = state.waypoints
    .map((p, i) => `<div class="wp"><span><b>${i + 1}.</b> ${fmtCoord(p[0])}, ${fmtCoord(p[1])}</span>
      <button data-i="${i}" title="remove">✕</button></div>`).join("");
  el.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      state.waypoints.splice(+b.dataset.i, 1);
      renderWaypoints();
    }));
  redrawOverlays();
  if (typeof updateControlButtons === "function") updateControlButtons();
}
$("customSpeedInput").addEventListener("input", () => {
  if (typeof updateControlButtons === "function") updateControlButtons();
});
$("customLoop").addEventListener("change", () => {
  if (typeof updateControlButtons === "function") updateControlButtons();
});

const clearWpsBtn = $("clearWpsBtn");
if (clearWpsBtn) {
  clearWpsBtn.addEventListener("click", () => {
    state.waypoints = [];
    renderWaypoints();
    toast("Waypoints cleared.", "ok");
  });
}

/* ----------------------------------------------- trip live tracking marker */
let tripTrackingMarker = null;

function updateTripTrackingMarker(lat, lng) {
  if (!tripTrackingMarker) {
    const icon = L.divIcon({
      className: "",
      html: `<div class="traj-vehicle-dot"><div class="traj-nav-puck"></div></div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
    tripTrackingMarker = L.marker([lat, lng], { icon, zIndexOffset: 3000 });
  }
  if (!map.hasLayer(tripTrackingMarker)) {
    tripTrackingMarker.addTo(map);
  }
  tripTrackingMarker.setLatLng([lat, lng]);
  tripTrackingMarker.bindTooltip(
    `<b>Live location</b><br>${fmtCoord(lat)}, ${fmtCoord(lng)}`,
    { direction: "top", offset: [0, -8] }
  );
  if (userSettings.autoCenter) {
    map.panTo([lat, lng], { animate: true, duration: 0.6 });
  }
}

function removeTripTrackingMarker() {
  if (tripTrackingMarker && map.hasLayer(tripTrackingMarker)) {
    map.removeLayer(tripTrackingMarker);
  }
}

/* ----------------------------------------------------------------- trip */
document.querySelectorAll("#tripProfiles .chip, #tripProfiles .seg-btn").forEach((c) =>
  c.addEventListener("click", () => {
    state.tripProfile = c.dataset.profile;
    document.querySelectorAll("#tripProfiles .chip, #tripProfiles .seg-btn").forEach((x) =>
      x.classList.toggle("on", x === c));
  }));

$("tripPlanBtn").addEventListener("click", planTrip);
$("tripDestInput").addEventListener("keydown", (e) => e.key === "Enter" && planTrip());
$("tripFactorInput").addEventListener("input", () => {
  updateTripEta();
  if (typeof updateControlButtons === "function") updateControlButtons();
});
$("tripFactorInput").addEventListener("change", () => {
  updateTripEta();
  if (typeof updateControlButtons === "function") updateControlButtons();
});
const durationSel = $("durationSelect");
if (durationSel) {
  durationSel.addEventListener("change", () => {
    if (typeof updateControlButtons === "function") updateControlButtons();
  });
}

function selectRoute(idx) {
  if (!state.tripRoutes || !state.tripRoutes[idx]) return;
  state.selectedRouteIndex = idx;
  state.trip = state.tripRoutes[idx];
  renderTripRoutes();
  redrawOverlays();
  updateTripEta();
  if (typeof updateControlButtons === "function") updateControlButtons();
}

function renderTripRoutes() {
  const el = $("tripRoutesList");
  if (!state.tripRoutes || state.tripRoutes.length <= 1) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden");
  el.innerHTML = state.tripRoutes.map((rt, i) => {
    const isSel = i === state.selectedRouteIndex;
    const badgeText = rt.is_fastest ? "Fastest" : `+${Math.max(1, rt.duration_min - state.tripRoutes[0].duration_min)}m`;
    const shortVia = rt.summary ? rt.summary.replace(/^via\s+/, "") : `Route ${i + 1}`;
    return `<button class="chip ${isSel ? 'on' : ''}" data-idx="${i}" title="${rt.summary || ''} (${rt.distance_km} km, ${rt.duration_min} min)">
      ${isSel ? '✓ ' : ''}${shortVia} · ${rt.duration_min}m (${badgeText})
    </button>`;
  }).join("");

  el.querySelectorAll(".chip").forEach((card) => {
    card.addEventListener("click", () => {
      selectRoute(+card.dataset.idx);
    });
  });
}

function updateTripEta() {
  if (!state.trip) return;
  const f = Math.min(Math.max(+$("tripFactorInput").value || 1, 0.1), 20);
  const mins = Math.max(1, Math.round(state.trip.duration_min / f));
  const isImp = userSettings.units === "imperial";
  const distVal = isImp ? (state.trip.distance_km * 0.621371).toFixed(1) : state.trip.distance_km;
  const distUnit = isImp ? "mi" : "km";
  const speedAvg = isImp ? Math.round(state.trip.speed_kmh * f * 0.621371) : Math.round(state.trip.speed_kmh * f);
  const speedUnit = isImp ? "mph" : "km/h";
  $("tripEta").value = `~${mins >= 60 ? Math.floor(mins / 60) + "h " : ""}${mins % 60}m (${distVal} ${distUnit})`;
  if (!$("tripSummary").classList.contains("hidden")) {
    const label = mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins} min`;
    const viaText = state.trip.summary ? `<b>${state.trip.summary}</b> · ` : "";
    $("tripSummary").innerHTML =
      `${viaText}<b>${distVal} ${distUnit}</b> · <b>${label}</b> (${speedAvg} ${speedUnit} avg)<br>` +
      `<span class="muted small">${state.trip.dest_label || ""}</span>`;
  }
}

async function planTrip() {
  const dest = $("tripDestInput").value.trim();
  const gmaps = $("gmapsInput").value.trim();
  if (!dest && !gmaps) { toast("Type a destination or paste a Google Maps link.", "error"); return; }
  const body = {
    profile: state.tripProfile,
    to: dest ? { name: dest } : null,
    gmaps_url: gmaps || null,
    start: { lat: state.target.lat, lng: state.target.lng },
  };
  $("tripSummary").classList.remove("hidden");
  $("tripSummary").innerHTML = "Planning route…";
  try {
    const trip = await api("/api/route", body);
    state.tripRoutes = trip.routes && trip.routes.length ? trip.routes : [trip];
    state.selectedRouteIndex = 0;
    state.trip = state.tripRoutes[0];
    renderTripRoutes();
    setMode("trip");
    redrawOverlays();
    updateTripEta();

    // Collect all waypoints across alternative routes to fit map view
    const allWps = [];
    state.tripRoutes.forEach((r) => { if (r.waypoints) allWps.push(...r.waypoints); });
    if (allWps.length) {
      map.fitBounds(L.polyline(allWps).getBounds(), { padding: [40, 40] });
    }

    toast(state.tripRoutes.length > 1
      ? `Found ${state.tripRoutes.length} route options — pick one on the list or map.`
      : "Itinerary planned — press START SPOOFING or Auto Swap.", "ok");
    if (typeof updateControlButtons === "function") updateControlButtons();
  } catch (e) {
    state.trip = null;
    state.tripRoutes = [];
    renderTripRoutes();
    $("tripSummary").innerHTML = `<span style="color:#ef4444">${e.message}</span>`;
  }
}

/* -------------------------------------------------------------- devices */
function renderCaps(caps) {
  const pills = [];
  pills.push(caps.apple_service
    ? `<span class="pill ok">Apple drivers OK</span>`
    : `<span class="pill bad" title="Install iTunes or the Apple Devices app">Apple drivers missing</span>`);
  pills.push(caps.adb
    ? `<span class="pill ok">ADB ready</span>`
    : `<span class="pill bad">ADB missing</span>`);
  $("capPills").innerHTML = pills.join("");
  $("installAdbBtn").classList.toggle("hidden", !!caps.adb || caps.adb_install_running);
  if (caps.adb_install_running) $("installAdbBtn").textContent = "Downloading…";
}

function deviceBadges(d) {
  const b = [];
  if (d.platform === "ios") {
    b.push(`<span class="badge">${d.os_version ? "iOS " + d.os_version : "iOS"}</span>`);
    b.push(d.paired
      ? `<span class="badge ok">paired</span>`
      : `<span class="badge warn">needs trust</span>`);
    if (d.developer_mode === true) b.push(`<span class="badge ok">dev mode</span>`);
    if (d.developer_mode === false) b.push(`<span class="badge err">dev mode OFF</span>`);
    if (d.tunnel_mode) b.push(`<span class="badge">tunnel mode</span>`);
  } else {
    b.push(`<span class="badge">Android ${d.os_version || ""}</span>`);
    if (d.adb_status !== "device") b.push(`<span class="badge err">${d.adb_status}</span>`);
    else {
      const br = d.bridge || {};
      b.push(br.installed && br.mock_allowed
        ? `<span class="badge ok">bridge ready</span>`
        : `<span class="badge warn">needs bridge setup</span>`);
    }
  }
  if (d.active) b.push(`<span class="badge ok">SPOOFING</span>`);
  return b.join("");
}

function renderDevices() {
  const el = $("deviceList");
  if (!state.devices.length) {
    el.innerHTML = `<div class="empty">No phones detected. Plug one in with USB, unlock it,
      accept any trust/USB-debugging prompts, then hit Refresh.</div>`;
    return;
  }
  el.innerHTML = state.devices.map((d, i) => `
    <div class="dev ${state.selected === d.id ? "sel" : ""}" data-i="${i}">
      <div class="dtop">
        <span class="dname">${d.name || d.id}</span>
        <span class="spacer"></span>
        <span class="muted small">${d.platform === "ios" ? "iPhone" : "Android"}</span>
      </div>
      <div class="dbadges">${deviceBadges(d)}</div>
      ${d.notes && d.notes.length && d.notes[0] !== "Ready"
      ? `<div class="muted small" style="margin-top:5px">${d.notes.join(" · ")}</div>` : ""}
      ${d.platform === "android" && d.adb_status === "device" &&
      (!d.bridge || !d.bridge.installed || !d.bridge.mock_allowed)
      ? `<div class="row"><button class="btn small" data-setup="${d.id}">Setup bridge</button></div>` : ""}
    </div>`).join("");
  el.querySelectorAll(".dev").forEach((el) =>
    el.addEventListener("click", () => {
      state.selected = state.devices[+el.dataset.i].id;
      renderDevices();
    }));
  el.querySelectorAll("[data-setup]").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await api("/api/android/setup-bridge", { device_id: b.dataset.setup });
        toast("Bridge installed & mock-location granted.", "ok");
        refresh(true);
      } catch (err) { toast(err.message, "error"); }
    }));
}

/* -------------------------------------------------------------- session */
function renderSession(s) {
  const el = $("sessionCard");
  if (!s || s.state === "stopped") { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  const err = s.state === "failed";
  el.classList.toggle("error", err);
  if (err) {
    el.innerHTML = `<b style="color:#ef4444">Failed</b><br>${s.error || "unknown error"}` +
      (s.error && /developer mode/i.test(s.error)
        ? `<div class="row"><button id="devModeBtn" class="btn small">Enable Developer Mode (reboots iPhone)</button></div>`
        : "");
    const btn = el.querySelector("#devModeBtn");
    if (btn) btn.addEventListener("click", enableDevMode);
    return;
  }
  const modeName = { fixed: "stay put", jitter: "roaming", custom: "drawn route", route: "itinerary" }[s.mode] || s.mode;
  let hudHtml = "";
  if (s.mode === "route" && s.telemetry && userSettings.showHud !== false) {
    const t = s.telemetry;
    const isImp = userSettings.units === "imperial";
    const speedVal = isImp ? Math.round(t.speed_kmh * 0.621371) : t.speed_kmh;
    const speedUnit = isImp ? "mph" : "km/h";
    const speedStr = t.completed ? "Arrived" : `${speedVal} ${speedUnit}`;
    let remStr = "";
    if (t.completed) {
      remStr = "Holding destination";
    } else if (t.remaining_s != null) {
      const m = Math.ceil(t.remaining_s / 60);
      remStr = m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m remaining` : `${m} min remaining`;
    }
    const pct = Math.min(100, Math.max(0, Math.round(t.progress)));
    hudHtml = `
      <div class="trip-hud">
        <div class="hud-row">
          <span class="hud-title">TRIP TELEMETRY</span>
          <span class="hud-val">${t.completed ? "100%" : pct + "%"}</span>
        </div>
        <div class="hud-progress-bg">
          <div class="hud-progress-fill" style="width: ${pct}%;"></div>
        </div>
        <div class="hud-meta">
          <span>${speedStr}</span>
          <span>${remStr}</span>
        </div>
      </div>
    `;
  }
  el.innerHTML = `<span class="live"></span><b>Spoofing ${s.device_name}</b> — ${modeName}<br>
    ${s.place ? s.place + "<br>" : ""}now at ${fmtCoord(s.last[0])}, ${fmtCoord(s.last[1])}
    ${s.engine === "dvt-tunnel-cli" ? "<br><span class='muted small'>iOS 17+ tunnel session</span>" : ""}
    ${hudHtml}`;
}

async function enableDevMode(ev) {
  const b = ev.target;
  b.disabled = true;
  const original = b.textContent;
  b.textContent = "Asking the iPhone…";
  try {
    const d = await api("/api/ios/enable-devmode", {});
    if (d.manual) {
      toast(d.note, "ok");
      b.textContent = "Check the iPhone's Settings";
    } else {
      toast("Developer Mode enabled — the iPhone is rebooting. Unlock it when it's back, then press START again.", "ok");
      b.textContent = "iPhone is rebooting…";
    }
  } catch (e) {
    toast(e.message, "error");
    b.textContent = original;
  } finally {
    b.disabled = false;
    if (b.textContent !== original) setTimeout(() => { b.textContent = original; }, 15000);
  }
}

function hasTargetChanged() {
  if (!state.session || state.session.state !== "active" || !state.activeTarget) {
    return false;
  }
  const at = state.activeTarget;
  if (state.mode !== at.mode) return true;

  const curDur = $("durationSelect") ? $("durationSelect").value : "auto";
  if (curDur !== (at.duration_select || "auto")) return true;

  if (state.mode === "fixed" || state.mode === "jitter") {
    const dLat = Math.abs((state.target.lat || 0) - (at.lat || 0));
    const dLng = Math.abs((state.target.lng || 0) - (at.lng || 0));
    if (dLat > 0.0001 || dLng > 0.0001) return true;
    if (state.mode === "jitter") {
      const curR = +$("radiusInput").value || 120;
      const curS = +$("roamSpeedInput").value || 4.5;
      if (curR !== at.radius_m || curS !== at.speed_kmh) return true;
    }
    return false;
  }

  if (state.mode === "custom") {
    const curSpeed = +$("customSpeedInput").value || 20;
    const curLoop = $("customLoop").value === "true";
    if (curSpeed !== (at.speed_kmh || 20) || curLoop !== !!at.loop) return true;

    const curWps = state.waypoints || [];
    const prevWps = at.waypoints || [];
    if (curWps.length !== prevWps.length) return curWps.length >= 2;
    for (let i = 0; i < curWps.length; i++) {
      if (Math.abs(curWps[i][0] - prevWps[i][0]) > 0.0001 || Math.abs(curWps[i][1] - prevWps[i][1]) > 0.0001) {
        return true;
      }
    }
    return false;
  }

  if (state.mode === "trip") {
    if (!state.trip) return false;
    if (!at.trip) return true;
    const curDest = state.trip.dest_label || "";
    const prevDest = at.trip.dest_label || "";
    if (curDest !== prevDest) return true;

    if ((state.trip.summary || "") !== (at.trip.summary || "")) return true;
    if (Math.abs((state.trip.distance_km || 0) - (at.trip.distance_km || 0)) > 0.05) return true;
    if (Math.abs((state.trip.duration_min || 0) - (at.trip.duration_min || 0)) > 0.2) return true;

    const curFactor = Math.min(Math.max(+$("tripFactorInput").value || 1, 0.1), 20);
    if (Math.abs(curFactor - (at.speed_factor || 1)) > 0.05) return true;

    const curWps = state.trip.waypoints || [];
    const prevWps = at.trip.waypoints || [];
    if (curWps.length !== prevWps.length) return true;
    if (curWps.length > 0 && prevWps.length > 0) {
      const mid = Math.floor(curWps.length / 2);
      if (Math.abs(curWps[0][0] - prevWps[0][0]) > 0.0001 || Math.abs(curWps[0][1] - prevWps[0][1]) > 0.0001) return true;
      if (Math.abs(curWps[mid][0] - prevWps[mid][0]) > 0.0001 || Math.abs(curWps[mid][1] - prevWps[mid][1]) > 0.0001) return true;
      if (Math.abs(curWps[curWps.length - 1][0] - prevWps[prevWps.length - 1][0]) > 0.0001 || Math.abs(curWps[curWps.length - 1][1] - prevWps[prevWps.length - 1][1]) > 0.0001) return true;
    }
    return false;
  }

  return false;
}

function updateControlButtons() {
  const s = state.session;
  const isActive = !!s && s.state !== "stopped" && s.state !== "failed";
  $("startBtn").classList.toggle("hidden", isActive);
  const activeControls = $("activeControls");
  if (activeControls) activeControls.classList.toggle("hidden", !isActive);

  const autoSwapBtn = $("autoSwapBtn");
  if (autoSwapBtn) {
    const showSwap = isActive && hasTargetChanged();
    autoSwapBtn.classList.toggle("hidden", !showSwap);
  }
}

/* --------------------------------------------------------------- status */
let lastLogLen = 0;
async function poll() {
  try {
    const st = await api("/api/status");
    state.devices = st.devices;
    renderCaps(st.capabilities);
    renderDevices();
    const selDev = st.devices.find((x) => x.id === state.selected);
    $("devModeBtn").classList.toggle("hidden", !(selDev && selDev.platform === "ios"));
    const s = state.selected ? st.sessions.find((x) => x.device_id === state.selected) : st.sessions[0];
    state.session = s || null;

    if (s && s.state === "active" && !state.activeTarget && s.last) {
      state.activeTarget = {
        mode: s.mode || "fixed",
        lat: s.last[0],
        lng: s.last[1],
        place: s.place || "",
        duration_select: $("durationSelect") ? $("durationSelect").value : "auto",
        speed_factor: Math.min(Math.max(+$("tripFactorInput").value || 1, 0.1), 20),
      };
      // page reloaded mid-spoof: sync the target to the running spoof so the
      // AutoSwap button doesn't offer a stale default location instead
      state.target = { lat: s.last[0], lng: s.last[1], place: s.place || "" };
      syncCoordInputs();
    } else if (!s || s.state === "stopped" || s.state === "failed") {
      state.activeTarget = null;
    }

    // ONLY show live tracking marker when in Trip mode
    const isTripActive = s && s.state === "active" && state.mode === "trip" && s.last && s.last.length >= 2;
    if (isTripActive) {
      updateTripTrackingMarker(s.last[0], s.last[1]);
    } else {
      removeTripTrackingMarker();
    }

    updateControlButtons();
    renderSession(s);

    if (st.logs.length !== lastLogLen) {
      lastLogLen = st.logs.length;
      const log = $("log");
      log.innerHTML = st.logs
        .map((l) => `<div class="${l.level}">${new Date(l.t * 1000).toLocaleTimeString()} ${l.msg}</div>`)
        .join("");
      log.scrollTop = log.scrollHeight;
    }
  } catch { /* server restarting */ }
}

function refresh(force) {
  lastLogLen = 0;   // force log repaint
  poll();
}

/* ------------------------------------------------------------- controls */
$("liveLocBtn").addEventListener("click", () => {
  if (!navigator.geolocation) {
    toast("This browser does not support geolocation.", "error");
    return;
  }
  const b = $("liveLocBtn");
  b.disabled = true;
  b.textContent = "Locating...";
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude, accuracy } = pos.coords;
    setTarget(latitude, longitude, "");
    b.disabled = false;
    b.textContent = "Use my live location";
    toast(`Live location found (accuracy of about ${Math.round(accuracy)} m).`, "ok");
    reverseGeocode();
  }, (err) => {
    b.disabled = false;
    b.textContent = "Use my live location";
    toast("Could not get the live location: " + err.message + " Allow location access for this page.", "error");
  }, { enableHighAccuracy: true, timeout: 15000 });
});

$("refreshBtn").addEventListener("click", () => refresh(true));
$("devModeBtn").addEventListener("click", enableDevMode);
$("installAdbBtn").addEventListener("click", async () => {
  try {
    await api("/api/android/install-adb", {});
    toast("Downloading Google platform-tools…");
    $("installAdbBtn").textContent = "Downloading…";
  } catch (e) { toast(e.message, "error"); }
});

function buildPayload() {
  const devId = state.selected || (state.session && state.session.device_id);
  if (!devId) throw new Error("Select a device first (step 1).");
  const body = { device_id: devId, place: state.target.place };
  const durSelect = $("durationSelect");
  if (durSelect && durSelect.value !== "auto") {
    const hours = parseFloat(durSelect.value);
    if (!isNaN(hours) && hours > 0) {
      body.playback_hours = hours;
    }
  }
  if (state.mode === "fixed") {
    Object.assign(body, { mode: "fixed", lat: state.target.lat, lng: state.target.lng });
  } else if (state.mode === "jitter") {
    Object.assign(body, {
      mode: "jitter", lat: state.target.lat, lng: state.target.lng,
      radius_m: +$("radiusInput").value, speed_kmh: +$("roamSpeedInput").value,
    });
  } else if (state.mode === "custom") {
    if (state.waypoints.length < 2) throw new Error("Click the map to add at least 2 waypoints.");
    Object.assign(body, {
      mode: "route", waypoints: state.waypoints,
      speed_kmh: +$("customSpeedInput").value, loop: $("customLoop").value === "true",
      place: "Drawn route",
    });
  } else if (state.mode === "trip") {
    if (!state.trip) throw new Error("Plan an itinerary first (Trip → Plan).");
    Object.assign(body, {
      mode: "route", waypoints: state.trip.waypoints,
      seg_seconds: state.trip.seg_seconds,
      speed_factor: Math.min(Math.max(+$("tripFactorInput").value || 1, 0.1), 20),
      loop: false,
      place: state.trip.dest_label,
    });
  }
  return body;
}

$("startBtn").addEventListener("click", async () => {
  try {
    const body = buildPayload();
    await api("/api/start", body);
    state.activeTarget = {
      mode: body.mode,
      lat: body.lat,
      lng: body.lng,
      place: body.place,
      radius_m: body.radius_m,
      speed_kmh: body.speed_kmh,
      speed_factor: body.speed_factor,
      duration_select: $("durationSelect") ? $("durationSelect").value : "auto",
      loop: body.loop,
      waypoints: body.waypoints ? JSON.parse(JSON.stringify(body.waypoints)) : null,
      trip: state.trip ? JSON.parse(JSON.stringify(state.trip)) : null,
    };
    toast("Spoofing started.", "ok");
    updateControlButtons();
    poll();
  } catch (e) { toast(e.message, "error"); }
});

const autoSwapBtn = $("autoSwapBtn");
if (autoSwapBtn) {
  autoSwapBtn.addEventListener("click", async () => {
    try {
      const body = buildPayload();
      await api("/api/swap", body);
      state.activeTarget = {
        mode: body.mode,
        lat: body.lat,
        lng: body.lng,
        place: body.place,
        radius_m: body.radius_m,
        speed_kmh: body.speed_kmh,
        speed_factor: body.speed_factor,
        duration_select: $("durationSelect") ? $("durationSelect").value : "auto",
        loop: body.loop,
        waypoints: body.waypoints ? JSON.parse(JSON.stringify(body.waypoints)) : null,
        trip: state.trip ? JSON.parse(JSON.stringify(state.trip)) : null,
      };
      toast("Location swapped seamlessly without delay.", "ok");
      updateControlButtons();
      poll();
    } catch (e) { toast(e.message, "error"); }
  });
}

$("stopBtn").addEventListener("click", async () => {
  try {
    removeTripTrackingMarker();
    await api("/api/stop", { device_id: state.selected || (state.session && state.session.device_id) });
    state.activeTarget = null;
    toast("Stopped — real GPS restored.", "ok");
    updateControlButtons();
    poll();
  } catch (e) { toast(e.message, "error"); }
});

/* ---------------------------------------------------------------- log card */
const logToggle = $("logToggle");
const logWrapper = $("logWrapper");
const logChevron = $("logChevron");
if (logToggle && logWrapper) {
  logToggle.addEventListener("click", () => {
    const isHidden = logWrapper.classList.toggle("hidden");
    if (logChevron) {
      logChevron.textContent = isHidden ? "▶" : "▼";
    }
  });
}

/* ------------------------------------------------------------- settings UI */
function initSettingsUI() {
  const modal = $("settingsModal");
  const btn = $("settingsBtn");
  const closeBtn = $("closeSettingsBtn");
  const saveBtn = $("saveSettingsBtn");
  const resetBtn = $("resetSettingsBtn");

  if (!modal || !btn) return;

  function syncSettingsInputs() {
    if ($("settingMapTheme")) $("settingMapTheme").value = userSettings.mapTheme;
    if ($("settingAutoCenter")) $("settingAutoCenter").checked = !!userSettings.autoCenter;
    if ($("settingShowHud")) $("settingShowHud").checked = !!userSettings.showHud;
    if ($("settingDefaultRadius")) $("settingDefaultRadius").value = userSettings.defaultRadius;
    if ($("settingDefaultRoamSpeed")) $("settingDefaultRoamSpeed").value = userSettings.defaultRoamSpeed;
    if ($("settingDefaultTripFactor")) $("settingDefaultTripFactor").value = userSettings.defaultTripFactor;
    if ($("settingOfflineMode")) $("settingOfflineMode").checked = !!userSettings.offlineMode;

    document.querySelectorAll("#settingUnitsControl .seg-btn").forEach((b) => {
      b.classList.toggle("on", b.dataset.val === userSettings.units);
    });
    document.querySelectorAll("#settingPollInterval .seg-btn").forEach((b) => {
      b.classList.toggle("on", +b.dataset.val === userSettings.pollInterval);
    });
  }

  function openSettings() {
    syncSettingsInputs();
    modal.classList.remove("hidden");
    const activeTab = document.querySelector("#settingsTabButtons .settings-tab-btn.on");
    if (activeTab && activeTab.dataset.target === "tabOffline") {
      refreshOfflineStats();
      updateDownloadEstimate();
    }
  }

  function closeSettings() {
    modal.classList.add("hidden");
    saveSettings();
  }

  btn.addEventListener("click", openSettings);
  if (closeBtn) closeBtn.addEventListener("click", closeSettings);
  if (saveBtn) saveBtn.addEventListener("click", closeSettings);

  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeSettings();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeSettings();
    }
  });

  // Settings tabs
  document.querySelectorAll("#settingsTabButtons .settings-tab-btn").forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      document.querySelectorAll("#settingsTabButtons .settings-tab-btn").forEach((b) => b.classList.remove("on"));
      tabBtn.classList.add("on");
      const targetId = tabBtn.dataset.target;
      document.querySelectorAll(".tab-content").forEach((tc) => {
        tc.classList.toggle("hidden", tc.id !== targetId);
      });
      if (targetId === "tabOffline") {
        refreshOfflineStats();
        updateDownloadEstimate();
      }
    });
  });

  // Offline country/region state
  let selectedCountry = { name: "United States", bounds: [24.3963, -125.0, 49.3844, -66.9346] };
  let countrySearchDebounce = null;

  async function updateDownloadEstimate() {
    const weightEl = $("offlineWeight");
    const regionEl = $("offlineRegion");
    if (!weightEl || !regionEl) return;

    const weight = weightEl.value || "moderate";
    const region = regionEl.value || "world";

    const countryWrap = $("countrySearchContainer");
    if (countryWrap) {
      countryWrap.classList.toggle("hidden", region !== "country");
    }

    let bounds = null;
    if (region === "viewport") {
      const b = map.getBounds();
      bounds = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()];
    } else if (region === "country" && selectedCountry) {
      bounds = selectedCountry.bounds;
    }

    try {
      const res = await api("/api/offline/estimate", {
        region_type: region,
        weight: weight,
        country: (region === "country" && selectedCountry) ? selectedCountry.name : null,
        bounds: bounds,
      });

      if ($("estSizeVal")) $("estSizeVal").textContent = `~${res.size_formatted}`;
      if ($("estTilesVal")) $("estTilesVal").textContent = res.tile_count_formatted;
      if ($("estDiskVal")) $("estDiskVal").textContent = `${res.disk_free_formatted} free`;
      if ($("estDescVal")) $("estDescVal").textContent = res.description;

      const badge = $("offlineEstimateBadge");
      if (badge) {
        if (res.has_space) {
          badge.textContent = "Ready to download";
          badge.classList.remove("warn");
        } else {
          badge.textContent = "Low disk space";
          badge.classList.add("warn");
        }
      }
    } catch {
      // Non-blocking estimate failure
    }
  }

  // Country search handling
  if ($("countrySearchInput")) {
    $("countrySearchInput").addEventListener("input", () => {
      clearTimeout(countrySearchDebounce);
      const q = $("countrySearchInput").value.trim();
      const resEl = $("countrySearchResults");
      if (!resEl) return;
      if (q.length < 1) {
        resEl.classList.add("hidden");
        return;
      }
      countrySearchDebounce = setTimeout(async () => {
        try {
          const data = await api(`/api/offline/regions?q=${encodeURIComponent(q)}`);
          if (!data.results || !data.results.length) {
            resEl.innerHTML = `<div class="res muted">No countries found</div>`;
          } else {
            resEl.innerHTML = data.results.map((c) =>
              `<div class="res" data-name="${c.name}">${c.name}</div>`
            ).join("");
            resEl.querySelectorAll(".res").forEach((el) => {
              el.addEventListener("click", () => {
                const name = el.dataset.name;
                const match = data.results.find((x) => x.name === name);
                if (match) {
                  selectedCountry = match;
                  if ($("selectedCountryBadge")) $("selectedCountryBadge").textContent = `Selected: ${match.name}`;
                  $("countrySearchInput").value = match.name;
                  resEl.classList.add("hidden");
                  updateDownloadEstimate();
                }
              });
            });
          }
          resEl.classList.remove("hidden");
        } catch {
          resEl.classList.add("hidden");
        }
      }, 200);
    });

    if ($("selectedCountryBadge") && selectedCountry) {
      $("selectedCountryBadge").textContent = `Selected: ${selectedCountry.name}`;
    }
  }

  if ($("offlineWeight")) {
    $("offlineWeight").addEventListener("change", updateDownloadEstimate);
  }
  if ($("offlineRegion")) {
    $("offlineRegion").addEventListener("change", () => {
      if ($("offlineRegion").value === "country" && !selectedCountry) {
        selectedCountry = { name: "United States", bounds: [24.3963, -125.0, 49.3844, -66.9346] };
        if ($("selectedCountryBadge")) $("selectedCountryBadge").textContent = "Selected: United States";
      }
      updateDownloadEstimate();
    });
  }

  // Offline stats polling
  let offlinePollTimer = null;
  async function refreshOfflineStats() {
    try {
      const res = await api("/api/offline/status");
      if ($("offlineStorageBadge")) {
        const freeText = res.disk_free_formatted ? ` · ${res.disk_free_formatted} available` : "";
        $("offlineStorageBadge").textContent = `${res.size_formatted} used${freeText}`;
      }
      if ($("offlineTileCountText")) {
        $("offlineTileCountText").textContent = `Cached tiles: ${res.tile_count.toLocaleString()}`;
      }
      if ($("offlineDiskLeftText")) {
        $("offlineDiskLeftText").textContent = `Disk available: ${res.disk_free_formatted || "--"}`;
      }

      const progCard = $("offlineProgressCard");
      const progMsg = $("offlineProgressMsg");
      const progPct = $("offlineProgressPct");
      const progFill = $("offlineProgressFill");
      const startBtn = $("startOfflineDownloadBtn");
      const cancelBtn = $("cancelOfflineDownloadBtn");

      if (res.downloading) {
        if (progCard) progCard.classList.remove("hidden");
        if (progMsg) progMsg.textContent = res.message || "Downloading map pack…";
        if (progPct) progPct.textContent = `${res.percent}%`;
        if (progFill) progFill.style.width = `${res.percent}%`;
        if (startBtn) startBtn.disabled = true;
        if (cancelBtn) cancelBtn.classList.remove("hidden");

        clearTimeout(offlinePollTimer);
        offlinePollTimer = setTimeout(refreshOfflineStats, 1000);
      } else {
        if (startBtn) startBtn.disabled = false;
        if (cancelBtn) cancelBtn.classList.add("hidden");
        if (res.percent === 100) {
          if (progCard) progCard.classList.remove("hidden");
          if (progMsg) progMsg.textContent = res.message || "All tiles downloaded and ready offline.";
          if (progPct) progPct.textContent = "100%";
          if (progFill) progFill.style.width = "100%";
        } else if (res.message && res.message.startsWith("Stopped")) {
          if (progCard) progCard.classList.remove("hidden");
          if (progMsg) progMsg.textContent = res.message;
        }
      }
    } catch {
      // offline status failure is non-blocking
    }
  }

  // Offline map mode toggle
  if ($("settingOfflineMode")) {
    $("settingOfflineMode").addEventListener("change", (e) => {
      userSettings.offlineMode = !!e.target.checked;
      saveSettings();
      if (userSettings.offlineMode) {
        setMapTheme("offline");
        toast("Offline map mode enabled (using local cache)", "ok");
      } else {
        setMapTheme(userSettings.mapTheme);
        toast("Online map mode restored", "ok");
      }
    });
  }

  // Offline download action
  if ($("startOfflineDownloadBtn")) {
    $("startOfflineDownloadBtn").addEventListener("click", async () => {
      const region = $("offlineRegion") ? $("offlineRegion").value : "world";
      const weight = $("offlineWeight") ? $("offlineWeight").value : "moderate";
      const style = $("offlineMapStyle") ? $("offlineMapStyle").value : "topo";

      let bounds = null;
      if (region === "viewport") {
        const b = map.getBounds();
        bounds = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()];
      } else if (region === "country" && selectedCountry) {
        bounds = selectedCountry.bounds;
      }

      try {
        const res = await api("/api/offline/download", {
          package: region,
          weight: weight,
          style: style,
          country: (region === "country" && selectedCountry) ? selectedCountry.name : null,
          bounds: bounds,
        });
        if (res.error) {
          toast(res.error, "error");
          return;
        }
        toast("Offline map download started in background.", "ok");
        refreshOfflineStats();
      } catch (err) {
        toast(`Failed to start download: ${err.message}`, "error");
      }
    });
  }

  // Cancel offline download
  if ($("cancelOfflineDownloadBtn")) {
    $("cancelOfflineDownloadBtn").addEventListener("click", async () => {
      try {
        await api("/api/offline/cancel", {});
        toast("Download cancellation requested.", "ok");
        setTimeout(refreshOfflineStats, 500);
      } catch (err) {
        toast(`Error cancelling: ${err.message}`, "error");
      }
    });
  }

  // Clear offline tile cache
  if ($("clearOfflineCacheBtn")) {
    $("clearOfflineCacheBtn").addEventListener("click", async () => {
      if (!confirm("Clear all downloaded offline map tiles? This cannot be undone.")) return;
      try {
        await api("/api/offline/clear", {});
        toast("Offline map cache cleared.", "ok");
        refreshOfflineStats();
        updateDownloadEstimate();
      } catch (err) {
        toast(`Error clearing cache: ${err.message}`, "error");
      }
    });
  }

  // Theme
  if ($("settingMapTheme")) {
    $("settingMapTheme").addEventListener("change", (e) => {
      userSettings.mapTheme = e.target.value;
      if (!userSettings.offlineMode || e.target.value === "offline") {
        setMapTheme(userSettings.mapTheme);
      }
      saveSettings();
    });
  }

  // Auto center
  if ($("settingAutoCenter")) {
    $("settingAutoCenter").addEventListener("change", (e) => {
      userSettings.autoCenter = !!e.target.checked;
      saveSettings();
    });
  }

  // HUD
  if ($("settingShowHud")) {
    $("settingShowHud").addEventListener("change", (e) => {
      userSettings.showHud = !!e.target.checked;
      saveSettings();
      if (state.session) renderSession(state.session);
    });
  }

  // Units
  document.querySelectorAll("#settingUnitsControl .seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      userSettings.units = b.dataset.val;
      document.querySelectorAll("#settingUnitsControl .seg-btn").forEach((x) => x.classList.toggle("on", x === b));
      saveSettings();
      updateTripEta();
      if (state.session) renderSession(state.session);
    });
  });

  // Polling rate
  document.querySelectorAll("#settingPollInterval .seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      userSettings.pollInterval = +b.dataset.val;
      document.querySelectorAll("#settingPollInterval .seg-btn").forEach((x) => x.classList.toggle("on", x === b));
      saveSettings();
      schedulePoll();
    });
  });

  // Default roam radius
  if ($("settingDefaultRadius")) {
    $("settingDefaultRadius").addEventListener("input", (e) => {
      const val = Math.min(Math.max(+e.target.value || 120, 15), 2000);
      userSettings.defaultRadius = val;
      if ($("radiusInput")) $("radiusInput").value = val;
      saveSettings();
      redrawOverlays();
    });
  }

  // Default roam speed
  if ($("settingDefaultRoamSpeed")) {
    $("settingDefaultRoamSpeed").addEventListener("input", (e) => {
      const val = Math.min(Math.max(+e.target.value || 4.5, 0.5), 30);
      userSettings.defaultRoamSpeed = val;
      if ($("roamSpeedInput")) $("roamSpeedInput").value = val;
      saveSettings();
    });
  }

  // Default trip factor
  if ($("settingDefaultTripFactor")) {
    $("settingDefaultTripFactor").addEventListener("input", (e) => {
      const val = Math.min(Math.max(+e.target.value || 1.0, 0.1), 20);
      userSettings.defaultTripFactor = val;
      if ($("tripFactorInput")) $("tripFactorInput").value = val;
      saveSettings();
      updateTripEta();
    });
  }

  // Reset
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      userSettings = Object.assign({}, DEFAULT_SETTINGS);
      saveSettings();
      setMapTheme(userSettings.mapTheme);
      if ($("radiusInput")) $("radiusInput").value = userSettings.defaultRadius;
      if ($("roamSpeedInput")) $("roamSpeedInput").value = userSettings.defaultRoamSpeed;
      if ($("tripFactorInput")) $("tripFactorInput").value = userSettings.defaultTripFactor;
      if ($("settingOfflineMode")) $("settingOfflineMode").checked = false;
      syncSettingsInputs();
      redrawOverlays();
      updateTripEta();
      if (state.session) renderSession(state.session);
      schedulePoll();
      toast("Preferences reset to defaults.", "ok");
    });
  }
}

/* ----------------------------------------------------------------- boot */
let pollTimer = null;
function schedulePoll() {
  clearTimeout(pollTimer);
  const baseRate = userSettings.pollInterval || 1000;
  const interval = (state.session && state.session.state === "active") ? baseRate : Math.max(baseRate * 2.5, 2000);
  pollTimer = setTimeout(async () => {
    await poll();
    schedulePoll();
  }, interval);
}

if ($("radiusInput") && userSettings.defaultRadius) $("radiusInput").value = userSettings.defaultRadius;
if ($("roamSpeedInput") && userSettings.defaultRoamSpeed) $("roamSpeedInput").value = userSettings.defaultRoamSpeed;
if ($("tripFactorInput") && userSettings.defaultTripFactor) $("tripFactorInput").value = userSettings.defaultTripFactor;

initSettingsUI();
syncCoordInputs();
renderWaypoints();
setMode("fixed");
poll().then(() => schedulePoll());
