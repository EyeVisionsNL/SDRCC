/* SDRCC Map Lab: completely read-only experimental ADS-B/AIS viewer. */
(async () => {
    "use strict";
    const el = id => document.getElementById(id);
    const errorBox = el("map-error");
    const setError = message => {
        errorBox.textContent = message;
        errorBox.classList.add("visible");
    };
    let maplibregl;
    try {
        maplibregl = await import("https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs");
        if (!maplibregl.supported()) throw new Error("WebGL is not available in this browser.");
    } catch (error) {
        setError("The map library could not load: " + error.message
            + ". Internet access and WebGL are required. Your normal SDRCC maps remain available.");
        return;
    }

    const empty = {type: "FeatureCollection", features: []};
    const map = new maplibregl.Map({
        container: "map",
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [4.35, 51.91], zoom: 11, pitch: 0,
        canvasContextAttributes: {antialias: true},
    });
    map.addControl(new maplibregl.NavigationControl({showCompass: true}), "top-right");
    map.addControl(new maplibregl.ScaleControl({maxWidth: 130}), "bottom-left");
    let loaded = false;
    let mode3d = false;
    let resetCenter = [4.35, 51.91];
    let initialCenterSet = false;
    let inFlight = false;

    const validTargets = (rows, kind) => {
        if (!Array.isArray(rows)) return [];
        return rows.filter(row => row && row.type === kind && Number.isFinite(row.lon)
            && Number.isFinite(row.lat) && Math.abs(row.lon) <= 180
            && Math.abs(row.lat) <= 90).slice(0, 2000);
    };
    function makeGeoJson(rows) {
        return {
            type: "FeatureCollection",
            features: rows.map(item => ({
                type: "Feature",
                geometry: {type: "Point", coordinates: [item.lon, item.lat]},
                properties: {
                    type: item.type,
                    id: String(item.id || ""),
                    name: String(item.name || item.id || ""),
                    callsign: String(item.callsign || ""),
                    course: item.course,
                    speed_knots: item.speed_knots,
                    altitude_ft: item.altitude_ft,
                    age_seconds: item.age_seconds,
                },
            })),
        };
    }
    function setLayerVisibility(kind, visible) {
        if (!loaded) return;
        for (const suffix of ["dots", "labels"]) {
            const id = "sdrcc-" + kind + "-" + suffix;
            if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
        }
    }
    function setMode(three) {
        mode3d = three;
        el("mode-2d").setAttribute("aria-pressed", String(!three));
        el("mode-3d").setAttribute("aria-pressed", String(three));
        if (!loaded) return;
        map.easeTo({
            pitch: three ? 62 : 0,
            bearing: three ? -22 : 0,
            duration: 700,
        });
        if (map.getLayer("sdrcc-buildings")) {
            map.setLayoutProperty("sdrcc-buildings", "visibility", three ? "visible" : "none");
        }
    }
    function popup(feature) {
        const props = feature.properties || {};
        const box = document.createElement("div");
        const title = document.createElement("div");
        title.className = "popup-title";
        title.textContent = (props.type === "ais" ? "🚢 " : "✈ ") + (props.name || props.id);
        box.appendChild(title);
        const line = text => {
            const element = document.createElement("div");
            element.className = "popup-line";
            element.textContent = text;
            box.appendChild(element);
        };
        line((props.type === "ais" ? "MMSI: " : "ICAO: ") + (props.id || "?"));
        if (props.callsign) line("Callsign: " + props.callsign);
        if (props.course !== null && props.course !== undefined) line("Heading/course: " + props.course + "°");
        if (props.speed_knots !== null && props.speed_knots !== undefined) line("Speed: " + props.speed_knots + " kn");
        if (props.type === "adsb" && props.altitude_ft !== null && props.altitude_ft !== undefined) {
            line("Reported altitude: " + Number(props.altitude_ft).toLocaleString() + " ft");
        }
        if (props.age_seconds !== null && props.age_seconds !== undefined) line("Last position: " + props.age_seconds + " s ago");
        return box;
    }
    function addPoints(kind, color) {
        const source = "sdrcc-" + kind;
        map.addSource(source, {type: "geojson", data: empty});
        map.addLayer({
            id: source + "-dots", type: "circle", source,
            paint: {
                "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3.5, 13, 7],
                "circle-color": color,
                "circle-stroke-color": "#062032", "circle-stroke-width": 1.7,
                "circle-opacity": .96,
            },
        });
        map.addLayer({
            id: source + "-labels", type: "symbol", source,
            minzoom: 11,
            layout: {
                "text-field": ["get", "name"],
                "text-size": 11,
                "text-offset": [0, 1.2],
                "text-anchor": "top",
                "text-optional": true,
            },
            paint: {"text-color": "#f4faff", "text-halo-color": "#11283b", "text-halo-width": 1.4},
        });
        map.on("click", source + "-dots", event => {
            const feature = event.features && event.features[0];
            if (!feature) return;
            new maplibregl.Popup({offset: 12, maxWidth: "300px"})
                .setLngLat(feature.geometry.coordinates)
                .setDOMContent(popup(feature))
                .addTo(map);
        });
        map.on("mouseenter", source + "-dots", () => {map.getCanvas().style.cursor = "pointer";});
        map.on("mouseleave", source + "-dots", () => {map.getCanvas().style.cursor = "";});
    }
    function addBuildings() {
        try {
            map.addSource("sdrcc-building-tiles", {
                type: "vector", url: "https://tiles.openfreemap.org/planet",
            });
            const label = map.getStyle().layers.find(layer =>
                layer.type === "symbol" && layer.layout && layer.layout["text-field"]);
            map.addLayer({
                id: "sdrcc-buildings", source: "sdrcc-building-tiles",
                "source-layer": "building",
                type: "fill-extrusion", minzoom: 15,
                layout: {visibility: "none"},
                filter: ["!=", ["get", "hide_3d"], true],
                paint: {
                    "fill-extrusion-color": "#79a9c6",
                    "fill-extrusion-opacity": .7,
                    "fill-extrusion-height": ["coalesce", ["get", "render_height"], 8],
                    "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
                },
            }, label && label.id);
        } catch (error) {
            setError("3D building layer is unavailable: " + error.message + ". The 2D traffic map remains usable.");
        }
    }

    async function refresh() {
        if (inFlight || document.hidden) return;
        inFlight = true;
        try {
            const response = await fetch("/api/map-lab/traffic", {cache: "no-store"});
            if (!response.ok) throw new Error("SDRCC API HTTP " + response.status);
            const data = await response.json();
            if (!data.ok) throw new Error("Traffic data unavailable");
            if (Array.isArray(data.center) && data.center.length === 2
                    && data.center.every(Number.isFinite)) {
                resetCenter = data.center;
                if (!initialCenterSet && loaded) {
                    map.jumpTo({center: resetCenter});
                    initialCenterSet = true;
                }
            }
            const ships = validTargets(data.ais?.targets, "ais");
            const planes = validTargets(data.adsb?.targets, "adsb");
            el("count-ais").textContent = data.ais?.available ? ships.length : "OFF";
            el("count-adsb").textContent = data.adsb?.available ? planes.length : "OFF";
            el("feed-status").textContent =
                "AIS " + (data.ais?.available ? "LIVE" : "UNAVAILABLE")
                + " · ADS-B " + (data.adsb?.available ? "LIVE" : "UNAVAILABLE")
                + " · Updated " + new Date().toLocaleTimeString();
            if (loaded) {
                map.getSource("sdrcc-ais").setData(makeGeoJson(ships));
                map.getSource("sdrcc-adsb").setData(makeGeoJson(planes));
            }
        } catch (error) {
            el("feed-status").textContent = "Traffic refresh failed: " + error.message;
        } finally {
            inFlight = false;
        }
    }

    map.on("load", () => {
        addBuildings();
        addPoints("ais", "#34d5e5");
        addPoints("adsb", "#ffbd73");
        loaded = true;
        setLayerVisibility("ais", el("layer-ais").checked);
        setLayerVisibility("adsb", el("layer-adsb").checked);
        setMode(mode3d);
        refresh();
    });
    map.on("error", event => {
        const reason = event.error && event.error.message || "";
        if (/style|tile|network|fetch|load/i.test(reason)) {
            el("feed-status").textContent = "Basemap network warning; the existing SDRCC viewers remain available.";
        }
    });
    el("mode-2d").addEventListener("click", () => setMode(false));
    el("mode-3d").addEventListener("click", () => setMode(true));
    el("layer-ais").addEventListener("change", () => setLayerVisibility("ais", el("layer-ais").checked));
    el("layer-adsb").addEventListener("change", () => setLayerVisibility("adsb", el("layer-adsb").checked));
    el("reset-view").addEventListener("click", () => {
        map.easeTo({center: resetCenter, zoom: 11, bearing: mode3d ? -22 : 0, pitch: mode3d ? 62 : 0});
    });
    el("refresh-now").addEventListener("click", refresh);
    window.setInterval(refresh, 10000);
})();
