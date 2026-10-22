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
        // MapLibre 6 uses named ESM exports and no longer exposes supported().
        maplibregl = await import("https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs");
        if (typeof maplibregl.Map !== "function") {
            throw new Error("MapLibre's Map export is missing.");
        }
    } catch (error) {
        setError("The MapLibre library could not load: " + error.message
            + ". Check the CDN connection; your existing SDRCC maps are unaffected.");
        return;
    }

    const empty = {type: "FeatureCollection", features: []};
    let map;
    try {
        // MapLibre 6 reports WebGL/GPU initialization failures here.
        map = new maplibregl.Map({
            container: "map",
            style: "https://tiles.openfreemap.org/styles/liberty",
            center: [4.35, 51.91], zoom: 11, pitch: 0,
            canvasContextAttributes: {antialias: true},
        });
    } catch (error) {
        setError("Map initialization failed: " + error.message
            + ". Check WebGL support; your existing SDRCC maps are unaffected.");
        return;
    }
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
                    course: Number.isFinite(item.course) ? item.course : null,
                    course_known: Number.isFinite(item.course),
                    speed_knots: item.speed_knots,
                    altitude_ft: item.altitude_ft,
                    age_seconds: item.age_seconds,
                    validation_state: item.validation_state || "unknown",
                },
            })),
        };
    }
    function setLayerVisibility(kind, visible) {
        if (!loaded) return;
        for (const suffix of ["icons", "labels"]) {
            const id = "sdrcc-" + kind + "-" + suffix;
            const enabled = visible && (suffix !== "labels" || el("show-names").checked);
            if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", enabled ? "visible" : "none");
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
        if (props.type === "ais" && props.validation_state === "unverified") {
            line("Position not verified by AIS-Catcher");
        }
        if (props.callsign) line("Callsign: " + props.callsign);
        line(props.course_known ? "Reported course/track: " + props.course + "°" : "Course/track not reported (?)");
        if (props.speed_knots !== null && props.speed_knots !== undefined) line("Speed: " + props.speed_knots + " kn");
        if (props.type === "adsb" && props.altitude_ft !== null && props.altitude_ft !== undefined) {
            line("Reported altitude: " + Number(props.altitude_ft).toLocaleString() + " ft");
        }
        if (props.age_seconds !== null && props.age_seconds !== undefined) line("Last position: " + props.age_seconds + " s ago");
        return box;
    }
    // Draw local, crisp 2x sprites; MapLibre 6 supports ImageData in addImage.
    // Sprite noses point north; `icon-rotate` uses course/track in degrees.
    // No external images, emojis/font dependencies, or a second AIS/ADS-B feed.
    function sprite(kind, color, unknownCourse = false) {
        const canvas = document.createElement("canvas");
        canvas.width = 96;
        canvas.height = 96;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas 2D context is unavailable");
        ctx.scale(2, 2);
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.shadowColor = "rgba(1, 15, 29, 0.8)";
        ctx.shadowBlur = 3;
        ctx.shadowOffsetY = 1.5;
        ctx.fillStyle = color;
        ctx.strokeStyle = "#07243a";
        ctx.lineWidth = 2.4;

        ctx.beginPath();
        if (kind === "ais") {
            // Vessel silhouette: pointed bow, long hull and square stern.
            ctx.moveTo(24, 5);
            ctx.bezierCurveTo(29, 10, 33, 16, 33, 24);
            ctx.lineTo(31, 40);
            ctx.quadraticCurveTo(24, 43, 17, 40);
            ctx.lineTo(15, 24);
            ctx.bezierCurveTo(15, 16, 19, 10, 24, 5);
        } else {
            // Distinct top-down aircraft silhouette, not an ambiguous dot.
            ctx.moveTo(24, 3);
            ctx.quadraticCurveTo(27.5, 6, 27.5, 11);
            ctx.lineTo(28.5, 20);
            ctx.lineTo(42.5, 27);
            ctx.lineTo(42.5, 31);
            ctx.lineTo(28, 27);
            ctx.lineTo(27.5, 35);
            ctx.lineTo(34, 39);
            ctx.lineTo(34, 42);
            ctx.lineTo(24, 39);
            ctx.lineTo(14, 42);
            ctx.lineTo(14, 39);
            ctx.lineTo(20.5, 35);
            ctx.lineTo(20, 27);
            ctx.lineTo(5.5, 31);
            ctx.lineTo(5.5, 27);
            ctx.lineTo(19.5, 20);
            ctx.lineTo(20.5, 11);
            ctx.quadraticCurveTo(20.5, 6, 24, 3);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.shadowColor = "transparent";

        ctx.strokeStyle = "rgba(255,255,255,0.94)";
        ctx.lineWidth = 1.6;
        if (kind === "ais") {
            ctx.beginPath();
            ctx.moveTo(20, 26);
            ctx.lineTo(28, 26);
            ctx.moveTo(21, 33);
            ctx.lineTo(27, 33);
            ctx.stroke();
            ctx.fillStyle = "#e5fbff";
            ctx.fillRect(20, 19, 8, 4.5);
        } else {
            ctx.beginPath();
            ctx.moveTo(24, 9);
            ctx.lineTo(24, 31);
            ctx.stroke();
        }
        // A '?' badge prevents pointing-north from implying a known bearing.
        if (unknownCourse) {
            ctx.beginPath();
            ctx.fillStyle = "#132a41";
            ctx.strokeStyle = "#eff8ff";
            ctx.lineWidth = 1.2;
            ctx.arc(38, 38, 7, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = "#fff";
            ctx.font = "bold 11px system-ui, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("?", 38, 38);
        }
        return ctx.getImageData(0, 0, 96, 96);
    }
    function registerSprites() {
        for (const [name, kind, color] of [
            ["sdrcc-ship", "ais", "#34d5e5"],
            ["sdrcc-ship-unverified", "ais", "#ff9f68"],
            ["sdrcc-plane", "adsb", "#ffbd73"],
        ]) {
            map.addImage(name, sprite(kind, color), {pixelRatio: 2});
            map.addImage(name + "-no-course", sprite(kind, color, true), {pixelRatio: 2});
        }
    }
    function addPoints(kind) {
        const source = "sdrcc-" + kind;
        map.addSource(source, {type: "geojson", data: empty});
        const baseIcon = kind === "ais"
            ? ["case", ["==", ["get", "validation_state"], "unverified"],
                "sdrcc-ship-unverified", "sdrcc-ship"]
            : "sdrcc-plane";
        map.addLayer({
            id: source + "-icons", type: "symbol", source,
            layout: {
                "icon-image": ["concat", baseIcon,
                    ["case", ["==", ["get", "course_known"], true], "", "-no-course"]],
                "icon-size": ["interpolate", ["linear"], ["zoom"],
                    7, 0.36, 10, 0.53, 13, 0.76, 16, 0.91],
                // Course/track is compass degrees clockwise from true north.
                "icon-rotate": ["coalesce", ["get", "course"], 0],
                "icon-rotation-alignment": "map",
                "icon-pitch-alignment": "viewport",
                "icon-allow-overlap": true,
                "icon-ignore-placement": true,
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
        map.on("click", source + "-icons", event => {
            const feature = event.features && event.features[0];
            if (!feature) return;
            new maplibregl.Popup({offset: 12, maxWidth: "300px"})
                .setLngLat(feature.geometry.coordinates)
                .setDOMContent(popup(feature))
                .addTo(map);
        });
        map.on("mouseenter", source + "-icons", () => {map.getCanvas().style.cursor = "pointer";});
        map.on("mouseleave", source + "-icons", () => {map.getCanvas().style.cursor = "";});
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
            const aisTotal = Number.isInteger(data.ais?.source_count) ? data.ais.source_count : ships.length;
            const adsbTotal = Number.isInteger(data.adsb?.source_count) ? data.adsb.source_count : planes.length;
            const unverified = Number.isInteger(data.ais?.unverified_count) ? data.ais.unverified_count : 0;
            el("feed-detail").textContent =
                `AIS: ${ships.length} plotted from ${aisTotal} records`
                + (unverified ? ` (orange: ${unverified} unverified)` : "")
                + ` · ADS-B: ${planes.length} plotted from ${adsbTotal} records`;
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
        registerSprites();
        addPoints("ais");
        addPoints("adsb");
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
    el("show-names").addEventListener("change", () => {
        setLayerVisibility("ais", el("layer-ais").checked);
        setLayerVisibility("adsb", el("layer-adsb").checked);
    });
    el("reset-view").addEventListener("click", () => {
        map.easeTo({center: resetCenter, zoom: 11, bearing: mode3d ? -22 : 0, pitch: mode3d ? 62 : 0});
    });
    el("refresh-now").addEventListener("click", refresh);
    window.setInterval(refresh, 10000);
})();
