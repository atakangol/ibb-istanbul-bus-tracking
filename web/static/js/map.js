/** Leaflet map and per-slot layer groups. */

const SLOT_COLORS = ["#2563eb", "#dc2626", "#16a34a"];

const IstanbulMap = (() => {
  const ISTANBUL_CENTER = [41.01, 28.97];
  const DEFAULT_ZOOM = 11;

  let map = null;
  const layerGroups = [];

  function init() {
    map = L.map("map", { zoomControl: true }).setView(ISTANBUL_CENTER, DEFAULT_ZOOM);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · ' +
        'Routes <a href="https://project-osrm.org/">OSRM</a>',
    }).addTo(map);

    for (let i = 0; i < 3; i += 1) {
      const group = L.layerGroup().addTo(map);
      layerGroups.push(group);
    }
  }

  function colorForSlot(index) {
    return SLOT_COLORS[index] ?? SLOT_COLORS[0];
  }

  function clearSlot(index) {
    const group = layerGroups[index];
    if (group) {
      group.clearLayers();
    }
  }

  function renderRoute(index, route) {
    clearSlot(index);
    const group = layerGroups[index];
    const color = colorForSlot(index);
    const latlngs =
      route.path && route.path.length >= 2
        ? route.path.map((p) => [p.lat, p.lon])
        : route.stops.map((s) => [s.lat, s.lon]);

    if (latlngs.length >= 2) {
      L.polyline(latlngs, {
        color,
        weight: 5,
        opacity: 0.85,
      }).addTo(group);
    }

    route.stops.forEach((stop) => {
      const marker = L.circleMarker([stop.lat, stop.lon], {
        radius: 5,
        color,
        fillColor: color,
        fillOpacity: 0.9,
        weight: 2,
      });
      marker.bindPopup(
        `<strong>${stop.order}. ${escapeHtml(stop.name)}</strong><br>` +
          `Code: ${escapeHtml(stop.code)}`,
      );
      marker.addTo(group);
    });
  }

  function fitAllSlots() {
    const bounds = L.latLngBounds([]);
    let hasPoints = false;

    layerGroups.forEach((group) => {
      group.eachLayer((layer) => {
        if (layer instanceof L.Polyline) {
          bounds.extend(layer.getBounds());
          hasPoints = true;
        } else if (layer instanceof L.CircleMarker) {
          bounds.extend(layer.getLatLng());
          hasPoints = true;
        }
      });
    });

    if (hasPoints) {
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 15 });
    } else {
      map.setView(ISTANBUL_CENTER, DEFAULT_ZOOM);
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  return {
    init,
    colorForSlot,
    clearSlot,
    renderRoute,
    fitAllSlots,
  };
})();
