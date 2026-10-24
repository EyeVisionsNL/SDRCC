/* SDRCC Map Lab: completely read-only experimental ADS-B/AIS viewer. */
(async () => {
    "use strict";
    const el = id => document.getElementById(id);
    // Preserve the selected AIS track window independently of the legend.
    const trackMinutesKey = "sdrcc.mapLab.trackMinutes";
    let trackMinutes = 15;
    try {
        const stored = Number(window.localStorage.getItem(trackMinutesKey));
        if (Number.isInteger(stored) && stored >= 1 && stored <= 60)
            trackMinutes = stored;
    } catch (_) { /* Local storage is optional. */ }
    el("track-duration").value = String(trackMinutes);
    el("track-duration-value").textContent = trackMinutes + " min";
    // Match the existing collapsible Rijnmond VTS legend behaviour:
    // a small default-closed panel that remembers the user's preference.
    const legend = el("map-lab-legend");
    const legendKey = "sdrcc.mapLab.legendOpen";
    if (legend) {
        try { legend.open = window.localStorage.getItem(legendKey) === "1"; }
        catch (_) { /* Storage is optional, so the map stays available. */ }
        legend.addEventListener("toggle", () => {
            try { window.localStorage.setItem(legendKey, legend.open ? "1" : "0"); }
            catch (_) { /* Browser storage may be disabled. */ }
        });
    }
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
    let overlayBusy = false;
    let latestShips = [];
    let emergencyTargets = [];
    let atisTarget = null;
    let previouslyDrawnEmergency = 0;
    let previouslyDrawnAtis = 0;
    let trackRequestSequence = 0;
    let lastTrackFetchAt = 0;
    let trackLoading = false;
    let trackRefreshPending = false;

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
    const AIS_CLASS_NAMES = Object.freeze({
        0:"Other", 1:"Unknown", 2:"Cargo", 3:"Class B", 4:"Passenger",
        5:"Special", 6:"Tanker", 7:"High speed", 8:"Fishing",
        9:"Aircraft", 10:"Helicopter", 11:"Station", 12:"Aid to navigation",
        13:"Search and rescue",
    });
    function hullGeometry(ship) {
        if (ship.is_offshore_structure ||
                ["offshore_wtg", "offshore_platform"].includes(ship.render_profile)) return null;
        if (!ship.hull_available || !Number.isFinite(ship.hull_heading)) return null;
        const bow = ship.to_bow, stern = ship.to_stern;
        const port = ship.to_port, starboard = ship.to_starboard;
        if (![bow, stern, port, starboard, ship.lon, ship.lat].every(Number.isFinite)) return null;
        const length = bow + stern, beam = port + starboard;
        if (bow <= 0 || stern < 0 || port < 0 || starboard < 0
                || length < 5 || length > 450 || beam < 2 || beam > 90
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
                    render_profile: ship.render_profile || "vessel",
                    hull_available: true,
                    hull_geometry_source: ship.hull_geometry_source || "",
                    hull_bearing_approximate: ship.hull_bearing_approximate === true,
                    validation_state: ship.validation_state || "unknown",
                    position_stale: ship.position_stale === true,
                    course: ship.course,
                    course_known: Number.isFinite(ship.course),
                    speed_knots: ship.speed_knots,
                    age_seconds: ship.age_seconds,
                    imo: ship.imo, eni: ship.eni, callsign: ship.callsign,
                    destination: ship.destination, country: ship.country,
                    nav_status: ship.nav_status, shiptype: ship.shiptype,
                    beam_m: ship.beam_m, draught_m: ship.draught_m,
                    heading: ship.heading,
                    display_height_m: ["watertaxi","krve"].includes(ship.render_profile)
                        ? Math.min(1.8, Math.max(.9,
                            (Number(ship.to_port) + Number(ship.to_starboard)) * .45))
                        : Math.min(9, Math.max(2.5,
                            (Number(ship.to_port) + Number(ship.to_starboard)) * 0.38)),
                },
            });
        }
        return {type: "FeatureCollection", features};
    }
    function deckCollection(ships, hulls) {
        // Native MapLibre prisms: illustration only, not measured AIS equipment.
        const features = [];
        const detailsById = new Map(hulls.features.map(f => [f.properties.id, f.properties]));
        for (const ship of ships) {
            const profile = ship.render_profile;
            if (!["tanker", "cargo", "tug", "police", "watertaxi", "krve", "port_authority", "vessel"].includes(profile)) continue;
            const info = detailsById.get(String(ship.id));
            if (!info) continue;
            const {to_bow:bow, to_stern:stern, to_port:port,
                to_starboard:starboard, lon, lat, hull_heading:headingDeg} = ship;
            if (![bow,stern,port,starboard,lon,lat,headingDeg].every(Number.isFinite)
                    || Math.abs(lat) > 85) continue;
            const length = bow+stern, beam = port+starboard;
            if (length < 5 || beam < 2) continue;
            const heading = headingDeg * Math.PI / 180;
            const cos = Math.cos(heading), sin = Math.sin(heading);
            const metresPerLon = 111320 * Math.cos(lat * Math.PI / 180);
            const at = (forward,right) => [
                lon+(forward*sin+right*cos)/metresPerLon,
                lat+(forward*cos-right*sin)/111320,
            ];
            const add = (a,b,left,right,part,above,baseOffset=0) => {
                if (a>=b || left>=right) return;
                const ring = [at(a,left),at(a,right),at(b,right),at(b,left)];
                ring.push(ring[0]);
                features.push({type:"Feature",
                    geometry:{type:"Polygon",coordinates:[ring]},
                    properties:{...info,part,
                        base_height_m:info.display_height_m+baseOffset,
                        top_height_m:info.display_height_m+baseOffset+above,
                        center_lon:lon,center_lat:lat}});
            };
            if (profile === "vessel") {
                // Distinct but low-cost illustrations for the remaining AIS
                // classes; no class gets stranded as a flat pointer at 3D zoom.
                const cls=ship.shipclass;
                if (cls === 4) {
                    add(-stern+length*.2,-stern+length*.78,
                        -port*.70,starboard*.70,"passenger-cabin",3.5);
                    add(-stern+length*.23,-stern+length*.75,
                        -port*.72,starboard*.72,"passenger-roof",.4,3.5);
                } else if (cls === 8) {
                    add(-stern+length*.42,-stern+length*.73,
                        -port*.67,starboard*.67,"fishing-wheelhouse",2.8);
                    add(-stern+length*.12,-stern+length*.28,
                        -port*.30,starboard*.30,"fishing-gear",.8);
                } else if (cls === 7) {
                    add(-stern+length*.26,-stern+length*.72,
                        -port*.64,starboard*.64,"fast-cabin",2);
                    add(-stern+length*.30,-stern+length*.67,
                        -port*.68,starboard*.68,"fast-roof",.2,2);
                } else {
                    add(-stern+length*.31,-stern+length*.64,
                        -port*.68,starboard*.68,"general-cabin",2.3);
                    add(-stern+length*.34,-stern+length*.61,
                        -port*.70,starboard*.70,"general-roof",.25,2.3);
                }
                continue;
            }
            if (profile === "krve") {
                // Illustrative KRVE RIB/roeiersvlet: dark hull, thick yellow
                // rubbing fenders and pale enclosed wheelhouse with amber roof.
                // All pieces scale with real AIS antenna offsets.
                const from=-stern+length*.30, to=-stern+length*.71;
                add(-stern+length*.06,-stern+length*.30,
                    -port*.66,starboard*.66,"krve-workdeck",.16);
                add(from,to,-port*.66,starboard*.66,"krve-cabin",1.75);
                add(from+length*.025,to-length*.025,
                    -port*.7,starboard*.7,"krve-roof",.2,1.75);
                for (const side of [-1,1]) {
                    const near=side<0 ? -port*.98 : starboard*.77;
                    const far=side<0 ? -port*.77 : starboard*.98;
                    add(-stern+length*.07,-stern+length*.88,
                        near,far,"krve-fender",.48);
                    const glassNear=side<0 ? -port*.69 : starboard*.59;
                    const glassFar=side<0 ? -port*.59 : starboard*.69;
                    add(from+length*.045,to-length*.045,
                        glassNear,glassFar,"krve-windows",.48,.66);
                }
                add(-stern+length*.16,-stern+length*.24,
                    -port*.23,starboard*.23,"krve-mooring-gear",.28);
                continue;
            }
            if (profile === "watertaxi") {
                // Black fast boat with a low cabin, yellow roof and twin yellow rails.
                const from=-stern+length*.29, to=-stern+length*.68;
                add(from,to,-port*.67,starboard*.67,"watertaxi-cabin",1.55);
                add(from+length*.025,to-length*.025,
                    -port*.71,starboard*.71,"watertaxi-roof",.22,1.55);
                add(-stern+length*.14,-stern+length*.82,
                    -port*.94,-port*.78,"watertaxi-stripe",.23);
                add(-stern+length*.14,-stern+length*.82,
                    starboard*.78,starboard*.94,"watertaxi-stripe",.23);
                add(from+length*.04,to-length*.04,
                    -port*.73,-port*.65,"watertaxi-window",.4,.66);
                add(from+length*.04,to-length*.04,
                    starboard*.65,starboard*.73,"watertaxi-window",.4,.66);
                continue;
            }
            if (profile === "tug") {
                // Wheelhouse toward the bow, compact towing winch on the afterdeck.
                add(-stern+length*.37,-stern+length*.70,
                    -port*.67,starboard*.67,"tug-wheelhouse",4.8);
                add(-stern+length*.12,-stern+length*.28,
                    -port*.4,starboard*.4,"tug-winch",1.65);
                continue;
            }
            if (profile === "port_authority") {
                // Port of Rotterdam blue/yellow inspection and fire/rescue craft.
                // 3D geometry illustrates its appearance, not AIS deck measurements.
                const from=-stern+length*.28, to=-stern+length*.66;
                add(from,to,-port*.70,starboard*.70,"rpa-cabin",3.2);
                add(from+length*.02,to-length*.02,
                    -port*.72,starboard*.72,"rpa-roof",.25,3.2);
                for(const side of [-1,1]){
                    const stripeNear=side<0?-port*.96:starboard*.82;
                    const stripeFar=side<0?-port*.82:starboard*.96;
                    add(-stern+length*.1,-stern+length*.88,
                        stripeNear,stripeFar,"rpa-yellow-stripe",.48);
                    const glassNear=side<0?-port*.74:starboard*.62;
                    const glassFar=side<0?-port*.62:starboard*.74;
                    add(from+length*.03,to-length*.03,
                        glassNear,glassFar,"rpa-windows",.55,.65);
                }
                add(from+length*.23,from+length*.31,
                    -port*.19,starboard*.19,"rpa-fire-monitor",.9,3.2);
                continue;
            }
            if (profile === "police") {
                // Distinct compact blue/white patrol boat: cabin, blue side deck
                // accent and a small illustrative beacon on its wheelhouse.
                add(-stern+length*.29,-stern+length*.66,
                    -port*.76,starboard*.76,"police-cabin",3.7);
                add(-stern+length*.31,-stern+length*.62,
                    -port*.79,-port*.66,"police-stripe",1.15);
                add(-stern+length*.31,-stern+length*.62,
                    starboard*.66,starboard*.79,"police-stripe",1.15);
                add(-stern+length*.43,-stern+length*.50,
                    -port*.22,starboard*.22,"police-lightbar",4.5);
                continue;
            }
            add(-stern+length*.05,-stern+length*.17,
                -port*.75,starboard*.75,"bridge",4.1);
            const start=-stern+length*.24, end=-stern+length*.67;
            if (profile === "cargo") {
                // Three raised broad hatch covers, with narrow gaps.
                for(let n=0;n<3;n++){
                    add(start+(end-start)*(n/3+.025),
                        start+(end-start)*((n+1)/3-.025),
                        -port*.72,starboard*.72,"cargo-hatch",.9);
                }
            } else {
                // Distinct tanker piping and transverse tank hatch features.
                for(const offset of [-.26,0,.26]){
                    const centre=offset*beam, half=Math.min(.7,beam*.07);
                    add(start,end,centre-half,centre+half,"tanker-pipe",1.2);
                }
                for(let n=1;n<=3;n++){
                    const middle=start+(end-start)*n/4;
                    add(middle-length*.012,middle+length*.012,
                        -port*.68,starboard*.68,"tanker-cap",.55);
                }
            }
        }
        return {type:"FeatureCollection",features};
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
        const profile = isAIS ? (item.render_profile || "vessel") : "";
        const offshore = ["offshore_wtg","offshore_platform"].includes(profile);
        const iconName = isAIS
            ? offshore
                ? "sdrcc-" + profile.replace("_","-")
                    + (unverified ? "-unverified" : "")
                : "sdrcc-ship-" + shipclass + "-" + (moving ? "moving" : "still")
                    + (unverified ? "-unverified" : "")
            : "sdrcc-plane" + (Number.isFinite(item.course) ? "" : "-no-course");
        return {
            type: item.type,
            id: String(item.id || ""),
            name: String(item.name || item.id || ""),
            label_name: String(item.name || item.id || "").slice(0, 20),
            callsign: String(item.callsign || ""),
            registration: item.registration || "",
            aircraft_type: item.aircraft_type || "",
            description: item.description || "",
            operator: item.operator || "",
            squawk: item.squawk || "",
            category: item.category || "",
            baro_rate: item.baro_rate,
            destination: item.destination || "",
            country: item.country || "",
            nav_status: item.nav_status || "",
            shiptype: item.shiptype,
            imo: item.imo || "",
            eni: item.eni || "",
            beam_m: item.beam_m,
            draught_m: item.draught_m,
            heading: item.heading,
            hull_geometry_source: item.hull_geometry_source || "",
            hull_bearing_approximate: item.hull_bearing_approximate === true,
            icon_name: iconName,
            render_profile: profile,
            is_offshore_structure: offshore,
            is_moving: moving,
            course: Number.isFinite(item.course) ? item.course : null,
            course_known: Number.isFinite(item.course),
            length_m: Number.isFinite(item.length_m) ? item.length_m : null,
            // Enlarge turbines ~2x at every map zoom without changing ship sizes.
            icon_scale: isAIS
                ? (profile === "offshore_wtg" ? 0.78
                    : profile === "offshore_platform" ? 0.9
                    : iconScale(item.length_m))
                : 1,
            hull_available: isAIS && !offshore && hullGeometry(item) !== null,
            shipclass,
            speed_knots: item.speed_knots,
            altitude_ft: item.altitude_ft,
            age_seconds: item.age_seconds,
            position_stale: item.position_stale === true,
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
    function setTrackVisibility() {
        if (!loaded || !map.getLayer("sdrcc-ais-track")) return;
        const show = el("layer-ais").checked && el("layer-tracks").checked;
        map.setLayoutProperty("sdrcc-ais-track", "visibility", show ? "visible" : "none");
    }
    async function loadAllTracks() {
        if (trackLoading) {
            trackRefreshPending = true;
            return;
        }
        if (!loaded || !el("layer-tracks").checked || !el("layer-ais").checked
                || document.hidden) return;
        const request = ++trackRequestSequence;
        trackLoading = true;
        lastTrackFetchAt = Date.now();
        el("track-status").textContent = "Loading tracks…";
        try {
            const response = await fetch("/api/map-lab/ais-tracks?minutes=" + trackMinutes,
                {cache:"no-store"});
            if (!response.ok) throw new Error("Track HTTP " + response.status);
            const data = await response.json();
            if (request !== trackRequestSequence || !el("layer-tracks").checked
                    || !el("layer-ais").checked) return;
            const tracks = data.geojson?.type === "FeatureCollection"
                && Array.isArray(data.geojson.features) ? data.geojson.features : [];
            map.getSource("sdrcc-ais-track").setData({
                type:"FeatureCollection", features:tracks,
            });
            const count = Number.isInteger(data.track_count) ? data.track_count : 0;
            el("track-status").textContent = !data.available
                ? "AIS-Catcher tracks unavailable"
                : count ? count + " vessel tracks" : "No recent tracks";
        } catch (_) {
            if (request === trackRequestSequence)
                el("track-status").textContent = "Tracks temporarily unavailable";
        } finally {
            trackLoading = false;
            if (trackRefreshPending) {
                trackRefreshPending = false;
                if (el("layer-tracks").checked && el("layer-ais").checked)
                    void loadAllTracks();
            }
        }
    }
    function addTrackLayer() {
        map.addSource("sdrcc-ais-track", {type:"geojson",data:empty});
        map.addLayer({
            id:"sdrcc-ais-track", type:"line", source:"sdrcc-ais-track",
            layout:{visibility:"none","line-cap":"round","line-join":"round"},
            paint:{"line-color":classColorExpression, "line-width":1.7,
                "line-opacity":.7},
        });
    }
    function setLayerVisibility(kind, visible) {
        if (!loaded) return;
        for (const suffix of kind === "ais"
                ? ["hull-fill", "hull-border", "hull-3d", "hull-decks", "icons", "fallback-icons", "labels"]
                : ["icons", "labels"]) {
            const id = "sdrcc-" + kind + "-" + suffix;
            const hull2d = suffix === "hull-fill" || suffix === "hull-border";
            const enabled = visible
                && (suffix !== "labels" || el("show-names").checked)
                && (!hull2d || !mode3d)
                && (!["hull-3d","hull-decks"].includes(suffix) || mode3d);
            if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", enabled ? "visible" : "none");
        }
        if (kind === "ais") setTrackVisibility();
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
        setLayerVisibility("ais", el("layer-ais").checked);
    }
    function popup(feature) {
        const props = feature.properties || {};
        const box = document.createElement("div");
        box.className = "traffic-detail";
        const title = document.createElement("div");
        title.className = "popup-title";
        title.textContent = (props.type === "ais" ? "🚢 " : "✈ ") + (props.name || props.id);
        box.appendChild(title);
        const add = (label, value, suffix = "") => {
            if (value === null || value === undefined || value === "") return;
            const row = document.createElement("div");
            row.className = "popup-line";
            const caption = document.createElement("strong");
            caption.textContent = label + ": ";
            row.appendChild(caption);
            const data = document.createElement("span");
            data.textContent = String(value) + suffix;
            row.appendChild(data);
            box.appendChild(row);
        };
        if (props.type === "ais") {
            add("MMSI", props.id);
            const activeEmergency = emergencyTargets.find(item =>
                item.mmsi === String(props.id) && item.expiresAt > Date.now());
            if (activeEmergency) add("Emergency vessel",
                activeEmergency.category === "knrm" ? "KNRM" : "Water police");
            if (atisTarget?.mmsi === String(props.id)
                    && atisTarget.expiresAt > Date.now()) {
                add("Matched Marine ATIS", atisTarget.atis_code);
            }
            if (Number.isFinite(props.age_seconds)) {
                const ageText = props.age_seconds >= 60
                    ? Math.floor(props.age_seconds / 60) + " min ago"
                    : Math.round(props.age_seconds) + " s ago";
                add("Last AIS signal", ageText);
            }
            if (props.position_stale) add("AIS position", "Historical (older than 30 min)");
            if (props.hull_geometry_source) {
                add("3D hull", props.hull_geometry_source === "AIS dimensions"
                    ? "Real AIS dimensions" : props.hull_geometry_source);
            } else if (!props.is_offshore_structure && props.hull_available === false) {
                add("3D hull", "Unavailable: fixed AIS object or invalid position");
            }
            if (props.render_profile === "offshore_wtg") add("Structure", "Wind turbine (name-based)");
            else if (props.render_profile === "offshore_platform") add("Structure", "Offshore platform (name-based)");
            else if (props.render_profile === "tanker") add("3D deck", "Tanker pipes (illustrative)");
            else if (props.render_profile === "cargo") add("3D deck", "Cargo hatches (illustrative)");
            else if (props.render_profile === "tug") add("3D deck", "Tug wheelhouse / towing winch (illustrative)");
            else if (props.render_profile === "police") add("3D deck", "Police patrol cabin / blue markings (illustrative)");
            else if (props.render_profile === "watertaxi") add("3D deck", "Black/yellow MSTX fast water taxi (illustrative)");
            else if (props.render_profile === "krve") add("3D deck", "KRVE mooring / pilot-transport craft (illustrative)");
            else if (props.render_profile === "port_authority") add("3D deck", "Rotterdam Port Authority patrol / rescue boat (illustrative)");
            if (props.hull_bearing_approximate) add("3D orientation",
                Number.isFinite(props.course) && Number.isFinite(props.speed_knots)
                    && props.speed_knots > .5
                    ? "Based on AIS course; not necessarily true heading"
                    : "North-up illustration; true heading not reported");
            add("Class", AIS_CLASS_NAMES[props.shipclass] || "Unknown");
            add("Ship type", props.shiptype);
            add("Callsign", props.callsign);
            add("IMO", props.imo);
            add("ENI", props.eni);
            add("Country", props.country);
            add("Destination", props.destination);
            add("Navigation status", props.nav_status);
            add("Length", props.length_m, " m");
            add("Beam", props.beam_m, " m");
            add("Draught", props.draught_m, " m");
            add("Heading", props.heading, "°");
            if (props.validation_state === "unverified") add("AIS", "Position unverified");
        } else {
            add("ICAO24", props.id?.toUpperCase());
            add("Registration", props.registration);
            add("Type", props.aircraft_type);
            add("Aircraft", props.description);
            add("Operator", props.operator);
            add("Squawk", props.squawk);
            add("Category", props.category);
            add("Vertical rate", props.baro_rate, " ft/min");
            add("Altitude", props.altitude_ft, " ft");
        }
        add("Course/track", props.course_known ? props.course : "Not reported",
            props.course_known ? "°" : "");
        add("Ground speed", props.speed_knots, " kn");
        add("Last position", props.age_seconds, " s ago");
        if (props.type === "adsb" && /^[a-f0-9]{6}$/i.test(props.id || "")) {
            const photo = document.createElement("div");
            photo.className = "popup-photo";
            photo.textContent = "Checking for a credited aircraft photo…";
            box.appendChild(photo);
            // The server only asks Planespotters for photos when a plane is clicked.
            void fetch("/api/map-lab/aircraft-photo/" + encodeURIComponent(props.id))
                .then(response => response.ok ? response.json() : null)
                .then(result => {
                    photo.textContent = "";
                    if (!result || !result.ok || !result.image_url) {
                        photo.textContent = "No aircraft photo available";
                        return;
                    }
                    const img = document.createElement("img");
                    img.src = result.image_url;
                    img.alt = "Aircraft photograph";
                    img.loading = "lazy";
                    img.referrerPolicy = "no-referrer";
                    img.onerror = () => {img.remove(); photo.textContent = "Aircraft photo unavailable";};
                    photo.appendChild(img);
                    const credit = document.createElement(result.source_url ? "a" : "div");
                    credit.textContent = "Photo: " + (result.photographer || result.source);
                    if (result.source_url) {
                        credit.href = result.source_url;
                        credit.target = "_blank";
                        credit.rel = "noopener noreferrer";
                    }
                    photo.appendChild(credit);
                })
                .catch(() => {photo.textContent = "Aircraft photo unavailable";});
        }
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
    function spriteOffshore(profile,unverified) {
        // Upright fixed-installation symbols, not ship arrows.
        const canvas=document.createElement("canvas");
        canvas.width=96;canvas.height=96;
        const ctx=canvas.getContext("2d");
        if(!ctx)throw new Error("Canvas 2D context is unavailable");
        ctx.scale(2,2);
        ctx.lineJoin="round";ctx.lineCap="round";
        ctx.shadowColor="rgba(0,10,24,.6)";ctx.shadowBlur=2;
        ctx.strokeStyle=unverified?"#ffae75":"#0a2739";
        ctx.lineWidth=unverified?2.8:1.8;
        if(profile==="offshore_wtg"){
            ctx.fillStyle="#8ee9f9";
            ctx.fillRect(22.5,22,3,17);
            ctx.beginPath();ctx.arc(24,20,3.5,0,Math.PI*2);ctx.fill();ctx.stroke();
            for(let i=0;i<3;i++){
                const a=-Math.PI/2+i*2*Math.PI/3;
                const tip=[24+17*Math.cos(a),20+17*Math.sin(a)];
                const left=[24+3*Math.cos(a+1.05),20+3*Math.sin(a+1.05)];
                const right=[24+3*Math.cos(a-1.05),20+3*Math.sin(a-1.05)];
                ctx.beginPath();ctx.moveTo(left[0],left[1]);ctx.lineTo(tip[0],tip[1]);
                ctx.lineTo(right[0],right[1]);ctx.closePath();ctx.fill();ctx.stroke();
            }
            ctx.beginPath();ctx.moveTo(16,39);ctx.lineTo(32,39);ctx.stroke();
        }else{
            ctx.fillStyle="#f0c27c";
            ctx.fillRect(9,23,30,6);
            ctx.fillRect(12,29,3,12);ctx.fillRect(33,29,3,12);
            ctx.beginPath();ctx.moveTo(24,5);ctx.lineTo(17,23);
            ctx.lineTo(31,23);ctx.closePath();ctx.fill();ctx.stroke();
            ctx.beginPath();ctx.moveTo(24,5);ctx.lineTo(24,23);ctx.stroke();
            ctx.beginPath();ctx.moveTo(18,16);ctx.lineTo(30,16);ctx.stroke();
            ctx.beginPath();ctx.moveTo(13,35);ctx.lineTo(35,35);ctx.stroke();
        }
        return ctx.getImageData(0,0,96,96);
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
    function labelPlate(color) {
        // Compact borderless class-coloured AIS label; nine-slice fits text.
        const canvas = document.createElement("canvas");
        canvas.width = 96; canvas.height = 48;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas 2D context is unavailable");
        ctx.scale(2, 2);
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, 48, 24);
        return ctx.getImageData(0, 0, 96, 48);
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
        for (const [key, color] of Object.entries(AIS_CLASS_COLORS)) {
            map.addImage("sdrcc-name-" + key, labelPlate(color), {
                pixelRatio: 2,
                stretchX: [[18, 78]], stretchY: [[16, 32]],
                content: [12, 8, 84, 40],
            });
        }
        for(const profile of ["offshore_wtg","offshore_platform"]){
            for(const unverified of [false,true]){
                const name="sdrcc-"+profile.replace("_","-")
                    +(unverified?"-unverified":"");
                map.addImage(name,spriteOffshore(profile,unverified),{pixelRatio:2});
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
                "fill-opacity":["case", ["get", "position_stale"], 0.65, 0.93],
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
                "line-opacity":["case", ["get", "position_stale"], 0.65, 0.95],
            },
        });
        map.addLayer({
            id: "sdrcc-ais-hull-3d", type: "fill-extrusion",
            source: "sdrcc-ais-hulls", minzoom: HULL_MIN_ZOOM,
            layout: {visibility: "none"},
            paint: {
                "fill-extrusion-color": ["case",
                    ["==", ["get", "validation_state"], "unverified"], "#57352c",
                    ["==", ["get", "render_profile"], "police"], "#153f6b",
                    ["==", ["get", "render_profile"], "watertaxi"], "#11161c",
                    ["==", ["get", "render_profile"], "krve"], "#20272e",
                    ["==", ["get", "render_profile"], "port_authority"], "#1d4c79",
                    "#1b3243"],
                // Illustrative depth only: actual ship height is not present in AIS.
                "fill-extrusion-height": ["get", "display_height_m"],
                "fill-extrusion-base": 0,
                "fill-extrusion-opacity": 0.96,
                "fill-extrusion-vertical-gradient": true,
            },
        });
        map.addSource("sdrcc-ais-decks",{type:"geojson",data:empty});
        map.addLayer({
            id:"sdrcc-ais-hull-decks",type:"fill-extrusion",
            source:"sdrcc-ais-decks",minzoom:15,
            layout:{visibility:"none"},
            paint:{
                "fill-extrusion-color":["match",["get","part"],
                    "bridge","#c1d6df","cargo-hatch","#677e92",
                    "tanker-pipe","#91c5d0","tanker-cap","#d1d8d5",
                    "tug-wheelhouse","#dce4ed","tug-winch","#f5a46e",
                    "police-cabin","#ebf5fa","police-stripe","#1769b0",
                    "police-lightbar","#198aff",
                    "watertaxi-cabin","#161d24","watertaxi-roof","#ffd31a",
                    "watertaxi-stripe","#ffe02a","watertaxi-window","#87bdd2",
                    "krve-workdeck","#333941","krve-cabin","#e8eef1",
                    "krve-roof","#ee9c19","krve-fender","#f8bf1e",
                    "krve-windows","#38677b","krve-mooring-gear","#414953",
                    "rpa-cabin","#f4df4c","rpa-roof","#ffcc24",
                    "rpa-yellow-stripe","#f7d438","rpa-windows","#39748d",
                    "rpa-fire-monitor","#c8d5da",
                    "passenger-cabin","#d7e5ed","passenger-roof","#729fba",
                    "fishing-wheelhouse","#e3e6de","fishing-gear","#ddaa64",
                    "fast-cabin","#b3d0e1","fast-roof","#f0cf42",
                    "general-cabin","#c3d1dc","general-roof","#879ba9",
                    "#8195a8"],
                "fill-extrusion-base":["get","base_height_m"],
                "fill-extrusion-height":["get","top_height_m"],
                "fill-extrusion-opacity":.93,
                "fill-extrusion-vertical-gradient":true,
            },
        });
        for (const id of ["sdrcc-ais-hull-fill", "sdrcc-ais-hull-3d", "sdrcc-ais-hull-decks"]) {
            map.on("click", id, event => {
                const feature = event.features && event.features[0];
                if (!feature) return;
                const ring = feature.geometry && feature.geometry.coordinates?.[0];
                if (!ring?.length) return;
                const center = ring.reduce(
                    (sum, point) => [sum[0] + point[0] / ring.length,
                        sum[1] + point[1] / ring.length], [0, 0]);
                const position=Number.isFinite(feature.properties?.center_lon)
                    && Number.isFinite(feature.properties?.center_lat)
                    ? [feature.properties.center_lon,feature.properties.center_lat] : center;
                new maplibregl.Popup({offset: 12, maxWidth: "350px"})
                    .setLngLat(position).setDOMContent(popup(feature)).addTo(map);
            });
            map.on("mouseenter", id, () => {map.getCanvas().style.cursor = "pointer";});
            map.on("mouseleave", id, () => {map.getCanvas().style.cursor = "";});
        }
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
                ? ["case", ["get", "is_offshore_structure"], 0,
                    ["get", "is_moving"], ["coalesce", ["get", "course"], 0], 0]
                : ["coalesce", ["get", "course"], 0],
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "viewport",
            "icon-allow-overlap": true,
            "icon-ignore-placement": true,
        };
        const iconLayer = {
            id: source + "-icons", type: "symbol", source,
            layout: iconLayout,
            paint: {"icon-opacity": kind === "ais"
                ? ["case", ["get", "position_stale"], 0.65, 1] : 1},
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
                paint: {"icon-opacity": ["case", ["get", "position_stale"], 0.65, 1]},
            });
        }
        map.addLayer({
            id: source + "-labels", type: "symbol", source,
            minzoom: kind === "ais" ? AIS_NAME_MIN_ZOOM : 11,
            layout: {
                "text-field": kind === "ais" ? ["get", "label_name"] : ["get", "name"],
                "icon-image": kind === "ais"
                    ? ["concat", "sdrcc-name-", ["to-string", ["get", "shipclass"]]]
                    : "sdrcc-plane",
                "icon-text-fit": kind === "ais" ? "both" : "none",
                "icon-text-fit-padding": kind === "ais" ? [2, 4, 2, 4] : [0, 0, 0, 0],
                // A small plate is easier to read than a large label over the hull.
                "text-size": kind === "ais"
                    ? ["interpolate", ["linear"], ["zoom"], 12.5, 8.5, 15, 9, 18, 9.5]
                    : ["interpolate", ["linear"], ["zoom"], 11, 9, 16, 10.5],
                // MapLibre can try adjacent positions instead of covering the
                // ship's own icon/real-scale hull or hiding the vessel entirely.
                "text-variable-anchor": ["top", "bottom", "right", "left"],
                "text-justify": "auto",
                "text-radial-offset": kind === "ais"
                    ? ["interpolate", ["linear"], ["zoom"], 12.5, 1.6, 14, 2.1, 16, 3.2, 18, 5]
                    : 1.2,
                "text-optional": false,
                "text-allow-overlap": false,
                "text-ignore-placement": false,
            },
            paint: {
                "icon-opacity": kind === "ais"
                    ? ["case", ["get", "position_stale"], 0.65, 1] : 0,
                "text-opacity": kind === "ais"
                    ? ["case", ["get", "position_stale"], 0.72, 1] : 1,
                "text-color": kind === "ais"
                    ? ["match", ["get", "shipclass"],
                        0, "#072331", 1, "#072331", 2, "#0c281c",
                        7, "#17232b", 8, "#17232b", 9, "#17232b", 10, "#17232b",
                        12, "#17232b", "#ffffff"]
                    : "#ffffff",
                "text-halo-color": kind === "ais" ? "rgba(10,21,30,0.12)" : "#102436",
                "text-halo-width": kind === "ais" ? 0.4 : 1.4,
            },
        });
        const interactive = kind === "ais"
            ? [source + "-icons", source + "-fallback-icons", source + "-labels"]
            : [source + "-icons", source + "-labels"];
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
    function setAuxVisibility(kind, visible) {
        if (!loaded) return;
        const layers = kind === "station"
            ? ["sdrcc-home-ring", "sdrcc-home-dot", "sdrcc-home-name"]
            : ["sdrcc-vts-fill", "sdrcc-vts-line"];
        for (const id of layers) {
            if (map.getLayer(id)) {
                map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
            }
        }
    }
    function addSectorLayers() {
        map.addSource("sdrcc-vts", {type:"geojson", data:empty});
        map.addLayer({
            id:"sdrcc-vts-fill", type:"fill", source:"sdrcc-vts",
            paint: {
                "fill-color":["get","color"],
                "fill-opacity":0.15,
            },
        });
        map.addLayer({
            id:"sdrcc-vts-line", type:"line", source:"sdrcc-vts",
            paint: {
                "line-color":["get","color"],
                "line-width":["interpolate",["linear"],["zoom"], 9,0.65,14,1.5],
                "line-opacity":0.8,
            },
        });
        // VTS fills and borders are visual context only: never put a sector
        // name on every polygon or open a popup when clicking the water.
        // A click should select a ship/aircraft, not a covering VTS polygon.
    }
    async function loadSectors() {
        const status = el("vts-status");
        try {
            const response = await fetch("/api/map-lab/vts-sectors", {cache:"no-store"});
            if (!response.ok) throw new Error("HTTP " + response.status);
            const data = await response.json();
            const geojson = data?.geojson;
            if (!data?.available || geojson?.type !== "FeatureCollection"
                    || !Array.isArray(geojson.features)) {
                status.textContent = "VTS layer not installed";
                return;
            }
            map.getSource("sdrcc-vts").setData(geojson);
            status.textContent = geojson.features.length + " RWS sectors";
        } catch (error) {
            status.textContent = "VTS sectors unavailable";
        }
    }
    // Emergency and ATIS indicators reuse existing SDRCC observers.
    // Draw after AIS icons/hulls so 3D extrusions never hide their alert rings.
    // Transparent ring centres leave ships visible and selectable.
    function addAlertLayers() {
        map.addSource("sdrcc-emergency", {type:"geojson", data:empty});
        map.addSource("sdrcc-atis", {type:"geojson", data:empty});
        map.addLayer({
            id:"sdrcc-emergency-ring", type:"circle", source:"sdrcc-emergency",
            paint: {
                "circle-radius":13,
                "circle-color":"rgba(0,0,0,0)",
                "circle-stroke-color":["match",["get","category"],
                    "knrm","#ffffff","waterpolitie","#2499ff","#ffffff"],
                "circle-stroke-width":3.2,
                "circle-stroke-opacity":0.92,
                "circle-pitch-alignment":"viewport",
                "circle-pitch-scale":"viewport",
            },
        });
        map.addLayer({
            id:"sdrcc-atis-ring", type:"circle", source:"sdrcc-atis",
            paint: {
                "circle-radius":15,
                "circle-color":"rgba(46,216,147,0.06)",
                "circle-stroke-color":"#37e4a6",
                "circle-stroke-width":3,
                "circle-stroke-opacity":0.9,
                "circle-pitch-alignment":"viewport",
                "circle-pitch-scale":"viewport",
            },
        });
    }
    function setAlertVisibility() {
        if (!loaded) return;
        for (const [name, toggle] of [
            ["sdrcc-emergency-ring","layer-emergency"],
            ["sdrcc-atis-ring","layer-atis"],
        ]) {
            if (map.getLayer(name)) {
                map.setLayoutProperty(name, "visibility",
                    el(toggle).checked && el("layer-ais").checked ? "visible" : "none");
            }
        }
    }
    function validHighlightLocation(entry) {
        return entry && Number.isFinite(entry.latitude)
            && Number.isFinite(entry.longitude)
            && Math.abs(entry.latitude) <= 90 && Math.abs(entry.longitude) <= 180;
    }
    function tickHighlights() {
        if (!loaded) return;
        const now = Date.now();
        const emergencyActive = emergencyTargets.some(row => now < row.expiresAt);
        const atisActive = atisTarget && now < atisTarget.expiresAt;
        // Avoid re-uploading empty GeoJSON or repainting an idle map every 650 ms.
        if (!emergencyActive && !atisActive
                && !previouslyDrawnEmergency && !previouslyDrawnAtis) {
            el("emergency-status").textContent = "None active";
            el("atis-status").textContent = "No active match";
            return;
        }
        const shipsByMmsi = new Map(latestShips.map(ship => [String(ship.id), ship]));
        const points = (rows, category) => rows.filter(row => now < row.expiresAt)
            .filter(row => /^\d{9}$/.test(row.mmsi))
            .map(row => {
                const ship = shipsByMmsi.get(row.mmsi);
                // Follow received AIS positions, never pan or re-center the map.
                const latitude = ship?.lat ?? row.latitude;
                const longitude = ship?.lon ?? row.longitude;
                return {type:"Feature", geometry:{
                    type:"Point", coordinates:[longitude, latitude],
                }, properties:{mmsi:row.mmsi, category:row.category || category}};
            });
        const emergencies = points(emergencyTargets, "emergency");
        const atis = points(atisTarget ? [atisTarget] : [], "atis");
        previouslyDrawnEmergency = emergencies.length;
        previouslyDrawnAtis = atis.length;
        map.getSource("sdrcc-emergency").setData({type:"FeatureCollection",features:emergencies});
        map.getSource("sdrcc-atis").setData({type:"FeatureCollection",features:atis});
        el("emergency-status").textContent = emergencies.length
            ? emergencies.length + " highlighted" : "None active";
        el("atis-status").textContent = atis.length
            ? "ATIS matched" : "No active match";
        // Subtle pulse, matching AIS-Catcher emergency and ATIS colours.
        const phase = (Math.sin(now / 1350 * Math.PI * 2) + 1) / 2;
        if (emergencies.length && el("layer-emergency").checked) {
            map.setPaintProperty("sdrcc-emergency-ring","circle-radius", 11 + phase * 6);
        }
        if (atis.length && el("layer-atis").checked) {
            map.setPaintProperty("sdrcc-atis-ring","circle-radius", 12 + phase * 6);
        }
    }
    async function refreshHighlights() {
        if (overlayBusy || document.hidden) return;
        overlayBusy = true;
        try {
            const response = await fetch("/api/map-lab/highlights", {cache:"no-store"});
            if (!response.ok) throw new Error("Highlight API unavailable");
            const data = await response.json();
            if (!data || data.ok !== true) throw new Error("Highlight data unavailable");
            const now = Date.now();
            emergencyTargets = (Array.isArray(data.emergency_vessels)
                ? data.emergency_vessels : []).slice(0,80)
                .filter(row => row && /^\d{9}$/.test(String(row.mmsi || ""))
                    && ["knrm","waterpolitie"].includes(row.category)
                    && validHighlightLocation(row)
                    && Number.isFinite(row.remaining_seconds)
                    && row.remaining_seconds > 0 && row.remaining_seconds <= 300)
                .map(row => ({...row, mmsi:String(row.mmsi),
                    expiresAt:now + row.remaining_seconds * 1000}));
            const match = data.atis_match;
            atisTarget = match && /^\d{9}$/.test(String(match.mmsi || ""))
                && validHighlightLocation(match)
                && Number.isFinite(match.remaining_seconds)
                && match.remaining_seconds > 0 && match.remaining_seconds <= 30
                ? {...match, mmsi:String(match.mmsi),
                    expiresAt:now + match.remaining_seconds * 1000} : null;
        } catch (_) {
            // No stale rings are created if the optional overlay is unavailable.
            // Previously approved highlights expire naturally on their deadlines.
        } finally {
            overlayBusy = false;
            tickHighlights();
        }
    }
    function addStationLayer() {
        map.addSource("sdrcc-home", {type:"geojson", data:empty});
        map.addLayer({
            id:"sdrcc-home-ring", type:"circle", source:"sdrcc-home",
            paint: {
                "circle-radius":12, "circle-color":"#0b2a40",
                "circle-stroke-color":"#fbbf56", "circle-stroke-width":2.5,
                "circle-opacity":0.88,
            },
        });
        map.addLayer({
            id:"sdrcc-home-dot", type:"circle", source:"sdrcc-home",
            paint: {
                "circle-radius":4.5, "circle-color":"#fbbf56",
                "circle-stroke-color":"#061729", "circle-stroke-width":1,
            },
        });
        map.addLayer({
            id:"sdrcc-home-name", type:"symbol", source:"sdrcc-home",
            layout: {
                "text-field":["get","name"],
                "text-anchor":"top", "text-offset":[0,1.5],
                "text-size":12, "text-allow-overlap":true,
                "text-ignore-placement":true,
            },
            paint: {
                "text-color":"#ffe0a1",
                "text-halo-color":"#102739", "text-halo-width":2,
            },
        });
        for (const id of ["sdrcc-home-ring","sdrcc-home-dot","sdrcc-home-name"]) {
            map.on("click",id,event=>{
                const feature=event.features && event.features[0];
                if (!feature) return;
                const coords=feature.geometry?.coordinates;
                if (!Array.isArray(coords)) return;
                const div=document.createElement("div");
                div.className="popup-title";
                div.textContent=(feature.properties?.name || "SDRCC station")
                    + " · Home Position";
                new maplibregl.Popup({offset:12})
                    .setLngLat(coords).setDOMContent(div).addTo(map);
            });
        }
    }
    function refreshStation(station) {
        const valid=station && Number.isFinite(station.lon)
            && Number.isFinite(station.lat) && Math.abs(station.lon) <= 180
            && Math.abs(station.lat) <= 90;
        el("station-status").textContent=valid ? "Home Position" : "Not configured";
        map.getSource("sdrcc-home").setData(valid
            ? {type:"FeatureCollection",features:[{
                type:"Feature",
                geometry:{type:"Point", coordinates:[station.lon,station.lat]},
                properties:{name:String(station.name || "SDRCC station").slice(0,64)},
            }]} : empty);
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
            el("legend-mini-status").textContent =
                "AIS " + (data.ais?.available ? ships.length : "OFF")
                + " · ADS-B " + (data.adsb?.available ? planes.length : "OFF");
            const aisTotal = Number.isInteger(data.ais?.source_count) ? data.ais.source_count : ships.length;
            const adsbTotal = Number.isInteger(data.adsb?.source_count) ? data.adsb.source_count : planes.length;
            const unverified = Number.isInteger(data.ais?.unverified_count) ? data.ais.unverified_count : 0;
            const historical = ships.filter(ship => ship.position_stale === true).length;
            el("feed-detail").textContent =
                `AIS: ${ships.length} plotted from ${aisTotal} records`
                + ` · ${hasHull(ships)} scaled hulls`
                + (unverified ? ` (orange: ${unverified} unverified)` : "")
                + (historical ? ` · ${historical} historical AIS positions (>30 min)` : "")
                + ` · ADS-B: ${planes.length} plotted from ${adsbTotal} records`;
            el("feed-status").textContent =
                "AIS " + (data.ais?.available ? "LIVE" : "UNAVAILABLE")
                + " · ADS-B " + (data.adsb?.available ? "LIVE" : "UNAVAILABLE")
                + " · Updated " + new Date().toLocaleTimeString();
            if (loaded) {
                map.getSource("sdrcc-ais").setData(makeGeoJson(ships));
                const hulls=hullCollection(ships);
                map.getSource("sdrcc-ais-hulls").setData(hulls);
                map.getSource("sdrcc-ais-decks").setData(deckCollection(ships,hulls));
                map.getSource("sdrcc-adsb").setData(makeGeoJson(planes));
                if (el("layer-tracks").checked && Date.now()-lastTrackFetchAt > 30000)
                    void loadAllTracks();
                refreshStation(data.station);
                latestShips = ships;
                tickHighlights();
            }
        } catch (error) {
            el("feed-status").textContent = "Traffic refresh failed: " + error.message;
        } finally {
            inFlight = false;
            if (loaded) void refreshHighlights();
        }
    }

    map.on("load", () => {
        addBuildings();
        addSectorLayers();
        registerSprites();
        addTrackLayer();
        addHullLayer();
        addPoints("ais");
        addPoints("adsb");
        addAlertLayers();
        addStationLayer();
        loaded = true;
        setAuxVisibility("station", el("layer-station").checked);
        setAuxVisibility("vts", el("layer-vts").checked);
        void loadSectors();
        setLayerVisibility("ais", el("layer-ais").checked);
        setLayerVisibility("adsb", el("layer-adsb").checked);
        setAlertVisibility();
        setMode(mode3d);
        void refresh();
    });
    map.on("error", event => {
        const reason = event.error && event.error.message || "";
        if (/style|tile|network|fetch|load/i.test(reason)) {
            el("feed-status").textContent = "Basemap network warning; the existing SDRCC viewers remain available.";
        }
    });
    el("mode-2d").addEventListener("click", () => setMode(false));
    el("mode-3d").addEventListener("click", () => setMode(true));
    el("layer-ais").addEventListener("change", () => {
        setLayerVisibility("ais", el("layer-ais").checked);
        setAlertVisibility();
        if (el("layer-ais").checked && el("layer-tracks").checked)
            void loadAllTracks();
    });
    el("track-duration").addEventListener("input", () => {
        el("track-duration-value").textContent = el("track-duration").value + " min";
    });
    el("track-duration").addEventListener("change", () => {
        const parsed = Number(el("track-duration").value);
        trackMinutes = Number.isFinite(parsed)
            ? Math.max(1, Math.min(60, Math.round(parsed))) : 15;
        el("track-duration").value = String(trackMinutes);
        el("track-duration-value").textContent = trackMinutes + " min";
        try { window.localStorage.setItem(trackMinutesKey, String(trackMinutes)); }
        catch (_) { /* Browser storage may be disabled. */ }
        trackRequestSequence++;
        if (loaded && el("layer-tracks").checked && el("layer-ais").checked)
            void loadAllTracks();
    });
    el("layer-tracks").addEventListener("change", () => {
        trackRequestSequence++;
        setTrackVisibility();
        if (!el("layer-tracks").checked) {
            map.getSource("sdrcc-ais-track").setData(empty);
            el("track-status").textContent = "Off";
        } else {
            void loadAllTracks();
        }
    });
    el("layer-adsb").addEventListener("change", () => setLayerVisibility("adsb", el("layer-adsb").checked));
    el("layer-station").addEventListener("change", () =>
        setAuxVisibility("station", el("layer-station").checked));
    el("layer-vts").addEventListener("change", () =>
        setAuxVisibility("vts", el("layer-vts").checked));
    el("layer-emergency").addEventListener("change", setAlertVisibility);
    el("layer-atis").addEventListener("change", setAlertVisibility);
    el("show-names").addEventListener("change", () => {
        setLayerVisibility("ais", el("layer-ais").checked);
        setLayerVisibility("adsb", el("layer-adsb").checked);
    });
    el("reset-view").addEventListener("click", () => {
        map.easeTo({center: resetCenter, zoom: 11, bearing: mode3d ? -22 : 0, pitch: mode3d ? 62 : 0});
    });
    el("refresh-now").addEventListener("click", refresh);
    window.setInterval(refresh, 10000);
    window.setInterval(tickHighlights, 650);
})();
