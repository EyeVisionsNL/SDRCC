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
    // Local tangent plane: metres from the AIS antenna become geographic coordinates.
    // The reported bow/stern/port/starboard offsets define real hull size.
    // In a harbour we want geographic-scale hulls, not a fixed pixel-length emoji.
    const HULL_MIN_ZOOM = 14;
    const AIS_NAME_MIN_ZOOM = 12.5;
    // Mirror AIS-catcher's class palette (shipclass from the AIS JSON).
    // A matching colour is used for compact arrows/dots, hull edges and names.
    const AIS_CLASS_COLORS = Object.freeze({
        0:"#22bdf0", 1:"#22bdf0", 2:"#1fbf5c", 3:"#c04ef0",
        4:"#2c4fd0", 5:"#6b3d10", 6:"#d93a2b", 7:"#f2c81a",
        8:"#ff86b4", 9:"#ff9340", 10:"#ff9340",
        11:"#2c4fd0", 12:"#f2c81a", 13:"#d93a2b",
    });
    const aisClass = value => Number.isInteger(value) && value >= 0 && value <= 13 ? value : 1;
    const classColorExpression = ["match", ["get", "shipclass"],
        ...Object.entries(AIS_CLASS_COLORS).flatMap(([key, value]) => [Number(key), value]),
        AIS_CLASS_COLORS[1]];
    function hullGeometry(ship) {
        if (!ship.hull_available || !Number.isFinite(ship.hull_heading)) return null;
        const bow = ship.to_bow, stern = ship.to_stern;
        const port = ship.to_port, starboard = ship.to_starboard;
        if (![bow, stern, port, starboard, ship.lon, ship.lat].every(Number.isFinite)) return null;
        const length = bow + stern, beam = port + starboard;
        if (bow <= 0 || stern < 0 || port < 0 || starboard < 0
                || length < 30 || length > 450 || beam < 2 || beam > 90
                || Math.abs(ship.lat) > 85) return null;

        const heading = ship.hull_heading * Math.PI / 180;
        const cos = Math.cos(heading), sin = Math.sin(heading);
        const metresPerLon = 111320 * Math.cos(ship.lat * Math.PI / 180);
        const metresPerLat = 111320;
        const at = (forward, right) => {
            const east = forward * sin + right * cos;
            const north = forward * cos - right * sin;
            return [ship.lon + east / metresPerLon, ship.lat + north / metresPerLat];
        };
        // Squared-off stern; pointed bow. Enough vertices to keep the shape
        // legible in a tilted MapLibre view and cheap for a thousand ships.
        const shoulder = bow - 0.3 * length;
        const midpoint = (starboard - port) / 2;
        const pts = [
            at(-stern, -port), at(-stern, starboard),
            at(shoulder, starboard),
            at(shoulder + (bow - shoulder) * 0.55, starboard * 0.7 + midpoint * 0.3),
            at(bow, midpoint),
            at(shoulder + (bow - shoulder) * 0.55, -port * 0.7 + midpoint * 0.3),
            at(shoulder, -port),
        ];
        pts.push(pts[0]);
        return {type: "Polygon", coordinates: [pts]};
    }
    function hullCollection(ships) {
        const features = [];
        for (const ship of ships) {
            const geometry = hullGeometry(ship);
            if (!geometry) continue;
            features.push({
                type: "Feature",
                geometry,
                properties: {
                    type: "ais", id: String(ship.id || ""),
                    name: String(ship.name || ship.id || ""),
                    length_m: ship.length_m,
                    shipclass: ship.shipclass,
                    validation_state: ship.validation_state || "unknown",
                    course: ship.course,
                    course_known: Number.isFinite(ship.course),
                    speed_knots: ship.speed_knots,
                    age_seconds: ship.age_seconds,
                },
            });
        }
        return {type: "FeatureCollection", features};
    }
    function hasHull(ships) {
        return ships.filter(ship => hullGeometry(ship) !== null).length;
    }
    function iconScale(length) {
        // AIS-catcher-like size bands where actual length is known.
        // If an AIS length isn't reported, keep a normal fallback silhouette.
        if (!Number.isFinite(length)) return 0.75;
        return length > 200 ? 1.1 : length >= 100 ? 0.9 : 0.75;
    }
    function trafficProperties(item) {
        const isAIS = item.type === "ais";
        const shipclass = isAIS ? aisClass(item.shipclass) : null;
        const moving = isAIS && Number.isFinite(item.course)
            && Number.isFinite(item.speed_knots) && item.speed_knots > 0.5;
        const unverified = item.validation_state === "unverified";
        const iconName = isAIS
            ? "sdrcc-ship-" + shipclass + "-" + (moving ? "moving" : "still")
                + (unverified ? "-unverified" : "")
            : "sdrcc-plane" + (Number.isFinite(item.course) ? "" : "-no-course");
        return {
            type: item.type,
            id: String(item.id || ""),
            name: String(item.name || item.id || ""),
            callsign: String(item.callsign || ""),
            icon_name: iconName,
            is_moving: moving,
            course: Number.isFinite(item.course) ? item.course : null,
            course_known: Number.isFinite(item.course),
            length_m: Number.isFinite(item.length_m) ? item.length_m : null,
            icon_scale: isAIS ? iconScale(item.length_m) : 1,
            hull_available: isAIS && hullGeometry(item) !== null,
            shipclass,
            speed_knots: item.speed_knots,
            altitude_ft: item.altitude_ft,
            age_seconds: item.age_seconds,
            validation_state: item.validation_state || "unknown",
        };
    }
    function makeGeoJson(rows) {
        return {
            type: "FeatureCollection",
            features: rows.map(item => ({
                type: "Feature",
                geometry: {type: "Point", coordinates: [item.lon, item.lat]},
                properties: trafficProperties(item),
            })),
        };
    }
    function setLayerVisibility(kind, visible) {
        if (!loaded) return;
        for (const suffix of kind === "ais" ? ["hull-fill", "hull-border", "icons", "fallback-icons", "labels"] : ["icons", "labels"]) {
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
        if (props.type === "ais" && Number(props.length_m) > 0) {
            line("Reported length: " + Number(props.length_m).toLocaleString() + " m");
        }
        line(props.course_known ? "Reported course/track: " + props.course + "°" : "Course/track not reported (?)");
        if (props.speed_knots !== null && props.speed_knots !== undefined) line("Speed: " + props.speed_knots + " kn");
        if (props.type === "adsb" && props.altitude_ft !== null && props.altitude_ft !== undefined) {
            line("Reported altitude: " + Number(props.altitude_ft).toLocaleString() + " ft");
        }
        if (props.age_seconds !== null && props.age_seconds !== undefined) line("Last position: " + props.age_seconds + " s ago");
        return box;
    }
    // Compact AIS-catcher-like arrows (under way) or dots (stopped/no course).
    // Colours are the actual AIS ship classes; no cyan cartoon hull overlays.
    function spriteShip(color, moving, unverified) {
        const canvas = document.createElement("canvas");
        canvas.width = 96;
        canvas.height = 96;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas 2D context is unavailable");
        ctx.scale(2, 2);
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.shadowColor = "rgba(0, 10, 24, 0.55)";
        ctx.shadowBlur = 2.2;
        ctx.fillStyle = color;
        ctx.strokeStyle = unverified ? "#ffae75" : "#091b2a";
        ctx.lineWidth = unverified ? 3 : 2;
        ctx.beginPath();
        if (moving) {
            // Heading zero is north; a slender, unambiguous direction arrow.
            ctx.moveTo(24, 9);
            ctx.lineTo(32.5, 32);
            ctx.lineTo(24, 27);
            ctx.lineTo(15.5, 32);
        } else {
            ctx.arc(24, 24, 5.3, 0, Math.PI * 2);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        return ctx.getImageData(0, 0, 96, 96);
    }
    function spritePlane(unknownCourse = false) {
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
        ctx.fillStyle = "#ffbd73";
        ctx.strokeStyle = "#07243a";
        ctx.lineWidth = 2.4;
        ctx.beginPath();
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
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.shadowColor = "transparent";
        ctx.strokeStyle = "rgba(255,255,255,0.94)";
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(24, 9);
        ctx.lineTo(24, 31);
        ctx.stroke();
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
        for (const [key, color] of Object.entries(AIS_CLASS_COLORS)) {
            for (const moving of [true, false]) {
                for (const unverified of [false, true]) {
                    const name = "sdrcc-ship-" + key + "-" + (moving ? "moving" : "still")
                        + (unverified ? "-unverified" : "");
                    map.addImage(name, spriteShip(color, moving, unverified), {pixelRatio: 2});
                }
            }
        }
        map.addImage("sdrcc-plane", spritePlane(), {pixelRatio: 2});
        map.addImage("sdrcc-plane-no-course", spritePlane(true), {pixelRatio: 2});
    }
    function addHullLayer() {
        map.addSource("sdrcc-ais-hulls", {type:"geojson", data:empty});
        map.addLayer({
            id:"sdrcc-ais-hull-fill", type:"fill", source:"sdrcc-ais-hulls",
            minzoom:HULL_MIN_ZOOM,
            paint:{
                // Dark hull shape; unverified AIS has a warm dark tint.
                "fill-color":["case",
                    ["==", ["get", "validation_state"], "unverified"], "#532e2a",
                    "#101927"],
                "fill-opacity":0.93,
            },
        });
        map.addLayer({
            id:"sdrcc-ais-hull-border", type:"line", source:"sdrcc-ais-hulls",
            minzoom:HULL_MIN_ZOOM,
            paint:{
                "line-color": ["case",
                    ["==", ["get", "validation_state"], "unverified"], "#ffae75",
                    classColorExpression],
                "line-width":["interpolate", ["linear"], ["zoom"], 14, 1.2, 17, 2],
                "line-opacity":0.95,
            },
        });
        map.on("click", "sdrcc-ais-hull-fill", event => {
            const feature=event.features && event.features[0];
            if (!feature) return;
            const ring=feature.geometry && feature.geometry.coordinates?.[0];
            const center=ring && ring[0];
            if (!center) return;
            new maplibregl.Popup({offset:12, maxWidth:"300px"})
                .setLngLat(center).setDOMContent(popup(feature)).addTo(map);
        });
        map.on("mouseenter", "sdrcc-ais-hull-fill", () => {map.getCanvas().style.cursor="pointer";});
        map.on("mouseleave", "sdrcc-ais-hull-fill", () => {map.getCanvas().style.cursor="";});
    }
    function addPoints(kind) {
        const source = "sdrcc-" + kind;
        map.addSource(source, {type: "geojson", data: empty});
        const iconLayout = {
            "icon-image": ["get", "icon_name"],
            "icon-size": ["interpolate", ["linear"], ["zoom"],
                7, ["*", 0.36, ["get", "icon_scale"]],
                10, ["*", 0.53, ["get", "icon_scale"]],
                13, ["*", 0.76, ["get", "icon_scale"]],
                16, ["*", 0.91, ["get", "icon_scale"]]],
            "icon-rotate": kind === "ais"
                ? ["case", ["get", "is_moving"], ["coalesce", ["get", "course"], 0], 0]
                : ["coalesce", ["get", "course"], 0],
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "viewport",
            "icon-allow-overlap": true,
            "icon-ignore-placement": true,
        };
        const iconLayer = {
            id: source + "-icons", type: "symbol", source,
            layout: iconLayout,
        };
        if (kind === "ais") iconLayer.maxzoom = HULL_MIN_ZOOM;
        map.addLayer(iconLayer);
        if (kind === "ais") {
            // MapLibre's native zoom ranges guarantee no icon/hull overlap:
            // at harbour zoom only missing/short hulls get a fallback symbol.
            map.addLayer({
                id: source + "-fallback-icons", type: "symbol", source,
                minzoom: HULL_MIN_ZOOM,
                filter: ["!=", ["get", "hull_available"], true],
                layout: {...iconLayout},
            });
        }
        map.addLayer({
            id: source + "-labels", type: "symbol", source,
            minzoom: kind === "ais" ? AIS_NAME_MIN_ZOOM : 11,
            layout: {
                "text-field": ["get", "name"],
                "text-size": ["interpolate", ["linear"], ["zoom"], 12, 10, 16, 12],
                "text-offset": [0, 0.95],
                "text-anchor": "top",
                "text-optional": true,
                "text-allow-overlap": false,
                "text-ignore-placement": false,
            },
            paint: {
                "text-color": kind === "ais" ? classColorExpression : "#f4faff",
                "text-halo-color": "#102436",
                "text-halo-width": kind === "ais" ? 2 : 1.4,
            },
        });
        const interactive = kind === "ais"
            ? [source + "-icons", source + "-fallback-icons"]
            : [source + "-icons"];
        for (const id of interactive) {
            map.on("click", id, event => {
                const feature = event.features && event.features[0];
                if (!feature) return;
                new maplibregl.Popup({offset: 12, maxWidth: "300px"})
                    .setLngLat(feature.geometry.coordinates)
                    .setDOMContent(popup(feature))
                    .addTo(map);
            });
            map.on("mouseenter", id, () => {map.getCanvas().style.cursor = "pointer";});
            map.on("mouseleave", id, () => {map.getCanvas().style.cursor = "";});
        }
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
                + ` · ${hasHull(ships)} scaled hulls`
                + (unverified ? ` (orange: ${unverified} unverified)` : "")
                + ` · ADS-B: ${planes.length} plotted from ${adsbTotal} records`;
            el("feed-status").textContent =
                "AIS " + (data.ais?.available ? "LIVE" : "UNAVAILABLE")
                + " · ADS-B " + (data.adsb?.available ? "LIVE" : "UNAVAILABLE")
                + " · Updated " + new Date().toLocaleTimeString();
            if (loaded) {
                map.getSource("sdrcc-ais").setData(makeGeoJson(ships));
                map.getSource("sdrcc-ais-hulls").setData(hullCollection(ships));
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
        addHullLayer();
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
