// Geox Mobile Remote — Web Application for phone-driven location control

(function () {
  let map = null;
  let marker = null;
  let targetLat = 45.5017;
  let targetLng = -73.5673;
  let currentMode = "fixed"; // fixed, jitter, lock
  let selectedDeviceId = localStorage.getItem("geox_remote_device") || "";
  let dpadStep = 10;
  let devices = [];
  let pollTimer = null;
  let searchDebounce = null;
  let currentLayerIndex = 0;

  const tileLayers = [
    {
      name: "streets",
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      attribution: "Tiles © Esri"
    },
    {
      name: "topo",
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
      attribution: "Tiles © Esri"
    },
    {
      name: "dark",
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      attribution: "Tiles © Esri"
    }
  ];
  let activeTileLayer = null;

  // DOM Elements
  const deviceSelect = document.getElementById("deviceSelect");
  const statusBadge = document.getElementById("statusBadge");
  const searchInput = document.getElementById("searchInput");
  const suggestionsBox = document.getElementById("suggestions");
  const coordsPill = document.getElementById("coordsPill");
  const applyBtn = document.getElementById("applyBtn");
  const stopBtn = document.getElementById("stopBtn");
  const recenterBtn = document.getElementById("recenterBtn");
  const layerToggleBtn = document.getElementById("layerToggleBtn");
  const dpadToggleBtn = document.getElementById("dpadToggleBtn");
  const dpadPanel = document.getElementById("dpadPanel");
  const dpadStepBtn = document.getElementById("dpadStep");

  function initMap() {
    map = L.map("map", {
      center: [targetLat, targetLng],
      zoom: 14,
      zoomControl: false
    });

    setTileLayer(0);

    const icon = L.divIcon({
      className: "geox-pin",
      html: '<div style="width:20px;height:20px;background:#22c55e;border:3px solid #fff;border-radius:50%;box-shadow:0 0 10px rgba(0,0,0,0.5);"></div>',
      iconSize: [20, 20],
      iconAnchor: [10, 10]
    });

    marker = L.marker([targetLat, targetLng], {
      draggable: true,
      icon: icon
    }).addTo(map);

    marker.on("dragend", function (e) {
      const ll = e.target.getLatLng();
      updateCoordinates(ll.lat, ll.lng);
    });

    map.on("click", function (e) {
      updateCoordinates(e.latlng.lat, e.latlng.lng);
      marker.setLatLng(e.latlng);
    });

    updateCoordinates(targetLat, targetLng);
  }

  function setTileLayer(idx) {
    if (activeTileLayer) {
      map.removeLayer(activeTileLayer);
    }
    currentLayerIndex = idx % tileLayers.length;
    const l = tileLayers[currentLayerIndex];
    activeTileLayer = L.tileLayer(l.url, {
      maxZoom: 18,
      attribution: l.attribution
    }).addTo(map);
  }

  function updateCoordinates(lat, lng) {
    targetLat = Number(lat.toFixed(6));
    targetLng = Number(lng.toFixed(6));
    if (coordsPill) {
      coordsPill.textContent = `${targetLat.toFixed(6)}, ${targetLng.toFixed(6)}`;
    }
  }

  function setPin(lat, lng, pan) {
    updateCoordinates(lat, lng);
    if (marker) marker.setLatLng([targetLat, targetLng]);
    if (pan && map) map.panTo([targetLat, targetLng]);
  }

  // Poll server status
  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();
      devices = data.devices || [];

      // Update Device select
      const prevVal = deviceSelect.value || selectedDeviceId;
      deviceSelect.innerHTML = "";

      if (devices.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No devices detected";
        deviceSelect.appendChild(opt);
        statusBadge.textContent = "Offline";
        statusBadge.className = "status-badge";
      } else {
        devices.forEach((d) => {
          const opt = document.createElement("option");
          opt.value = d.id;
          const conn = d.connection ? ` [${d.connection}]` : "";
          opt.textContent = `${d.name || d.display_name || d.model || d.id}${conn}`;
          if (d.id === prevVal) opt.selected = true;
          deviceSelect.appendChild(opt);
        });

        if (!deviceSelect.value && devices.length > 0) {
          deviceSelect.value = devices[0].id;
        }
        selectedDeviceId = deviceSelect.value;
        localStorage.setItem("geox_remote_device", selectedDeviceId);

        // Update badge for current device
        const currentDev = devices.find((d) => d.id === selectedDeviceId);
        const session = (data.sessions || []).find((s) => s.device_id === selectedDeviceId);

        if (session && session.state === "active") {
          statusBadge.textContent = "Active";
          statusBadge.className = "status-badge active";
          const sLat = (session.coords && session.coords.lat) != null ? session.coords.lat : (session.last && session.last[0]);
          const sLng = (session.coords && session.coords.lng) != null ? session.coords.lng : (session.last && session.last[1]);
          if (sLat != null && sLng != null) {
            setPin(sLat, sLng, false);
          }
        } else if (session && session.state === "locked_unplugged") {
          statusBadge.textContent = "Locked";
          statusBadge.className = "status-badge locked";
        } else {
          statusBadge.textContent = "Idle";
          statusBadge.className = "status-badge";
        }
      }
    } catch (e) {
      statusBadge.textContent = "Disconnected";
      statusBadge.className = "status-badge";
    }
  }

  // Start / Update Spoofing
  async function applyLocation() {
    if (!selectedDeviceId) {
      alert("Please connect a device first.");
      return;
    }

    const payload = {
      device_id: selectedDeviceId,
      lat: targetLat,
      lng: targetLng,
      speed_kmh: 4.5
    };

    if (currentMode === "jitter") {
      payload.mode = "jitter";
      payload.radius_m = 100;
    } else if (currentMode === "lock") {
      payload.mode = "fixed";
      payload.unplug_lock = true;
    } else {
      payload.mode = "fixed";
    }

    applyBtn.textContent = "Applying...";
    try {
      const res = await fetch("/api/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "Failed to set location");
        applyBtn.textContent = "Spoof Location";
      } else {
        applyBtn.textContent = "Location Set!";
        setTimeout(() => {
          applyBtn.textContent = "Spoof Location";
        }, 1500);
        pollStatus();
      }
    } catch (err) {
      alert("Connection error: " + err.message);
      applyBtn.textContent = "Spoof Location";
    }
  }

  // Restore Real GPS
  async function stopSpoofing() {
    if (!selectedDeviceId) return;
    stopBtn.textContent = "Stopping...";
    try {
      const res = await fetch("/api/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: selectedDeviceId })
      });
      await res.json();
      stopBtn.textContent = "GPS Restored";
      setTimeout(() => {
        stopBtn.textContent = "Restore GPS";
      }, 1500);
      pollStatus();
    } catch (err) {
      stopBtn.textContent = "Restore GPS";
    }
  }

  // D-Pad Nudge
  async function nudge(direction) {
    if (!selectedDeviceId) return;
    try {
      if (window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(20);
      }
      const res = await fetch("/api/nudge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: selectedDeviceId,
          direction: direction,
          step_m: dpadStep,
          lat: targetLat,
          lng: targetLng
        })
      });
      const data = await res.json();
      if (data.lat !== undefined && data.lng !== undefined) {
        setPin(data.lat, data.lng, true);
      }
    } catch (err) {
      console.error("Nudge error:", err);
    }
  }

  // Search autocomplete
  function initSearch() {
    searchInput.addEventListener("input", function () {
      clearTimeout(searchDebounce);
      const q = searchInput.value.trim();
      if (q.length < 2) {
        suggestionsBox.classList.add("hidden");
        suggestionsBox.innerHTML = "";
        return;
      }
      searchDebounce = setTimeout(async () => {
        try {
          const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}&lat=${targetLat}&lng=${targetLng}`);
          if (!res.ok) return;
          const data = await res.json();
          renderSuggestions(data.results || []);
        } catch (e) {}
      }, 300);
    });

    document.addEventListener("click", function (e) {
      if (!searchInput.contains(e.target) && !suggestionsBox.contains(e.target)) {
        suggestionsBox.classList.add("hidden");
      }
    });
  }

  function renderSuggestions(results) {
    suggestionsBox.innerHTML = "";
    if (results.length === 0) {
      suggestionsBox.classList.add("hidden");
      return;
    }
    results.slice(0, 6).forEach((item) => {
      const div = document.createElement("div");
      div.className = "suggestion-item";
      div.textContent = item.display_name || item.name;
      div.addEventListener("click", () => {
        const lat = parseFloat(item.lat);
        const lng = parseFloat(item.lon || item.lng);
        setPin(lat, lng, true);
        suggestionsBox.classList.add("hidden");
        searchInput.value = item.display_name || item.name;
      });
      suggestionsBox.appendChild(div);
    });
    suggestionsBox.classList.remove("hidden");
  }

  // Wire event handlers
  function initEvents() {
    deviceSelect.addEventListener("change", () => {
      selectedDeviceId = deviceSelect.value;
      localStorage.setItem("geox_remote_device", selectedDeviceId);
      pollStatus();
    });

    applyBtn.addEventListener("click", applyLocation);
    stopBtn.addEventListener("click", stopSpoofing);

    recenterBtn.addEventListener("click", () => {
      if (map) map.setView([targetLat, targetLng], 15);
    });

    layerToggleBtn.addEventListener("click", () => {
      setTileLayer(currentLayerIndex + 1);
    });

    dpadToggleBtn.addEventListener("click", () => {
      dpadPanel.classList.toggle("hidden");
    });

    // Preset chips
    document.querySelectorAll(".preset-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const lat = parseFloat(chip.dataset.lat);
        const lng = parseFloat(chip.dataset.lng);
        setPin(lat, lng, true);
      });
    });

    // Mode pills
    document.querySelectorAll(".mode-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".mode-pill").forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        currentMode = pill.dataset.mode;
      });
    });

    // D-Pad buttons
    document.getElementById("dpadNorth").addEventListener("click", () => nudge("north"));
    document.getElementById("dpadSouth").addEventListener("click", () => nudge("south"));
    document.getElementById("dpadEast").addEventListener("click", () => nudge("east"));
    document.getElementById("dpadWest").addEventListener("click", () => nudge("west"));

    const stepOptions = [5, 10, 25, 50];
    let stepIdx = 1;
    dpadStepBtn.addEventListener("click", () => {
      stepIdx = (stepIdx + 1) % stepOptions.length;
      dpadStep = stepOptions[stepIdx];
      dpadStepBtn.textContent = dpadStep + "m";
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    initMap();
    initSearch();
    initEvents();
    pollStatus();
    pollTimer = setInterval(pollStatus, 2000);
  });
})();
