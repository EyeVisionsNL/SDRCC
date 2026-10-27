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
    const trackEnabledKey = "sdrcc.mapLab.tracksEnabled";
    // Remember whether the operator enabled ALL vessel tracks (not just
    // their existing 1–60 min history length).
    try { el("layer-tracks").checked = window.localStorage.getItem(trackEnabledKey) === "1"; }
    catch (_) { el("layer-tracks").checked = false; }
    const trafficGroup=el("traffic-layer-settings");
    const trafficGroupKey="sdrcc.mapLab.trafficLayersOpen";
    if(trafficGroup){
        try { trafficGroup.open=window.localStorage.getItem(trafficGroupKey)!=="0"; }
        catch (_) { trafficGroup.open=true; }
        trafficGroup.addEventListener("toggle",()=>{
            try {window.localStorage.setItem(trafficGroupKey,trafficGroup.open?"1":"0");}
            catch (_) { /* Map layer controls remain operable without storage. */ }
        });
    }
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
    // Independent visibility preference for the Possible Speaker photo.
    const speakerPanel = el("speaker-photo-panel");
    const speakerShow = el("speaker-photo-show");
    const speakerPhotoKey = "sdrcc.mapLab.speakerPhotoVisible";
    let speakerVisible = true, speakerIdentity = "", speakerRetryAt = 0;
    let speakerRequest = 0;
    try { speakerVisible = window.localStorage.getItem(speakerPhotoKey) !== "0"; }
    catch (_) { /* optional storage */ }
    function showSpeakerPanel() {
        speakerPanel.hidden = !speakerVisible;
        speakerShow.hidden = speakerVisible;
    }
    function setSpeakerVisible(value) {
        speakerVisible = value;
        ++speakerRequest; speakerIdentity = ""; speakerRetryAt = 0;
        try { window.localStorage.setItem(speakerPhotoKey,value?"1":"0"); } catch (_) {}
        showSpeakerPanel();
        if (value) void refreshSpeakerPhoto(atisTarget);
    }
    el("speaker-photo-hide").addEventListener("click",()=>setSpeakerVisible(false));
    speakerShow.addEventListener("click",()=>setSpeakerVisible(true));
    showSpeakerPanel();
    async function refreshSpeakerPhoto(match) {
        if(!speakerVisible) return;
        const image=el("speaker-photo-image"),link=el("speaker-photo-link");
        const name=el("speaker-photo-name"),credit=el("speaker-photo-credit");
        const mmsi=String(match?.mmsi||"");
        const ship=latestShips.find(row=>String(row.id)===mmsi);
        const shipname=String(ship?.name||match?.shipname||match?.callsign||"").trim();
        const imo=String(ship?.imo||match?.imo||"").trim();
        const eni=String(ship?.eni||match?.eni||"").trim();
        const identity=[mmsi,shipname.toUpperCase(),imo,eni].join("|");
        if(!/^\d{9}$/.test(mmsi) || !match) {
            ++speakerRequest; speakerIdentity="";
            image.hidden=true;image.removeAttribute("src");link.removeAttribute("href");
            name.textContent="Waiting for validated Marine ATIS…";credit.textContent="";
            return;
        }
        if(identity===speakerIdentity && Date.now()<speakerRetryAt) return;
        speakerIdentity=identity;speakerRetryAt=Date.now()+30*60*1000;
        const request=++speakerRequest;
        image.hidden=true;image.removeAttribute("src");link.removeAttribute("href");
        name.textContent=shipname||("MMSI "+mmsi);credit.textContent="Searching vessel photo…";
        try {
            const url="/api/traffic-voice/vessel-photo?mmsi="+encodeURIComponent(mmsi)
                +"&shipname="+encodeURIComponent(shipname)
                +"&imo="+encodeURIComponent(imo)+"&eni="+encodeURIComponent(eni);
            const response=await fetch(url,{cache:"no-store"});
            const result=await response.json();
            if(request!==speakerRequest || !speakerVisible) return;
            if(!response.ok || !result.ok || !result.image_url) {
                credit.textContent="No vessel photo available."; return;
            }
            image.onload=()=>{if(request===speakerRequest) image.hidden=false;};
            image.onerror=()=>{
                if(request!==speakerRequest)return;
                image.hidden=true;credit.textContent="Photo could not be loaded.";
            };
            image.alt="Photo of "+(shipname||"matched vessel");
            image.style.objectFit=result.source==="De Binnenvaart"?"contain":"";
            image.src=result.image_url;
            if(result.page_url && /^https:\/\//.test(result.page_url))
                link.href=result.page_url;
            const sourceLabel=result.source==="Rensen-Driessen" && result.artist?"":result.source;
            credit.textContent=result.source==="De Binnenvaart" && result.artist
                ?"Foto: © "+result.artist
                :[sourceLabel,result.artist,result.license].filter(Boolean).join(" · ");
        } catch (_) {
            if(request===speakerRequest) credit.textContent="Photo lookup unavailable.";
        }
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
    // Opt-in: move the camera only once for each new ATIS match event.
    const atisFollowKey = "sdrcc.mapLab.atisAutoFocus";
    const atisZoomKey = "sdrcc.mapLab.atisFocusZoom";
    let atisAutoFocus = false;
    let atisFocusZoom = 15;
    let lastFocusedAtisEvent = "";
    try {
        atisAutoFocus = window.localStorage.getItem(atisFollowKey) === "1";
        const savedZoom = Number(window.localStorage.getItem(atisZoomKey));
        if (Number.isFinite(savedZoom) && savedZoom >= 11 && savedZoom <= 18)
            atisFocusZoom = savedZoom;
    } catch (_) { /* Browser storage can be disabled. */ }
    el("atis-auto-focus").checked = atisAutoFocus;
    el("atis-focus-zoom").value = String(atisFocusZoom);
    el("atis-focus-zoom-value").textContent = String(atisFocusZoom);
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
    const AIS_NAME_3D_SWITCH_ZOOM = 16;
    // In 3D, an AIS nameplate placed on the antenna position can cover the
    // wheelhouse. At harbour zoom use offset side labels without the coloured
    // plate; preserve the original plate and positioning when back in 2D.
    const AIS_NAME_PLATE_IMAGE = ["concat","sdrcc-name-",
        ["to-string",["get","shipclass"]]];
    const AIS_NAME_2D_ANCHORS = ["top","bottom","right","left"];
    const AIS_NAME_3D_ANCHORS = ["left","right"];
    const AIS_NAME_2D_OFFSET = ["interpolate",["linear"],["zoom"],
        12.5,1.6,14,2.1,16,3.2,18,5];
    // Keep close-up labels near the hull instead of pushing short vessels'
    // names several hundred pixels away. Long hulls retain extra clearance.
    // Native symbol collision detection still avoids clutter in busy harbours.
    const AIS_NAME_LENGTH_CLEARANCE = ["*",.025,
        ["min",200,["max",0,["coalesce",["get","length_m"],0]]]];
    const AIS_NAME_3D_OFFSET = ["interpolate",["linear"],["zoom"],
        12.5,1.6,
        14,["+",2.2,AIS_NAME_LENGTH_CLEARANCE],
        15,["+",2.4,AIS_NAME_LENGTH_CLEARANCE],
        16,["+",2.4,AIS_NAME_LENGTH_CLEARANCE],
        17,["+",2.7,["*",1.2,AIS_NAME_LENGTH_CLEARANCE]],
        18,["+",3.1,["*",2,AIS_NAME_LENGTH_CLEARANCE]],
        19,["+",3.4,["*",3.5,AIS_NAME_LENGTH_CLEARANCE]]];
    const AIS_NAME_2D_TEXT_SIZE = ["interpolate",["linear"],["zoom"],
        12.5,8.5,15,9,18,9.5];
    const AIS_NAME_3D_TEXT_SIZE = ["interpolate",["linear"],["zoom"],
        16,11.5,17,12,18,13];
    const AIS_NAME_2D_TEXT_COLOR = ["match",["get","shipclass"],
        0,"#072331",1,"#072331",2,"#0c281c",
        7,"#17232b",8,"#17232b",9,"#17232b",10,"#17232b",
        12,"#17232b","#ffffff"];
    // 3D aircraft are intentionally elevated map miniatures, NOT ADS-B
    // altitude-to-metres conversions. ADS-B flight levels remain in popups.
    // Switch directly from 2D silhouettes to 3D aircraft at zoom 15:
    // overlapping zoom ranges made both symbols appear for one target.
    // Larger visual miniatures remain illustrative, not real wingspans.
    const AIRCRAFT_3D_MIN_ZOOM = 15;
    const AIRCRAFT_3D_PLANE_SCALE = 2.4;
    const AIRCRAFT_3D_HELI_SCALE = 1.6;
    const AIRCRAFT_3D_PLANE_BASE_M = 62;
    const AIRCRAFT_3D_HELI_BASE_M = 52;
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
    // Fixed altitude bands in feet; unknown altitude is neutral grey.
    const AIR_ALTITUDE_COLORS = Object.freeze({
        unknown:"#aebdcc",low:"#3bd66f",climb:"#b8e15a",
        mid:"#ffd45a",high:"#ff9650",upper:"#e47bd7",cruise:"#ae88ff",
    });
    function altitudeBand(ft) {
        if (!Number.isFinite(ft)) return "unknown";
        return ft < 2000 ? "low" : ft < 5000 ? "climb"
            : ft < 10000 ? "mid" : ft < 20000 ? "high"
            : ft < 30000 ? "upper" : "cruise";
    }
    const AIS_CLASS_NAMES = Object.freeze({
        0:"Other", 1:"Unknown", 2:"Cargo", 3:"Class B", 4:"Passenger",
        5:"Special", 6:"Tanker", 7:"High speed", 8:"Fishing",
        9:"Aircraft", 10:"Helicopter", 11:"Station", 12:"Aid to navigation",
        13:"Search and rescue",
    });
    // Distinct display types share the existing bounded, AIS-sized hulls.
    // 3D superstructures are illustrative; they are not reported deck plans.
    const smallHullProfiles = new Set([
        "watertaxi","krve","pleasure","sailing","catamaran","fishing",
        "service","workboat","dredger","crane_workboat","pushboat",
        "pilot","rescue","port_service","oil_response","ferry","water_supply"
    ]);
    const mediumHullProfiles = new Set([
        "police","port_authority","passenger","cruise","cargo",
        "container","bulk","tanker","gas_tanker","powder_tanker",
        "chemical_tanker","bunker","barge_cargo","barge_tanker",
        "container_barge","gas_barge","chemical_barge","powder_barge",
        "convoy_cargo","convoy_tanker","offshore_supply",
        "research_vessel","cable_vessel","offshore_construction",
        "crane_ship"
    ]);
    const hullMinLength = profile => profile === "tug" ? 8 : smallHullProfiles.has(profile) ? 5
        : mediumHullProfiles.has(profile) ? 12 : 30;
    const specialDeckHints = Object.freeze({
        container:"Container stacks and aft bridge (illustrative; actual load unknown)",
        container_barge:"Low container barge with stacks (illustrative)",
        gas_tanker:"Gas tank modules (schematic; tank geometry unknown)",
        gas_barge:"Unpowered gas barge with tank modules (schematic)",
        powder_tanker:"Dry bulk / powder tanker silos (schematic; cargo unknown)",
        powder_barge:"Dry bulk / powder tank barge silos (schematic)",
        chemical_tanker:"Chemical tanker valves and tank deck (illustrative)",
        chemical_barge:"Chemical tank barge deck (illustrative)",
        water_supply:"Drinking-water supply boat with low tank deck, pipes and hose reels (illustrative)",
        bunker:"Bunkering tanker pumps and hose deck (illustrative)",
        bulk:"Bulk carrier hatch covers (illustrative)",
        ferry:"Low vehicle/passenger ferry deck (illustrative)",
        cruise:"Multi-deck river cruise ship with windows (illustrative)",
        catamaran:"Twin-sponson fast catamaran (illustrative)",
        fishing:"Fishing boat deck, gantry and wheelhouse (illustrative)",
        sailing:"Sailing craft with simplified mast and sail (illustrative)",
        pilot:"Pilot boat cabin and coloured stripe (illustrative)",
        rescue:"Search-and-rescue craft markings (illustrative; not dispatch-confirmed)",
        port_service:"Port service craft stripe and cabin (illustrative)",
        oil_response:"Pollution-response craft with deck gear (illustrative)",
        dredger:"Work/dredging vessel hopper and pipe (illustrative)",
        crane_workboat:"Work vessel with schematic deck crane (illustrative)",
        offshore_supply:"Offshore platform supply vessel: forward bridge, open aft work deck (illustrative)",
        research_vessel:"Research/survey vessel: laboratories, mast and working deck (illustrative)",
        cable_vessel:"Cable-laying ship: cable reel and stern guide (illustrative)",
        offshore_construction:"Offshore construction vessel: heavy work deck and crane (illustrative)",
        crane_ship:"Heavy-lift / crane vessel with deck crane (illustrative)",
    });
    function hullGeometry(ship) {
        if (ship.is_offshore_structure ||
                ["offshore_wtg", "offshore_platform", "ais_helicopter"]
                    .includes(ship.render_profile)) return null;
        if (!ship.hull_available || !Number.isFinite(ship.hull_heading)) return null;
        const bow = ship.to_bow, stern = ship.to_stern;
        const port = ship.to_port, starboard = ship.to_starboard;
        if (![bow, stern, port, starboard, ship.lon, ship.lat].every(Number.isFinite)) return null;
        const length = bow + stern, beam = port + starboard;
        if (bow < 0 || stern < 0 || port < 0 || starboard < 0
                || length < hullMinLength(ship.render_profile) || length > 450 || beam < 2 || beam > 90
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
        // Flat-ended barges and pushing craft stay within the reported
        // overall AIS dimensions; do not invent individual barge positions.
        const flatEnds = ["barge_cargo","barge_tanker","container_barge","gas_barge",
            "chemical_barge","powder_barge","convoy_cargo",
            "convoy_tanker","pushboat"].includes(ship.render_profile);
        const pts = flatEnds ? [
            at(-stern, -port*.83), at(-stern, starboard*.83),
            at(-stern+length*.035, starboard),
            at(bow-length*.035, starboard),
            at(bow, starboard*.83), at(bow, -port*.83),
            at(bow-length*.035, -port),
            at(-stern+length*.035, -port),
        ] : [
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
                    special_profile_evidence: ship.special_profile_evidence || "",
                    inland_type_code: ship.inland_type_code,
                    inland_type_name: ship.inland_type_name,
                    inland_convoy_barges: ship.inland_convoy_barges,
                    beam_m: ship.beam_m, draught_m: ship.draught_m,
                    heading: ship.heading,
                    display_height_m: ["watertaxi","krve","pleasure","sailing","catamaran","fishing","water_supply"].includes(ship.render_profile)
                        ? Math.min(1.8, Math.max(.9,
                            (Number(ship.to_port) + Number(ship.to_starboard)) * .45))
                        : ["barge_cargo","barge_tanker","container_barge","gas_barge",
                            "chemical_barge","powder_barge"].includes(ship.render_profile)
                            ? Math.min(2.5, Math.max(1.1,
                                (Number(ship.to_port) + Number(ship.to_starboard)) * .22))
                            : Math.min(9, Math.max(2.5,
                                (Number(ship.to_port) + Number(ship.to_starboard)) * .38)),
                },
            });
        }
        return {type: "FeatureCollection", features};
    }
    // Compact native MapLibre extrusions for AIS offshore structures. Geometry is
    // illustrative, not a measurement of the installation. No new libraries.
    function offshore3dCollection(ships) {
        const features = [];
        for (const ship of ships) {
            const wind = ship.render_profile === "offshore_wtg";
            if (!wind && ship.render_profile !== "offshore_platform") continue;
            const lon = ship.lon, lat = ship.lat;
            if (![lon,lat].every(Number.isFinite) || Math.abs(lat)>85) continue;
            const metresLon = 111320 * Math.cos(lat*Math.PI/180);
            const rectangle = (x,y,dx,dy,part,base,top) => {
                const corners = [[x-dx/2,y-dy/2],[x+dx/2,y-dy/2],
                    [x+dx/2,y+dy/2],[x-dx/2,y+dy/2]];
                const ring = corners.map(([east,north]) =>
                    [lon+east/metresLon,lat+north/111320]);
                ring.push(ring[0]);
                features.push({type:"Feature",geometry:{type:"Polygon",coordinates:[ring]},
                    properties:{id:String(ship.id),part,base_height_m:base,
                        top_height_m:top,render_profile:ship.render_profile}});
            };
            if (wind) {
                rectangle(0,0,3.5,3.5,"wind-tower",0,55);
                rectangle(3,0,11,3.5,"wind-nacelle",55,60);
                // Three recognizable stationary blades at hub height.
                rectangle(7,0,2.4,36,"wind-rotor",60,61);
                rectangle(-1,-9,2.4,18,"wind-rotor",60,61);
                rectangle(-1,9,2.4,18,"wind-rotor",60,61);
            } else {
                for(const x of [-12,12]) for(const y of [-9,9])
                    rectangle(x,y,3.5,3.5,"platform-leg",0,18);
                rectangle(0,0,32,25,"platform-deck",18,23);
                rectangle(-5,0,13,11,"platform-building",23,34);
                rectangle(9,4,7,7,"platform-plant",23,29);
                rectangle(13,-8,2,2,"platform-mast",23,46);
            }
        }
        return {type:"FeatureCollection",features};
    }
    function addOffshore3dLayer() {
        map.addSource("sdrcc-offshore-3d", {type:"geojson",data:empty});
        map.addLayer({id:"sdrcc-offshore-3d-structures",type:"fill-extrusion",
            source:"sdrcc-offshore-3d",minzoom:14,
            layout:{visibility:"none"},
            paint:{"fill-extrusion-color":["match",["get","part"],
                "wind-tower","#e1e9ed","wind-nacelle","#ccdce1",
                "wind-rotor","#f4f9fa","platform-leg","#71899c",
                "platform-deck","#c0a66e","platform-building","#cbd6de",
                "platform-plant","#6d8293","platform-mast","#cfdbe2","#8299a7"],
                "fill-extrusion-base":["get","base_height_m"],
                "fill-extrusion-height":["get","top_height_m"],
                "fill-extrusion-opacity":0.96}});
    }

    // Bright elevated miniatures ensure aircraft don't disappear into 3D
    // buildings. Height and enlarged footprint are purely visual: never
    // replace actual ADS-B altitude or change the 2D map.
    function aircraft3dCollection(items,kind) {
        const features=[];
        for(const item of items) {
            const heli=kind==="ais" ? item.render_profile==="ais_helicopter" : item.is_helicopter===true;
            if(kind==="ais" && !heli) continue;
            if(![item.lon,item.lat].every(Number.isFinite) || Math.abs(item.lat)>85) continue;
            const heading=(Number.isFinite(item.course)?item.course:0)*Math.PI/180;
            const sn=Math.sin(heading),cs=Math.cos(heading);
            const lonFactor=111320*Math.cos(item.lat*Math.PI/180);
            const size=heli ? AIRCRAFT_3D_HELI_SCALE
                : AIRCRAFT_3D_PLANE_SCALE;
            const props=trafficProperties(item);
            const visualBase = heli ? AIRCRAFT_3D_HELI_BASE_M
                : AIRCRAFT_3D_PLANE_BASE_M;
            const piece=(poly,part,base,height)=>{
                const ring=poly.map(([f,r])=>[
                    item.lon+(f*sn+r*cs)*size/lonFactor,
                    item.lat+(f*cs-r*sn)*size/111320]);
                ring.push(ring[0]);
                features.push({type:"Feature",geometry:{type:"Polygon",coordinates:[ring]},
                    properties:{...props,part,
                        base_height_m:visualBase+base,
                        top_height_m:visualBase+height}});
            };
            if(heli){
                piece([[8,0],[4,-2],[-4,-2],[-5,0],[-4,2],[4,2]],"heli-body",0,4.1);
                piece([[-4,-.6],[-11,-.6],[-11,.6],[-4,.6]],"heli-tail",1.8,3.2);
                piece([[-1,-11],[1,-11],[1,11],[-1,11]],"heli-rotor",4.8,5.35);
                piece([[-12,-2],[-11,-2],[-11,2],[-12,2]],"heli-tailrotor",3.3,3.9);
            }else{
                piece([[16,0],[9,-1.5],[-12,-1.5],[-16,0],[-12,1.5],[9,1.5]],"plane-body",0,4.3);
                piece([[4,-2],[-8,-15],[-10,-15],[-6,-1]],"plane-wing",2.5,3.25);
                piece([[4,2],[-6,1],[-10,15],[-8,15]],"plane-wing",2.5,3.25);
                piece([[-10,-1],[-15,-6],[-16,-6],[-14,1]],"plane-tail",3.15,4.1);
                piece([[-10,1],[-14,-1],[-16,6],[-15,6]],"plane-tail",3.15,4.1);
            }
        }
        return {type:"FeatureCollection",features};
    }
    // MapLibre dispatches one native click to every overlapping interactive
    // layer (hull, deck, icon and label). Only one popup may handle that
    // native click, and a new click replaces the currently open popup.
    const handledPopupClicks = new WeakSet();
    let activeMapPopup = null;
    function showSingleMapPopup(event, lngLat, content, options = {}) {
        const nativeEvent = event && event.originalEvent;
        if (nativeEvent && typeof nativeEvent === "object") {
            if (handledPopupClicks.has(nativeEvent)) return;
            handledPopupClicks.add(nativeEvent);
        }
        if (activeMapPopup) activeMapPopup.remove();
        activeMapPopup = new maplibregl.Popup(options)
            .setLngLat(lngLat).setDOMContent(content).addTo(map);
    }
    function addAircraft3dLayers() {
        for(const kind of ["ais","adsb"]){
            const source="sdrcc-"+kind+"-air-3d", layer=source+"-models";
            map.addSource(source,{type:"geojson",data:empty});
            map.addLayer({id:layer,type:"fill-extrusion",source,
                minzoom:AIRCRAFT_3D_MIN_ZOOM,
                layout:{visibility:"none"},
                paint:{"fill-extrusion-color":["match",["get","part"],
                    // Strong warm/dark aircraft palette, unlike blue buildings.
                    "heli-body","#ff942e","heli-tail","#253447",
                    "heli-rotor","#ffe66d","heli-tailrotor","#182a42",
                    "plane-body","#ffd344","plane-wing","#ff812b",
                    "plane-tail","#223248","#ffb732"],
                    "fill-extrusion-base":["get","base_height_m"],
                    "fill-extrusion-height":["get","top_height_m"],
                    "fill-extrusion-opacity":1}});
            map.on("click",layer,event=>{
                const feature=event.features?.[0];
                if(!feature) return;
                showSingleMapPopup(event,
                    [feature.properties.lon,feature.properties.lat],
                    popup(feature),{maxWidth:"360px"});
            });
        }
    }
    function deckCollection(ships, hulls) {
        // Native MapLibre prisms: illustration only, not measured AIS equipment.
        const features = [];
        const detailsById = new Map(hulls.features.map(f => [f.properties.id, f.properties]));
        for (const ship of ships) {
            const profile = ship.render_profile;
            if (!["tanker", "cargo", "passenger", "tug", "police", "watertaxi",
                "krve", "port_authority", "pleasure", "service",
                "barge_cargo", "barge_tanker", "convoy_cargo", "convoy_tanker",
                "pushboat", "workboat", "container", "container_barge", "bulk",
                "gas_tanker", "gas_barge", "chemical_tanker", "chemical_barge",
                "powder_tanker", "powder_barge", "bunker", "water_supply", "ferry", "cruise",
                "catamaran", "fishing", "sailing", "dredger", "crane_workboat",
                "pilot", "rescue", "port_service", "oil_response",
                "offshore_supply", "research_vessel", "cable_vessel",
                "offshore_construction", "crane_ship"].includes(profile)) continue;
            const info = detailsById.get(String(ship.id));
            if (!info) continue;
            const {to_bow:bow, to_stern:stern, to_port:port,
                to_starboard:starboard, lon, lat, hull_heading:headingDeg} = ship;
            if (![bow,stern,port,starboard,lon,lat,headingDeg].every(Number.isFinite)
                    || Math.abs(lat) > 85) continue;
            const length = bow+stern, beam = port+starboard;
            if (length < hullMinLength(profile) || beam < 2) continue;
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

            // Added model families use real AIS dimensions and orientation only.
            // Cargo/loading state, deck equipment and superstructure are schematic.

            // AIS 90/99 special-purpose vessels: shape only when the Python
            // backend provides a positively matched profile. Scale every deck
            // element within the actual AIS length, beam and heading. An empty
            // work deck does not imply that any particular cargo is aboard.
            if (profile === "water_supply") {
                // Compact fresh-water tanker: low flush tank deck, aft wheelhouse,
                // pump manifold and twin hose reels. All positions scale to AIS.
                add(-stern+length*.24,bow-length*.09,-port*.82,starboard*.82,"water-deck",.22);
                add(-stern+length*.06,-stern+length*.23,-port*.70,starboard*.70,"water-house",1.7);
                add(-stern+length*.10,-stern+length*.22,-port*.57,starboard*.57,"water-windows",.65,1.7);
                add(-stern+length*.085,-stern+length*.235,-port*.65,starboard*.65,"water-roof",.16,2.35);
                for (const f of [.36,.54,.72])
                    add(-stern+length*f,-stern+length*(f+.045),-port*.23,starboard*.23,"water-hatch",.25,.22);
                add(-stern+length*.29,bow-length*.13,-port*.07,starboard*.07,"water-pipe",.25,.48);
                add(-stern+length*.75,-stern+length*.82,-port*.48,starboard*.48,"water-pump",.65,.22);
                for (const side of [-1,1]) {
                    const center=side*beam*.27;
                    add(-stern+length*.27,-stern+length*.34,center-beam*.08,center+beam*.08,"water-hose",.75,.22);
                }
                continue;
            }
            if (profile === "offshore_supply") {
                // Recognizable PSV silhouette: broad open aft workdeck,
                // tall two-level forward bridge and a small navigation mast.
                // Heights and fittings are illustrative, not AIS measurements.
                add(-stern+length*.04,-stern+length*.69,
                    -port*.91,starboard*.91,"psv-workdeck",.3);
                for (const side of [-1,1]) {
                    const left=side<0?-port*.94:starboard*.85;
                    const right=side<0?-port*.85:starboard*.94;
                    add(-stern+length*.05,-stern+length*.69,
                        left,right,"psv-safety-rail",.55,.3);
                }
                // Larger lower bridge block, entirely inside AIS hull length.
                add(-stern+length*.70,bow-length*.045,
                    -port*.76,starboard*.76,"psv-wheelhouse",5.65,.3);
                // Blue side-window bands make the bridge readable obliquely.
                for (const side of [-1,1]) {
                    const left=side<0?-port*.78:starboard*.70;
                    const right=side<0?-port*.70:starboard*.78;
                    add(-stern+length*.73,bow-length*.075,
                        left,right,"psv-side-windows",1.05,3.65);
                }
                // Raised, narrower navigation bridge with panoramic glazing.
                add(-stern+length*.78,bow-length*.065,
                    -port*.65,starboard*.65,"psv-bridge-upper",2.2,5.95);
                add(bow-length*.145,bow-length*.063,
                    -port*.67,starboard*.67,"psv-bridge-glass",1.35,6.18);
                for (const side of [-1,1]) {
                    const left=side<0?-port*.68:starboard*.60;
                    const right=side<0?-port*.60:starboard*.68;
                    add(-stern+length*.80,bow-length*.09,
                        left,right,"psv-upper-windows",1.15,6.35);
                }
                add(-stern+length*.76,bow-length*.05,
                    -port*.71,starboard*.71,"psv-bridge-roof",.38,8.15);
                add(-stern+length*.85,-stern+length*.87,
                    -port*.065,starboard*.065,"psv-mast",3.0,8.53);
                // Minimal fittings only: never assert actual deck cargo.
                add(-stern+length*.20,-stern+length*.32,
                    -port*.23,starboard*.23,"psv-deck-gear",.35,.3);
                continue;
            }
            if (profile === "research_vessel") {
                add(-stern+length*.12,bow-length*.15,
                    -port*.83,starboard*.83,"research-workdeck",.35);
                add(-stern+length*.28,-stern+length*.69,
                    -port*.64,starboard*.64,"research-laboratory",3.1,.35);
                add(-stern+length*.31,-stern+length*.68,
                    -port*.69,starboard*.69,"research-windows",.58,1.95);
                add(-stern+length*.64,-stern+length*.68,
                    -port*.10,starboard*.10,"research-mast",5.2,3.45);
                continue;
            }
            if (profile === "cable_vessel") {
                add(-stern+length*.07,bow-length*.09,
                    -port*.83,starboard*.83,"cable-workdeck",.3);
                add(-stern+length*.64,bow-length*.07,
                    -port*.70,starboard*.70,"cable-wheelhouse",3.6,.3);
                // Schematic reel and stern chute, not measured machinery.
                add(-stern+length*.19,-stern+length*.45,
                    -port*.57,starboard*.57,"cable-reel",2.5,.3);
                for (const side of [-1,1]) {
                    const left=side<0?-port*.59:starboard*.47;
                    const right=side<0?-port*.47:starboard*.59;
                    add(-stern+length*.20,-stern+length*.44,
                        left,right,"cable-reel-rim",3.0,.3);
                }
                add(-stern+length*.035,-stern+length*.17,
                    -port*.24,starboard*.24,"cable-stern-chute",.95,.3);
                continue;
            }
            if (profile === "offshore_construction" || profile === "crane_ship") {
                add(-stern+length*.06,bow-length*.10,
                    -port*.88,starboard*.88,"construction-deck",.35);
                const forwardHouse=profile==="offshore_construction";
                const cabinStart=-stern+length*(forwardHouse ? .68 : .07);
                const cabinEnd=-stern+length*(forwardHouse ? .90 : .25);
                add(cabinStart,cabinEnd,
                    -port*.68,starboard*.68,"construction-wheelhouse",4.15,.35);
                const tower=-stern+length*(forwardHouse ? .38 : .55);
                add(tower-length*.025,tower+length*.035,
                    -port*.19,starboard*.19,"construction-crane-tower",8.0,.35);
                add(tower-length*.30,tower+length*.045,
                    -port*.10,starboard*.10,"construction-crane-boom",.75,7.6);
                if(profile==="offshore_construction")
                    add(-stern+length*.12,-stern+length*.28,
                        -port*.46,starboard*.46,"construction-equipment",1.2,.35);
                continue;
            }
            if (profile === "container" || profile === "container_barge") {
                const barge = profile === "container_barge";
                if (barge) add(-stern+length*.035,bow-length*.035,
                    -port*.94,starboard*.94,"barge-rim",.22);
                else add(-stern+length*.045,-stern+length*.17,
                    -port*.56,starboard*.56,"container-bridge",4.3);
                const start=barge ? .10 : .21, end=.91;
                const bays=length>170?6:length>80?4:2;
                for(let n=0;n<bays;n++){
                    const from=-stern+length*(start+(end-start)*(n+.06)/bays);
                    const to=-stern+length*(start+(end-start)*(n+.92)/bays);
                    for(let side=0;side<2;side++){
                        const left=side===0?-port*.86:0;
                        const right=side===0?0:starboard*.86;
                        const kind=["container-blue","container-rust","container-white"][n%3];
                        add(from,to,left+(right-left)*.05,right-(right-left)*.05,
                            kind,barge ? 1.65 : 2.4,.15);
                        // Second tier is illustrative, not proof of loaded boxes.
                        if(!barge && length>65)
                            add(from,to,left+(right-left)*.05,right-(right-left)*.05,
                                "container-top",2.2,2.55);
                    }
                }
                continue;
            }
            if (["gas_tanker","gas_barge","chemical_tanker","chemical_barge",
                 "powder_tanker","powder_barge","bunker"].includes(profile)) {
                const barge=profile.endsWith("_barge");
                if (barge) add(-stern+length*.04,bow-length*.04,
                    -port*.91,starboard*.91,"barge-rim",.22);
                else add(-stern+length*.055,-stern+length*.20,
                    -port*.60,starboard*.60,"tanker-bridge",3.7);
                const gas=profile==="gas_tanker"||profile==="gas_barge";
                const powder=profile==="powder_tanker"||profile==="powder_barge";
                const chemical=profile==="chemical_tanker"||profile==="chemical_barge";
                const kind=gas?"gas-vessel-tank":powder?"powder-silo":
                    chemical?"chemical-tank":"bunker-tank";
                const tankCount=gas?3:powder?4:chemical?5:3;
                const start=barge ? .10 : .25;
                for(let n=0;n<tankCount;n++){
                    const from=-stern+length*(start+(.89-start)*(n+.13)/tankCount);
                    const to=-stern+length*(start+(.89-start)*(n+.85)/tankCount);
                    add(from,to,-port*.72,starboard*.72,kind,gas ? 2.65 :
                        powder ? 2.25 : chemical ? 1.25 : 1.5,
                        barge ? .2 : .35);
                    if(chemical||profile==="bunker")
                        add(from+length*.004,to-length*.004,
                            -port*.15,starboard*.15,"chemical-valve",.28,1.5);
                }
                if(profile==="bunker"){
                    add(-stern+length*.68,bow-length*.09,
                        -port*.10,starboard*.10,"bunker-hose",.8,1.2);
                    add(-stern+length*.73,-stern+length*.80,
                        -port*.22,starboard*.22,"bunker-pump",1.1,.3);
                }
                continue;
            }
            if (profile === "bulk") {
                add(-stern+length*.035,-stern+length*.16,
                    -port*.68,starboard*.68,"bulk-bridge",5.4);
                for(let n=0;n<5;n++){
                    const from=-stern+length*(.23+n*.137);
                    add(from,from+length*.105,
                        -port*.83,starboard*.83,"bulk-hatch",.66);
                }
                continue;
            }
            if (profile === "ferry") {
                add(-stern+length*.05,bow-length*.05,
                    -port*.89,starboard*.89,"ferry-car-deck",.65);
                add(-stern+length*.25,-stern+length*.76,
                    -port*.43,starboard*.43,"ferry-passenger-cabin",2.2,.65);
                add(-stern+length*.25,-stern+length*.76,
                    -port*.45,starboard*.45,"ferry-roof",.25,2.85);
                for(const side of [-1,1]){
                    const left=side<0?-port*.83:starboard*.74;
                    const right=side<0?-port*.74:starboard*.83;
                    add(-stern+length*.07,bow-length*.07,
                        left,right,"ferry-rail",.65,.65);
                }
                continue;
            }
            if (profile === "cruise") {
                const a=-stern+length*.12,b=-stern+length*.89;
                add(a,b,-port*.83,starboard*.83,"cruise-deck",2.4);
                add(a+length*.03,b-length*.04,
                    -port*.75,starboard*.75,"cruise-hotel",2.6,2.4);
                add(a+length*.07,b-length*.10,
                    -port*.69,starboard*.69,"cruise-sundeck",.30,5.0);
                for(const side of [-1,1]){
                    const left=side<0?-port*.86:starboard*.73;
                    const right=side<0?-port*.73:starboard*.86;
                    add(a+length*.05,b-length*.05,left,right,
                        "cruise-windows",.55,1.1);
                    add(a+length*.08,b-length*.09,left,right,
                        "cruise-upper-windows",.5,3.45);
                }
                continue;
            }
            if (profile === "catamaran") {
                // Twin side sponsons are schematic, NOT additional AIS targets.
                for(const side of [-1,1]){
                    const left=side<0?-port*.92:starboard*.48;
                    const right=side<0?-port*.48:starboard*.92;
                    add(-stern+length*.04,bow-length*.08,
                        left,right,"catamaran-sponson",1.2);
                }
                add(-stern+length*.14,bow-length*.20,
                    -port*.87,starboard*.87,"catamaran-deck",.5,1.2);
                add(-stern+length*.28,-stern+length*.70,
                    -port*.61,starboard*.61,"catamaran-cabin",1.9,1.7);
                continue;
            }
            if (profile === "sailing") {
                add(-stern+length*.28,-stern+length*.73,
                    -port*.67,starboard*.67,"sailing-cabin",.9);
                const middle=-stern+length*.54;
                add(middle-length*.009,middle+length*.009,
                    -port*.08,starboard*.08,"sailing-mast",7.5,.5);
                // Pale rectangular extrusion represents a sail silhouette.
                add(middle-length*.21,middle-length*.013,
                    -port*.12,starboard*.12,"sailing-sail",4.0,2.0);
                continue;
            }
            if (profile === "fishing") {
                add(-stern+length*.55,-stern+length*.84,
                    -port*.67,starboard*.67,"fishing-wheelhouse",2.45);
                add(-stern+length*.08,-stern+length*.47,
                    -port*.74,starboard*.74,"fishing-workdeck",.26);
                for(const side of [-1,1]){
                    const left=side<0?-port*.82:starboard*.67;
                    const right=side<0?-port*.67:starboard*.82;
                    add(-stern+length*.20,-stern+length*.31,
                        left,right,"fishing-gantry",3.2);
                }
                continue;
            }
            if (profile === "dredger" || profile === "crane_workboat") {
                add(-stern+length*.05,bow-length*.05,
                    -port*.90,starboard*.90,"workboat-deck",.30);
                add(-stern+length*.61,-stern+length*.86,
                    -port*.63,starboard*.63,"workboat-cabin",2.3);
                if(profile==="crane_workboat"){
                    add(-stern+length*.31,-stern+length*.40,
                        -port*.22,starboard*.22,"crane-tower",6.3,.3);
                    add(-stern+length*.18,-stern+length*.61,
                        -port*.13,starboard*.13,"crane-boom",.65,5.8);
                } else {
                    add(-stern+length*.16,-stern+length*.51,
                        -port*.68,starboard*.68,"dredger-hopper",1.2,.3);
                    add(-stern+length*.39,-stern+length*.52,
                        -port*.16,starboard*.16,"dredger-pipe",1.25,1.5);
                }
                continue;
            }
            if (["pilot","rescue","port_service","oil_response"].includes(profile)) {
                add(-stern+length*.33,-stern+length*.71,
                    -port*.66,starboard*.66,"service-cabin",2.3);
                add(-stern+length*.35,-stern+length*.69,
                    -port*.71,starboard*.71,"service-roof",.24,2.3);
                const accent=profile==="pilot"?"pilot-band":
                    profile==="rescue"?"rescue-band":
                    profile==="oil_response"?"oil-response-band":"port-service-band";
                for(const side of [-1,1]){
                    const left=side<0?-port*.95:starboard*.78;
                    const right=side<0?-port*.78:starboard*.95;
                    add(-stern+length*.10,bow-length*.12,left,right,
                        accent,.36);
                }
                if(profile==="oil_response")
                    add(-stern+length*.13,-stern+length*.30,
                        -port*.40,starboard*.40,"oil-response-gear",.9,.3);
                if(profile==="rescue")
                    add(-stern+length*.51,-stern+length*.56,
                        -port*.17,starboard*.17,"rescue-beacon",.6,2.54);
                continue;
            }
            if (profile === "pleasure") {
                // Small recreation craft: pale deck, compact cockpit and
                // low windshield; nothing here changes other vessel decks.
                add(-stern+length*.10,-stern+length*.84,
                    -port*.78,starboard*.78,"pleasure-deck",.17);
                add(-stern+length*.32,-stern+length*.68,
                    -port*.65,starboard*.65,"pleasure-cabin",1.12);
                add(-stern+length*.62,-stern+length*.70,
                    -port*.64,starboard*.64,"pleasure-windshield",.48,.52);
                add(-stern+length*.13,-stern+length*.29,
                    -port*.48,starboard*.48,"pleasure-cockpit",.3);
                continue;
            }
            if (profile === "barge_cargo" || profile === "barge_tanker") {
                // Unpowered barge: low deck, no speculative wheelhouse.
                add(-stern+length*.04, bow-length*.04,
                    -port*.94, starboard*.94, "barge-rim", .25);
                if (profile === "barge_cargo") {
                    for (let n=0;n<3;n++) {
                        const from=-stern+length*(.11+n*.26);
                        add(from,from+length*.21,
                            -port*.77,starboard*.77,"barge-hatch",.55,.25);
                    }
                } else {
                    for (const side of [-.2,.2]) {
                        const center=side*beam;
                        add(-stern+length*.12,bow-length*.12,
                            center-beam*.045,center+beam*.045,"barge-pipe",.8,.25);
                    }
                }
                continue;
            }
            if (profile === "convoy_cargo" || profile === "convoy_tanker") {
                // Schematic segments, NOT actual individual barge placement.
                // Up to six schematic deck bays, NOT a claim about actual
                // lateral layout. ERI 8290/8390 is "nine or more".
                const count=Math.min(6,Math.max(1,
                    Math.round(Number(ship.inland_convoy_barges)||2)));
                add(-stern+length*.03,-stern+length*.19,
                    -port*.6,starboard*.6,"convoy-pusher-house",2.8);
                add(-stern+length*.19,-stern+length*.23,
                    -port*.78,starboard*.78,"convoy-coupling",.35);
                for(let n=0;n<count;n++) {
                    const from=-stern+length*(.26+n*.68/count);
                    const end=-stern+length*(.26+(n+1)*.68/count-.025);
                    add(from,end,-port*.84,starboard*.84,
                        profile === "convoy_cargo" ? "convoy-cargo-bay" : "convoy-tank-bay",
                        profile === "convoy_cargo" ? .85 : .62);
                }
                continue;
            }
            if (profile === "pushboat") {
                add(-stern+length*.17,-stern+length*.59,
                    -port*.72,starboard*.72,"pushboat-wheelhouse",3.0);
                add(bow-length*.16,bow-length*.06,
                    -port*.82,starboard*.82,"pushboat-push-knees",.75);
                continue;
            }
            if (profile === "workboat") {
                // Generic deck fixtures, NOT confirmed crane or dredger.
                add(-stern+length*.08,bow-length*.08,
                    -port*.88,starboard*.88,"workboat-deck",.25);
                add(-stern+length*.48,-stern+length*.73,
                    -port*.63,starboard*.63,"workboat-cabin",2.35);
                add(-stern+length*.19,-stern+length*.27,
                    -port*.29,starboard*.29,"workboat-equipment",.8,.25);
                continue;
            }
            if (profile === "service") {
                // Neutral service craft for 8450/8451/8453/8454: do not
                // imply Douane, police, fire/rescue or RPA ownership.
                const cabinStart = -stern + length * .42;
                const cabinEnd = -stern + length * .68;
                add(-stern + length * .08, -stern + length * .38,
                    -port * .76, starboard * .76, "service-workdeck", .28);
                add(cabinStart, cabinEnd, -port * .65, starboard * .65,
                    "service-cabin", 2.3);
                add(cabinStart + length*.02, cabinEnd - length*.02,
                    -port * .7, starboard * .7, "service-roof", .22, 2.3);
                for (const side of [-1,1]) {
                    const near = side < 0 ? -port*.72 : starboard*.58;
                    const far = side < 0 ? -port*.58 : starboard*.72;
                    add(cabinStart + length*.04, cabinEnd - length*.04,
                        near, far, "service-windows", .7, .75);
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
            if (profile === "passenger") {
                // Ferry / passenger vessel with long multi-deck superstructure.
                // All dimensions derive from available AIS hull offsets.
                const from=-stern+length*.18, to=-stern+length*.82;
                add(from,to,-port*.79,starboard*.79,"passenger-lower-deck",2.5);
                add(from+length*.04,to-length*.04,
                    -port*.69,starboard*.69,"passenger-upper-deck",2.0,2.5);
                add(from+length*.06,to-length*.06,
                    -port*.71,starboard*.71,"passenger-roof",.25,4.5);
                // Bright blue glazing on both sides and forward bridge.
                for (const side of [-1,1]) {
                    const near=side<0 ? -port*.82 : starboard*.69;
                    const far=side<0 ? -port*.69 : starboard*.82;
                    add(from+length*.04,to-length*.04,
                        near,far,"passenger-windows",.75,1.05);
                    add(from+length*.09,to-length*.09,
                        near,far,"passenger-upper-windows",.55,3.25);
                }
                add(to-length*.075,to,
                    -port*.58,starboard*.58,"passenger-bridge",1.0,4.5);
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
    // Decode HTML entities once and continue rendering with safe textContent.
    function readableText(value) {
        const raw = String(value ?? "");
        if (!/&(?:#(?:x[0-9a-f]+|[0-9]+)|[a-z][a-z0-9]+);/i.test(raw)) return raw;
        const node = document.createElement("textarea");
        node.innerHTML = raw;
        return node.value;
    }
    function trafficProperties(item) {
        const isAIS = item.type === "ais";
        const shipclass = isAIS ? aisClass(item.shipclass) : null;
        const profile = isAIS ? (item.render_profile || "vessel") : "";
        // AIS airborne helicopter targets have a real course even if they
        // don't report ship speed. Normal AIS ships retain existing rules.
        const moving = isAIS && Number.isFinite(item.course)
            && (profile === "ais_helicopter"
                || (Number.isFinite(item.speed_knots) && item.speed_knots > 0.5));
        const unverified = item.validation_state === "unverified";
        const offshore = ["offshore_wtg","offshore_platform"].includes(profile);
        const band = altitudeBand(item.altitude_ft);
        const iconName = isAIS
            ? profile === "ais_helicopter"
                ? "sdrcc-ais-helicopter" + (unverified ? "-unverified" : "")
                : offshore
                    ? "sdrcc-" + profile.replace("_","-")
                        + (unverified ? "-unverified" : "")
                    : "sdrcc-ship-" + shipclass + "-" + (moving ? "moving" : "still")
                        + (unverified ? "-unverified" : "")
            : "sdrcc-" + (item.is_helicopter === true ? "helicopter" : "plane")
                + "-alt-" + band + (Number.isFinite(item.course) ? "" : "-no-course");
        return {
            type: item.type,
            id: String(item.id || ""),
            name: String(item.name || item.id || ""),
            label_name: String(item.name || item.id || "").slice(0, 20),
            callsign: String(item.callsign || ""),
            registration: item.registration || "",
            aircraft_type: item.aircraft_type || "",
            description: item.description || "",
            is_helicopter: item.is_helicopter === true,
            air_3d: isAIS ? profile === "ais_helicopter" : true,
            lon:item.lon, lat:item.lat,
            altitude_band: band,
            altitude_color: AIR_ALTITUDE_COLORS[band],
            operator: item.operator || "",
            squawk: item.squawk || "",
            category: item.category || "",
            baro_rate: item.baro_rate,
            destination: item.destination || "",
            country: item.country || "",
            nav_status: item.nav_status || "",
            shiptype: item.shiptype,
            special_profile_evidence: item.special_profile_evidence || "",
            inland_type_code: item.inland_type_code,
            inland_type_name: item.inland_type_name,
            inland_convoy_barges: item.inland_convoy_barges,
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
                    : profile === "ais_helicopter" ? 0.82
                    : iconScale(item.length_m))
                : (item.is_helicopter === true ? 0.85 : 1),
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
    // Only after zoom 15 (from zoom 16) replace the normal coloured AIS
    // nameplate with text beside the 3D hull. Keep all label placement,
    // colours and the original plate untouched at zoom 15 and below.
    let aisNameClose3d = null;
    function updateAisNamePresentation() {
        if (!loaded || !map.getLayer("sdrcc-ais-labels")) return;
        const close3d = mode3d && map.getZoom() >= AIS_NAME_3D_SWITCH_ZOOM;
        if (aisNameClose3d === close3d) return;
        aisNameClose3d = close3d;
        const nameLayer = "sdrcc-ais-labels";
        map.setLayoutProperty(nameLayer,"icon-image",
            close3d ? "" : AIS_NAME_PLATE_IMAGE);
        map.setLayoutProperty(nameLayer,"text-variable-anchor",
            close3d ? AIS_NAME_3D_ANCHORS : AIS_NAME_2D_ANCHORS);
        map.setLayoutProperty(nameLayer,"text-radial-offset",
            close3d ? AIS_NAME_3D_OFFSET : AIS_NAME_2D_OFFSET);
        map.setLayoutProperty(nameLayer,"text-size",
            close3d ? AIS_NAME_3D_TEXT_SIZE : AIS_NAME_2D_TEXT_SIZE);
        // Readable over both pale land and dark/purple harbour water.
        map.setPaintProperty(nameLayer,"text-color",
            close3d ? "#f5faff" : AIS_NAME_2D_TEXT_COLOR);
        map.setPaintProperty(nameLayer,"text-halo-color",
            close3d ? "#102436" : "rgba(10,21,30,0.12)");
        map.setPaintProperty(nameLayer,"text-halo-width",
            close3d ? 1.9 : .4);
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
        if(map.getLayer("sdrcc-"+kind+"-air-3d-models"))
            map.setLayoutProperty("sdrcc-"+kind+"-air-3d-models","visibility",
                visible && mode3d ? "visible" : "none");
        // 2D icons must stop exactly when 3D extrusions start. A gradual
        // cross-fade leaves a second aircraft on screen between zoom 15-16.
        // In 2D mode the normal silhouette stays visible at every zoom.
        if(kind==="adsb" && map.getLayer("sdrcc-adsb-labels"))
            map.setLayoutProperty("sdrcc-adsb-labels","icon-image",
                mode3d ? ["step",["zoom"],["get","icon_name"],
                    AIRCRAFT_3D_MIN_ZOOM,""] : ["get","icon_name"]);
        if(kind==="adsb" && map.getLayer("sdrcc-adsb-icons"))
            map.setPaintProperty("sdrcc-adsb-icons","icon-opacity",
                mode3d ? ["step",["zoom"],1,AIRCRAFT_3D_MIN_ZOOM,0] : 1);
        if (kind === "ais") {
            updateAisNamePresentation();
            if (map.getLayer("sdrcc-offshore-3d-structures"))
                map.setLayoutProperty("sdrcc-offshore-3d-structures","visibility",
                    visible && mode3d ? "visible" : "none");
            // At zoom 14 AIS hulls replace ship symbols. Offshore fixed
            // structures also stop showing icons there. A real AIS helicopter
            // has no hull: keep its symbol until the 3D model begins at 15,
            // then hide it completely to avoid two helicopter icons.
            const defaultOpacity = ["case",["get","position_stale"],.65,1];
            const opacity = mode3d
                ? ["step",["zoom"],defaultOpacity,
                    HULL_MIN_ZOOM,
                        ["case",["get","is_offshore_structure"],0,defaultOpacity],
                    AIRCRAFT_3D_MIN_ZOOM,
                        ["case",["any",["get","is_offshore_structure"],
                            ["get","air_3d"]],0,defaultOpacity]]
                : defaultOpacity;
            for (const id of ["sdrcc-ais-icons","sdrcc-ais-fallback-icons"]) {
                if (map.getLayer(id)) map.setPaintProperty(id,"icon-opacity",opacity);
            }
            setTrackVisibility();
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
        setLayerVisibility("ais", el("layer-ais").checked);
        setLayerVisibility("adsb", el("layer-adsb").checked);
    }
    function popup(feature) {
        const props = feature.properties || {};
        const box = document.createElement("div");
        box.className = props.type === "adsb"
            ? "traffic-detail traffic-detail--aircraft" : "traffic-detail";
        const title = document.createElement("div");
        title.className = "popup-title";
        title.textContent = (props.render_profile === "ais_helicopter" || props.is_helicopter
            ? "🚁 " : props.type === "ais" ? "🚢 " : "✈ ") + readableText(props.name || props.id);
        box.appendChild(title);
        // Visible without scrolling: aviation photo used to be placed below
        // every aircraft detail (outside the 360px-high popup viewport).
        const photo = props.type === "adsb" && /^[a-f0-9]{6}$/i.test(props.id || "")
            ? document.createElement("div") : null;
        if (photo) {
            photo.className = "popup-photo";
            photo.textContent = "Checking for a credited aircraft photo…";
            box.appendChild(photo);
        }
        const add = (label, value, suffix = "") => {
            if (value === null || value === undefined || value === "") return;
            const row = document.createElement("div");
            row.className = "popup-line";
            const caption = document.createElement("strong");
            caption.textContent = label + ": ";
            row.appendChild(caption);
            const data = document.createElement("span");
            data.textContent = readableText(value) + suffix;
            row.appendChild(data);
            box.appendChild(row);
        };
        if (props.type === "ais") {
            add("MMSI", props.id);
            const activeEmergency = emergencyTargets.find(item =>
                item.mmsi === String(props.id) && item.expiresAt > Date.now());
            if (activeEmergency) add("Emergency vessel",
                activeEmergency.category === "knrm" ? "KNRM" : "Water police");
            if (atisTarget?.mmsi === String(props.id)) {
                add(atisTarget.expiresAt > Date.now()
                    ? "Matched Marine ATIS" : "Last matched Marine ATIS",
                    atisTarget.atis_code);
            }
            if (Number.isFinite(props.age_seconds)) {
                const ageText = props.age_seconds >= 60
                    ? Math.floor(props.age_seconds / 60) + " min ago"
                    : Math.round(props.age_seconds) + " s ago";
                add("Last AIS signal", ageText);
            }
            if (props.position_stale) add("AIS position", "Historical (older than 30 min)");
            if (props.render_profile === "offshore_wtg") add("Structure", "Wind turbine (name-based)");
            else if (props.render_profile === "offshore_platform") add("Structure", "Offshore platform (name-based)");
            else if (props.render_profile === "ais_helicopter")
                add("AIS target", "Helicopter (not a marine vessel)");
            else if (specialDeckHints[props.render_profile])
                add("3D deck", specialDeckHints[props.render_profile]);
            else if (props.render_profile === "tanker") add("3D deck", "Tanker pipes (illustrative)");
            else if (props.render_profile === "cargo") add("3D deck", "Cargo hatches (illustrative)");
            else if (props.render_profile === "passenger") add("3D deck", "Passenger decks, bridge and windows (illustrative)");
            else if (props.render_profile === "tug") add("3D deck", "Tug wheelhouse / towing winch (illustrative)");
            else if (props.render_profile === "service") add("3D deck", "Neutral service craft cabin / work deck (illustrative)");
            else if (props.render_profile === "workboat") add("3D deck", "Generic workboat deck / equipment (illustrative)");
            else if (props.render_profile === "pushboat") add("3D deck", "Pushboat cabin / push knees (illustrative)");
            else if (props.render_profile === "barge_cargo") add("3D deck", "Low freight barge / hatches (illustrative)");
            else if (props.render_profile === "barge_tanker") add("3D deck", "Low tank barge / pipes (illustrative)");
            else if (props.render_profile === "convoy_cargo" || props.render_profile === "convoy_tanker")
                add("3D deck", "Push convoy sections (schematic; arrangement unknown)");
            else if (props.render_profile === "police") add("3D deck", "Police patrol cabin / blue markings (illustrative)");
            else if (props.render_profile === "watertaxi") add("3D deck", "Black/yellow MSTX fast water taxi (illustrative)");
            else if (props.render_profile === "krve") add("3D deck", "KRVE mooring / pilot-transport craft (illustrative)");
            else if (props.render_profile === "port_authority") add("3D deck", "Rotterdam Port Authority patrol / rescue boat (illustrative)");
            else if (props.render_profile === "pleasure") {
                add("3D deck", "Class B pleasure craft / low cabin (illustrative)");
                if (props.hull_available) add("3D hull",
                    props.hull_geometry_source === "AIS dimensions"
                    ? "Real AIS dimensions"
                    : "Illustrative Class B hull (not measured)");
                if (props.hull_bearing_approximate) add("3D orientation",
                    "Approximate: AIS course or neutral north-up");
            }
            if (props.hull_geometry_source && props.hull_geometry_source !== "AIS dimensions" && props.render_profile !== "pleasure")
                add("3D hull data", props.hull_geometry_source);
            if (props.hull_bearing_approximate && props.render_profile !== "pleasure")
                add("3D orientation", props.render_profile === "tug"
                    ? "Approximate: AIS course or neutral north-up; not true heading"
                    : "Based on AIS course; may differ from true heading");
            add("Class", AIS_CLASS_NAMES[props.shipclass] || "Unknown");
            if (props.render_profile !== "ais_helicopter")
                add("Ship type", props.shiptype);
            if (props.special_profile_evidence)
                add("3D vessel identification", props.special_profile_evidence);
                if (props.inland_type_name) add("Inland AIS / ERI",
                    props.inland_type_code + " · " + props.inland_type_name);
                if (Number.isInteger(props.inland_convoy_barges) && props.inland_convoy_barges > 0)
                    add("ERI barges", (props.inland_type_code === 8290
                        || props.inland_type_code === 8390 ? "9 or more"
                        : String(props.inland_convoy_barges))
                        + " · actual arrangement unknown; 3D is schematic");
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
            if (props.is_helicopter) add("Aircraft class", "Helicopter");
            add("Aircraft", props.description);
            add("Operator", props.operator);
            add("Squawk", props.squawk);
            add("Category", props.category);
            add("Vertical rate", props.baro_rate, " ft/min");
            add("Altitude", props.altitude_ft, " ft");
            add("3D display", "Aircraft raised for visibility; height is illustrative");
            if (props.altitude_band === "unknown") add("Altitude colour", "Unknown");
            else add("Altitude colour", props.altitude_band);
        }
        add("Course/track", props.course_known ? props.course : "Not reported",
            props.course_known ? "°" : "");
        add("Ground speed", props.speed_knots, " kn");
        add("Last position", props.age_seconds, " s ago");
        if (photo) {
            // Keep all image lookups click-only. If the SDRCC server cannot
            // contact Planespotters, try their browser API just like tar1090.
            const hints = (props.registration ? "&reg=" + encodeURIComponent(props.registration) : "")
                + (props.aircraft_type ? "&icaoType=" + encodeURIComponent(props.aircraft_type) : "");
            const suffix = hints ? "?" + hints.slice(1) : "";
            // The official Planespotters API often serves thumbnails from
            // t.plnspttrs.net (NOT planespotters.net). Previously ALL those
            // valid URLs were rejected, both server-side and in the browser.
            const trusted = (url, isImage = false) => typeof url === "string"
                && (/^https:\/\/(?:[a-z0-9-]+\.)*planespotters\.net(?:\/|$)/i.test(url)
                    || (isImage && /^https:\/\/t\.plnspttrs\.net(?:\/|$)/i.test(url)));
            const photoPage = "https://www.planespotters.net/hex/" + props.id;
            const photoUnavailable = () => {
                photo.textContent = "Photo cannot be loaded here. ";
                const link = document.createElement("a");
                link.href = photoPage;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = "View aircraft photos on Planespotters.net";
                photo.appendChild(link);
            };
            const fallbackPhoto = () => fetch("https://api.planespotters.net/pub/photos/hex/"
                + encodeURIComponent(props.id) + suffix)
                .then(response => response.ok ? response.json() : null)
                .then(data => {
                    for (const entry of Array.isArray(data?.photos) ? data.photos.slice(0,5) : []) {
                        const src = [entry?.thumbnail_large?.src, entry?.thumbnail?.src]
                            .find(url => trusted(url, true));
                        if (!src) continue;
                        return {ok:true,image_url:src,source:"Planespotters.net",
                            source_url:trusted(entry.link) ? entry.link : "",
                            photographer:String(entry.photographer || "").slice(0,90)};
                    }
                    return null;
                });
            void fetch("/api/map-lab/aircraft-photo/" + encodeURIComponent(props.id) + suffix)
                .then(response => response.ok ? response.json() : null)
                .catch(() => null)
                .then(result => result?.ok && trusted(result.image_url,true)
                    ? result : fallbackPhoto().catch(() => null))
                .then(result => {
                    photo.textContent = "";
                    if (!result?.ok || !trusted(result.image_url,true)) {
                        photoUnavailable();
                        return;
                    }
                    const img = document.createElement("img");
                    img.src = result.image_url;
                    img.alt = "Aircraft photograph";
                    img.loading = "lazy";
                    img.referrerPolicy = "no-referrer";
                    img.onerror = () => {
                        img.remove();
                        // Retry the official public API if the server's image URL fails.
                        fallbackPhoto().catch(() => null).then(alternative => {
                            if (!alternative?.ok || !trusted(alternative.image_url, true)
                                    || alternative.image_url === result.image_url) {
                                photo.textContent = "";
                                photoUnavailable();
                                return;
                            }
                            img.onerror = () => { photo.textContent = ""; photoUnavailable(); };
                            img.src = alternative.image_url;
                            photo.prepend(img);
                        });
                    };
                    photo.appendChild(img);
                    const sourceUrl = trusted(result.source_url) ? result.source_url : "";
                    const credit = document.createElement(sourceUrl ? "a" : "div");
                    credit.textContent = "Photo: " + (result.photographer || "Planespotters.net");
                    if (sourceUrl) {
                        credit.href = sourceUrl;
                        credit.target = "_blank";
                        credit.rel = "noopener noreferrer";
                    }
                    photo.appendChild(credit);
                })
                .catch(() => {photoUnavailable();});
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
    function spritePlane(unknownCourse = false, color = "#ffbd73") {
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
        ctx.fillStyle = color;
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
    function spriteHelicopter(unknownCourse = false, color = "#ffbd73") {
        // AIS-Catcher-inspired TOP-DOWN helicopter silhouette (nose points north).
        // No round badge: rotor, fuselage, tail and skids remain identifiable.
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 96;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas 2D context is unavailable");
        ctx.scale(2, 2);
        ctx.lineJoin = "round"; ctx.lineCap = "round";
        ctx.shadowColor = "rgba(0,0,0,.8)"; ctx.shadowBlur = 2;
        ctx.strokeStyle = "#11283b"; ctx.lineWidth = 2.8;
        ctx.fillStyle = color;
        // Tail boom, tail fins and tail rotor.
        ctx.beginPath(); ctx.moveTo(22,28); ctx.lineTo(22,43);
        ctx.moveTo(16,40); ctx.lineTo(28,40);
        ctx.moveTo(18,35); ctx.lineTo(26,35); ctx.stroke();
        // Fuselage and cockpit, with nose pointing up.
        ctx.beginPath(); ctx.moveTo(22,6);
        ctx.bezierCurveTo(13,10,13,20,17,27);
        ctx.quadraticCurveTo(22,32,27,27);
        ctx.bezierCurveTo(31,20,31,10,22,6);
        ctx.closePath(); ctx.fill(); ctx.stroke();
        // Main rotor spans the helicopter width.
        ctx.lineWidth = 3.5;
        ctx.beginPath();ctx.moveTo(3,19);ctx.lineTo(41,19);ctx.stroke();
        // Contrasting cockpit glazing.
        ctx.shadowColor = "transparent";
        ctx.fillStyle = "#14344c";
        ctx.beginPath(); ctx.moveTo(22,9);
        ctx.quadraticCurveTo(15,12,18,18);
        ctx.lineTo(26,18); ctx.quadraticCurveTo(29,12,22,9);
        ctx.fill();
        if (unknownCourse) {
            ctx.fillStyle="#122d40";ctx.strokeStyle="#fff";ctx.lineWidth=1;
            ctx.beginPath();ctx.arc(39,39,6,0,Math.PI*2);ctx.fill();ctx.stroke();
            ctx.fillStyle="#fff";ctx.font="bold 10px system-ui,sans-serif";
            ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText("?",39,39);
        }
        return ctx.getImageData(0,0,96,96);
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
        for (const [band,color] of Object.entries(AIR_ALTITUDE_COLORS)) {
            for (const noCourse of [false,true]) {
                const suffix = "-alt-" + band + (noCourse ? "-no-course" : "");
                map.addImage("sdrcc-plane"+suffix,
                    spritePlane(noCourse,color), {pixelRatio:2});
                map.addImage("sdrcc-helicopter"+suffix,
                    spriteHelicopter(noCourse,color), {pixelRatio:2});
            }
        }
        // AIS class 10 is a reported helicopter target, not a ship:
        // use the same rotor silhouette, in the established AIS class colour.
        map.addImage("sdrcc-ais-helicopter",
            spriteHelicopter(false, AIS_CLASS_COLORS[10]), {pixelRatio:2});
        map.addImage("sdrcc-ais-helicopter-unverified",
            spriteHelicopter(false, "#d19b67"), {pixelRatio:2});
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
                    ["==", ["get", "render_profile"], "pleasure"], "#29475b",
                    ["==", ["get", "render_profile"], "service"], "#345368",
                    ["==", ["get", "render_profile"], "workboat"], "#4a5b69",
                    ["==", ["get", "render_profile"], "pushboat"], "#305366",
                    ["==", ["get", "render_profile"], "offshore_supply"], "#274d61",
                    ["==", ["get", "render_profile"], "research_vessel"], "#365a70",
                    ["==", ["get", "render_profile"], "cable_vessel"], "#3c626b",
                    ["==", ["get", "render_profile"], "offshore_construction"], "#37566c",
                    ["==", ["get", "render_profile"], "crane_ship"], "#4d6570",
                    ["==", ["get", "render_profile"], "container"], "#244d68",
                    ["==", ["get", "render_profile"], "container_barge"], "#3b5b69",
                    ["==", ["get", "render_profile"], "bulk"], "#516171",
                    ["==", ["get", "render_profile"], "gas_tanker"], "#527c89",
                    ["==", ["get", "render_profile"], "gas_barge"], "#647b83",
                    ["==", ["get", "render_profile"], "powder_tanker"], "#6a7a82",
                    ["==", ["get", "render_profile"], "powder_barge"], "#778187",
                    ["==", ["get", "render_profile"], "chemical_tanker"], "#306376",
                    ["==", ["get", "render_profile"], "chemical_barge"], "#55737b",
                    ["==", ["get", "render_profile"], "water_supply"], "#255568",
                    ["==", ["get", "render_profile"], "bunker"], "#2e5d65",
                    ["==", ["get", "render_profile"], "ferry"], "#3c6482",
                    ["==", ["get", "render_profile"], "cruise"], "#e2e4e0",
                    ["==", ["get", "render_profile"], "catamaran"], "#305573",
                    ["==", ["get", "render_profile"], "fishing"], "#4c6373",
                    ["==", ["get", "render_profile"], "sailing"], "#2b6670",
                    ["==", ["get", "render_profile"], "pilot"], "#294b69",
                    ["==", ["get", "render_profile"], "rescue"], "#d06e28",
                    ["==", ["get", "render_profile"], "port_service"], "#2c5673",
                    ["==", ["get", "render_profile"], "oil_response"], "#486b66",
                    ["==", ["get", "render_profile"], "dredger"], "#696653",
                    ["==", ["get", "render_profile"], "crane_workboat"], "#5c6470",
                    ["==", ["get", "render_profile"], "barge_cargo"], "#3d5664",
                    ["==", ["get", "render_profile"], "barge_tanker"], "#4c626a",
                    ["==", ["get", "render_profile"], "convoy_cargo"], "#315164",
                    ["==", ["get", "render_profile"], "convoy_tanker"], "#385963",
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
                    "psv-workdeck","#597487","psv-safety-rail","#e6c653",
                    "psv-wheelhouse","#f1f5f6","psv-bridge-roof","#f2f3ed",
                    "psv-bridge-upper","#dfeaf0","psv-bridge-glass","#20779e",
                    "psv-side-windows","#2984a9","psv-upper-windows","#2b85ad",
                    "psv-mast","#f3c858","psv-deck-gear","#e3bb64",
                    "research-workdeck","#7297aa","research-laboratory","#ecf3f2",
                    "research-windows","#58a0ba","research-mast","#ffcc60",
                    "cable-workdeck","#638890","cable-wheelhouse","#e1e9ea",
                    "cable-reel","#c4a56d","cable-reel-rim","#dfc58d",
                    "cable-stern-chute","#ebaf63",
                    "construction-deck","#6a8795","construction-wheelhouse","#dae5eb",
                    "construction-crane-tower","#efc05d",
                    "construction-crane-boom","#f3d478",
                    "construction-equipment","#929da2",
                    "container-bridge","#e3e7dd",
                    "container-blue","#376d91","container-rust","#bb694e",
                    "container-white","#dce7e4","container-top","#6a9cac",
                    "water-deck","#638c91","water-house","#e4eceb",
                    "water-windows","#173b50","water-roof","#eaf3f3",
                    "water-pipe","#73c9e6","water-hatch","#b4c8c9",
                    "water-pump","#4eaac7","water-hose","#253b47",
                    "tanker-bridge","#dbe8ec",
                    "gas-vessel-tank","#c9e0e4","powder-silo","#d9d4c6",
                    "chemical-tank","#b4d6d5","chemical-valve","#e3a95e",
                    "bunker-tank","#9eb8b7","bunker-hose","#c7b36a",
                    "bunker-pump","#d8cb9d",
                    "bulk-bridge","#e7e4de","bulk-hatch","#8fa2a8",
                    "ferry-car-deck","#a3c2cf","ferry-passenger-cabin","#e8f4f5",
                    "ferry-roof","#d8edf0","ferry-rail","#f2c752",
                    "cruise-deck","#d8e6ed","cruise-hotel","#faf7f0",
                    "cruise-sundeck","#e8cc9e","cruise-windows","#5f9da9",
                    "cruise-upper-windows","#87c0d4",
                    "catamaran-sponson","#527c92","catamaran-deck","#dbe6e9",
                    "catamaran-cabin","#f5f8fa",
                    "sailing-cabin","#f3eee3","sailing-mast","#b3bec8",
                    "sailing-sail","#f9faf5",
                    "fishing-wheelhouse","#dce6ed","fishing-workdeck","#788e92",
                    "fishing-gantry","#c8aa76",
                    "crane-tower","#e3b453","crane-boom","#e6b95d",
                    "dredger-hopper","#878b7d","dredger-pipe","#aeb9ae",
                    "pilot-band","#f5c63d","rescue-band","#ed802e",
                    "rescue-beacon","#eaf3fe","port-service-band","#f4bf47",
                    "oil-response-band","#77b29e","oil-response-gear","#c8a874",
                    "service-workdeck","#6d8694","service-cabin","#d7e4ed",
                    "service-roof","#a5bfca","service-windows","#4a9ac2",
                    "barge-rim","#8aa1ad","barge-hatch","#7c939e","barge-pipe","#9ec5ca",
                    "convoy-pusher-house","#b7c9d3","convoy-coupling","#dfad6c",
                    "convoy-cargo-bay","#718b9d","convoy-tank-bay","#9db8c2",
                    "pushboat-wheelhouse","#d7e7ee","pushboat-push-knees","#e9b867",
                    "workboat-deck","#7e9b9c","workboat-cabin","#d9e2e2",
                    "workboat-equipment","#c8ac75",
                    "passenger-lower-deck","#e9f0f5",
                    "passenger-upper-deck","#f7f9fc",
                    "passenger-roof","#d9e7ec",
                    "passenger-windows","#338ab3",
                    "passenger-upper-windows","#6ebdda",
                    "passenger-bridge","#cde5ef",
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
                    "pleasure-deck","#e5e8e2","pleasure-cabin","#f7f8f3",
                    "pleasure-windshield","#7fa8bd","pleasure-cockpit","#7b94a4",
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
                showSingleMapPopup(event,position,popup(feature),
                    {offset:12,maxWidth:"350px"});
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
            // Helicopter is a *side-on badge*, so keep it upright to
            // remain recognizable instead of spinning into a thin cross.
            "icon-rotate": kind === "ais"
                ? ["case", ["==", ["get", "render_profile"], "ais_helicopter"],
                        ["coalesce", ["get", "course"], 0],
                    ["get", "is_offshore_structure"], 0,
                    ["get", "is_moving"], ["coalesce", ["get", "course"], 0], 0]
                : ["case", ["get", "is_helicopter"],
                    ["coalesce", ["get", "course"], 0],
                    ["coalesce", ["get", "course"], 0]],
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
                    ? AIS_NAME_PLATE_IMAGE : ["get", "icon_name"],
                "icon-text-fit": kind === "ais" ? "both" : "none",
                "icon-text-fit-padding": kind === "ais" ? [2, 4, 2, 4] : [0, 0, 0, 0],
                // A small plate is easier to read than a large label over the hull.
                "text-size": kind === "ais"
                    ? AIS_NAME_2D_TEXT_SIZE
                    : ["interpolate", ["linear"], ["zoom"], 11, 9, 16, 10.5],
                // MapLibre can try adjacent positions instead of covering the
                // ship's own icon/real-scale hull or hiding the vessel entirely.
                "text-variable-anchor": kind === "ais"
                    ? AIS_NAME_2D_ANCHORS : ["top", "bottom", "right", "left"],
                "text-justify": "auto",
                "text-radial-offset": kind === "ais"
                    ? AIS_NAME_2D_OFFSET : 1.2,
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
                    ? AIS_NAME_2D_TEXT_COLOR : "#ffffff",
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
                showSingleMapPopup(event,feature.geometry.coordinates,
                    popup(feature),{offset:12,maxWidth:"300px"});
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
        const atisRetained = Boolean(atisTarget);
        // The last validated ATIS match is intentionally kept on this map
        // until another verified ATIS/AIS match replaces it. The original
        // 30-second deadline still distinguishes live from historical state.
        // Avoid re-uploading empty GeoJSON or repainting an idle map every 650 ms.
        if (!emergencyActive && !atisRetained
                && !previouslyDrawnEmergency && !previouslyDrawnAtis) {
            el("emergency-status").textContent = "None active";
            el("atis-status").textContent = "No active match";
            return;
        }
        const shipsByMmsi = new Map(latestShips.map(ship => [String(ship.id), ship]));
        const points = (rows, category, retainLast = false) => rows.filter(row =>
            retainLast || now < row.expiresAt)
            .filter(row => /^\d{9}$/.test(row.mmsi))
            .map(row => {
                const ship = shipsByMmsi.get(row.mmsi);
                // Prefer current AIS positions for alert rings and optional auto-center.
                const latitude = ship?.lat ?? row.latitude;
                const longitude = ship?.lon ?? row.longitude;
                return {type:"Feature", geometry:{
                    type:"Point", coordinates:[longitude, latitude],
                }, properties:{mmsi:row.mmsi, category:row.category || category}};
            });
        const emergencies = points(emergencyTargets, "emergency");
        const atis = points(atisTarget ? [atisTarget] : [], "atis", true);
        previouslyDrawnEmergency = emergencies.length;
        previouslyDrawnAtis = atis.length;
        map.getSource("sdrcc-emergency").setData({type:"FeatureCollection",features:emergencies});
        map.getSource("sdrcc-atis").setData({type:"FeatureCollection",features:atis});
        el("emergency-status").textContent = emergencies.length
            ? emergencies.length + " highlighted" : "None active";
        el("atis-status").textContent = atis.length
            ? (now < atisTarget.expiresAt ? "ATIS matched" : "Last ATIS match")
            : "No active match";
        // Subtle pulse, matching AIS-Catcher emergency and ATIS colours.
        const phase = (Math.sin(now / 1350 * Math.PI * 2) + 1) / 2;
        if (emergencies.length && el("layer-emergency").checked) {
            map.setPaintProperty("sdrcc-emergency-ring","circle-radius", 11 + phase * 6);
        }
        if (atis.length && el("layer-atis").checked) {
            map.setPaintProperty("sdrcc-atis-ring","circle-radius", 12 + phase * 6);
        }
    }
    function focusNewAtisMatch(match) {
        if (!match || !atisAutoFocus || !el("layer-atis").checked || !loaded
                || Date.now() >= match.expiresAt) return;
        // Focus once per received ATIS event, even if the same vessel speaks
        // again; do not refocus old retained highlights or repeated polls.
        const eventKey = String(match.event_id || (match.mmsi + ":" +
            String(match.atis_code || "")));
        if (eventKey === lastFocusedAtisEvent) return;
        lastFocusedAtisEvent = eventKey;
        // Highlight API uses longitude/latitude, unlike AIS traffic's lon/lat.
        const ship = latestShips.find(row => String(row.id) === match.mmsi);
        const lon = Number.isFinite(ship?.lon) ? ship.lon : match.longitude;
        const lat = Number.isFinite(ship?.lat) ? ship.lat : match.latitude;
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
        map.easeTo({center:[lon, lat], zoom:atisFocusZoom, duration:1400});
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
            // API only reports fresh, validated Marine ATIS/AIS matches.
            // Do not erase the last match when the backend's 30s TTL ends.
            // The last known matched vessel remains ringed (and pulsing) until
            // a different reception event passes the same strict validation.
            if (match && /^\d{9}$/.test(String(match.mmsi || ""))
                    && typeof match.event_id === "string" && match.event_id.length > 0
                    && validHighlightLocation(match)
                    && Number.isFinite(match.remaining_seconds)
                    && match.remaining_seconds > 0 && match.remaining_seconds <= 30
                    && match.event_id !== atisTarget?.event_id) {
                atisTarget = {...match, mmsi:String(match.mmsi),
                    expiresAt:now + match.remaining_seconds * 1000};
            }
        } catch (_) {
            // Never create an unverified highlight during an API failure.
            // Emergency deadlines still expire; an already validated last
            // ATIS ring remains as historical map context.
        } finally {
            overlayBusy = false;
            tickHighlights();
            focusNewAtisMatch(atisTarget);
            void refreshSpeakerPhoto(atisTarget);
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
                showSingleMapPopup(event,coords,div,{offset:12});
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
                map.getSource("sdrcc-offshore-3d").setData(offshore3dCollection(ships));
                map.getSource("sdrcc-adsb").setData(makeGeoJson(planes));
                map.getSource("sdrcc-adsb-air-3d").setData(aircraft3dCollection(planes,"adsb"));
                map.getSource("sdrcc-ais-air-3d").setData(aircraft3dCollection(ships,"ais"));
                if (el("layer-tracks").checked && Date.now()-lastTrackFetchAt > 30000)
                    void loadAllTracks();
                refreshStation(data.station);
                latestShips = ships;
                if (atisTarget && speakerVisible) void refreshSpeakerPhoto(atisTarget);
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
        addOffshore3dLayer();
        addPoints("ais");
        addPoints("adsb");
        addAircraft3dLayers();
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
    // Zoom changes the label style only when crossing the close-up
    // threshold, never on every frame; 2D always keeps normal nameplates.
    map.on("zoom", () => {
        if (loaded && mode3d) updateAisNamePresentation();
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
        try { window.localStorage.setItem(trackEnabledKey,
            el("layer-tracks").checked ? "1" : "0"); }
        catch (_) { /* Browser storage is optional. */ }
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
    el("atis-auto-focus").addEventListener("change", () => {
        atisAutoFocus = el("atis-auto-focus").checked;
        try {window.localStorage.setItem(atisFollowKey, atisAutoFocus ? "1" : "0");}
        catch (_) { /* Optional storage. */ }
        if (atisAutoFocus) focusNewAtisMatch(atisTarget);
    });
    el("atis-focus-zoom").addEventListener("input", () => {
        el("atis-focus-zoom-value").textContent = el("atis-focus-zoom").value;
    });
    el("atis-focus-zoom").addEventListener("change", () => {
        atisFocusZoom = Math.max(11, Math.min(18, Number(el("atis-focus-zoom").value) || 15));
        el("atis-focus-zoom").value = String(atisFocusZoom);
        el("atis-focus-zoom-value").textContent = String(atisFocusZoom);
        try {window.localStorage.setItem(atisZoomKey, String(atisFocusZoom));}
        catch (_) { /* Optional storage. */ }
    });
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
