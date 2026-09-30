/* Geox UI logic — vanilla JS, Leaflet map, talks to /api/* */

const $ = (id) => document.getElementById(id);

const state = {
  mode: "fixed",            // fixed | jitter | custom | trip
  target: { lat: 49.2827, lng: -123.1207, place: "Vancouver, Canada" },
  waypoints: [],            // custom draw mode
  trip: null,               // planned itinerary {waypoints, distance_km, ...}
  tripProfile: "car",
  devices: [],
  selected: null,
  session: null,
  activeTarget: null,       // current active spoof parameters
  pickMode: false,
};

/* ------------------------------------------------------------------ map */
const map = L.map("map", { zoomControl: true }).setView([state.target.lat, state.target.lng], 5);
// Esri World Dark Gray Canvas — free, no API key, matches the theme
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ", maxZoom: 16 },
).addTo(map);

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
  const route = state.mode === "trip" && state.trip ? state.trip.waypoints : state.waypoints;
  if ((state.mode === "custom" || state.mode === "trip") && route.length) {
    L.polyline(route, { color: "#22c55e", weight: 3, opacity: 0.85 }).addTo(layers);
    route.forEach((p, i) => {
      L.circleMarker(p, {
        radius: state.mode === "custom" ? 5 : 2.5,
        color: "#22c55e", fillColor: "#05210f", fillOpacity: 1, weight: 2,
      }).addTo(layers);
    });
  }
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
  if (state.mode !== "custom") return;
  state.waypoints.push([e.latlng.lat, e.latlng.lng]);
  renderWaypoints();
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

async function doSearch() {
  const q = $("searchInput").value.trim();
  if (q.length < 2) return;
  $("searchResults").classList.remove("hidden");
  $("searchResults").innerHTML = `<div class="res muted">Searching…</div>`;
  try {
    const d = await api("/api/geocode", { q });
    if (!d.results.length) { $("searchResults").innerHTML = `<div class="res">No results</div>`; return; }
    $("searchResults").innerHTML = d.results
      .map((r, i) => `<div class="res" data-i="${i}">${r.label}</div>`).join("");
    $("searchResults").querySelectorAll(".res").forEach((el) => {
      el.addEventListener("click", () => {
        const r = d.results[+el.dataset.i];
        setTarget(r.lat, r.lng, r.label);
        $("searchResults").classList.add("hidden");
      });
    });
  } catch (e) {
    $("searchResults").innerHTML = `<div class="res">${e.message}</div>`;
  }
}
$("searchBtn").addEventListener("click", doSearch);
$("searchInput").addEventListener("keydown", (e) => e.key === "Enter" && doSearch());
document.addEventListener("click", (e) => {
  if (!$("searchInput").contains(e.target) && !$("searchResults").contains(e.target))
    $("searchResults").classList.add("hidden");
});

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
for (const [label, lat, lng] of PRESETS) {
  const b = document.createElement("button");
  b.className = "chip";
  b.textContent = label;
  b.addEventListener("click", () => setTarget(lat, lng, label.replace(/^\S+\s/, "")));
  $("presets").appendChild(b);
}

function setTarget(lat, lng, place) {
  state.target = { lat, lng, place: place || "" };
  syncCoordInputs();
  map.setView([lat, lng], Math.max(map.getZoom(), 10));
  redrawOverlays();
  if (place) $("placeLabel").textContent = place;
  if (typeof updateControlButtons === "function") updateControlButtons();
}

/* ------------------------------------------------------------- mode tabs */
function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll("#modeChips .chip").forEach((c) =>
    c.classList.toggle("on", c.dataset.mode === mode));
  $("roamOpts").classList.toggle("hidden", mode !== "jitter");
  $("customOpts").classList.toggle("hidden", mode !== "custom");
  $("tripOpts").classList.toggle("hidden", mode !== "trip");
  redrawOverlays();
  if (typeof updateControlButtons === "function") updateControlButtons();
}
document.querySelectorAll("#modeChips .chip").forEach((c) =>
  c.addEventListener("click", () => setMode(c.dataset.mode)));

$("radiusInput").addEventListener("change", () => {
  redrawOverlays();
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
$("clearWpsBtn").addEventListener("click", () => { state.waypoints = []; renderWaypoints(); });

/* ----------------------------------------------------------------- trip */
document.querySelectorAll("#tripProfiles .chip").forEach((c) =>
  c.addEventListener("click", () => {
    state.tripProfile = c.dataset.profile;
    document.querySelectorAll("#tripProfiles .chip").forEach((x) =>
      x.classList.toggle("on", x === c));
  }));

$("tripPlanBtn").addEventListener("click", planTrip);
$("tripDestInput").addEventListener("keydown", (e) => e.key === "Enter" && planTrip());
$("tripFactorInput").addEventListener("change", updateTripEta);

function updateTripEta() {
  if (!state.trip) return;
  const f = Math.min(Math.max(+$("tripFactorInput").value || 1, 0.1), 20);
  const mins = Math.max(1, Math.round(state.trip.duration_min / f));
  $("tripEta").value = `about ${mins >= 60 ? Math.floor(mins / 60) + " h " : ""}${mins % 60} min`;
  if (!$("tripSummary").classList.contains("hidden")) {
    const label = mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${mins} min`;
    $("tripSummary").innerHTML =
      `<b>${state.trip.distance_km} km</b> · about <b>${label}</b> · ` +
      `avg ${(state.trip.speed_kmh * f).toFixed(1)} km/h · ${state.trip.waypoints.length} points<br>` +
      `Destination: ${state.trip.dest_label}<br>Speeds follow the real road (highway fast, city slow), ` +
      `scaled ×${f}, then it parks at the destination.`;
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
    state.trip = trip;
    setMode("trip");
    redrawOverlays();
    updateTripEta();
    map.fitBounds(L.polyline(trip.waypoints).getBounds(), { padding: [40, 40] });
    toast("Itinerary planned — press START SPOOFING or Auto Swap.", "ok");
    if (typeof updateControlButtons === "function") updateControlButtons();
  } catch (e) {
    state.trip = null;
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
  el.innerHTML = `<span class="live"></span><b>Spoofing ${s.device_name}</b> — ${modeName}<br>
    ${s.place ? s.place + "<br>" : ""}now at ${fmtCoord(s.last[0])}, ${fmtCoord(s.last[1])}
    ${s.engine === "dvt-tunnel-cli" ? "<br><span class='muted small'>iOS 17+ tunnel session</span>" : ""}`;
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
    const curWps = state.trip.waypoints || [];
    const prevWps = at.trip.waypoints || [];
    return curWps.length !== prevWps.length;
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
      };
    } else if (!s || s.state === "stopped" || s.state === "failed") {
      state.activeTarget = null;
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
    await api("/api/stop", { device_id: state.selected || (state.session && state.session.device_id) });
    state.activeTarget = null;
    toast("Stopped — real GPS restored.", "ok");
    updateControlButtons();
    poll();
  } catch (e) { toast(e.message, "error"); }
});

/* ----------------------------------------------------------------- boot */
syncCoordInputs();
renderWaypoints();
setMode("fixed");
poll();
setInterval(poll, 2500);
