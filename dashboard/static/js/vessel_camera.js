(() => {
    "use strict";
    const byId = id => document.getElementById(id);
    let current = null;
    // Only public provider pages, never an AIS-supplied URL or signed HLS token.
    function safeCamera(camera) {
        if (!camera || !/^\d{9}$/.test(String(camera.mmsi || ""))) return null;
        try {
            const url = new URL(camera.page_url);
            if (url.origin !== "https://webcam-binnenvaart.nl" || url.username || url.password
                    || url.search || url.hash || !/^\/pages\/cam-[a-z0-9-]+\.php$/i.test(url.pathname)) return null;
            return {...camera, page_url: url.href};
        } catch (_) { return null; }
    }
    function unload() {
        byId("vessel-camera-player")?.replaceChildren();
    }
    function close() {
        unload();
        const dialog = byId("vessel-camera-dialog");
        if (dialog?.open) dialog.close();
    }
    function open(camera) {
        camera = safeCamera(camera);
        const dialog = byId("vessel-camera-dialog");
        const holder = byId("vessel-camera-player");
        if (!camera || !dialog || !holder) return;
        unload();
        byId("vessel-camera-title").textContent = camera.shipname + " · onboard camera";
        byId("vessel-camera-identity").textContent = "MMSI " + camera.mmsi + " · Webcam Binnenvaart";
        byId("vessel-camera-source").href = camera.page_url;
        const frame = document.createElement("iframe");
        frame.title = "Webcam Binnenvaart — " + camera.shipname;
        frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox");
        frame.setAttribute("allow", "autoplay; fullscreen; picture-in-picture");
        frame.setAttribute("allowfullscreen", "");
        frame.referrerPolicy = "strict-origin-when-cross-origin";
        // Keep the complete original player and its attribution. The fragment
        // scrolls the provider page to its video, without scraping or rehosting.
        frame.src = camera.page_url + "#my-video";
        holder.appendChild(frame);
        if (!dialog.open) dialog.showModal();
    }
    function render(payload) {
        const marine = payload?.selected_mode === "marine_ais" && payload?.service?.active;
        const match = payload?.ais_match;
        current = marine && match?.matched === true
            && String(match.mmsi) === String(payload.vessel_camera?.mmsi)
            ? safeCamera(payload.vessel_camera) : null;
        const button = byId("traffic-voice-vessel-camera");
        if (button) button.hidden = !current;
        if (!marine) close();
        // An explicitly opened camera remains on that named ship when another
        // ATIS arrives. Never silently switch a viewer to another vessel.
    }
    function addHistoryButton(holder, camera) {
        camera = safeCamera(camera);
        if (!camera) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "traffic-voice-map-button vessel-camera-history-button";
        button.textContent = "📹 Onboard camera";
        button.addEventListener("click", () => open(camera));
        holder.appendChild(button);
    }
    function initialize() {
        byId("traffic-voice-vessel-camera")?.addEventListener("click", () => open(current));
        byId("vessel-camera-close")?.addEventListener("click", close);
        byId("vessel-camera-dialog")?.addEventListener("close", unload);
        byId("vessel-camera-dialog")?.addEventListener("cancel", close);
        document.addEventListener("visibilitychange", () => {if (document.hidden) close();});
        window.addEventListener("pagehide", close);
    }
    window.sdrccVesselCamera = {render, addHistoryButton, close};
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, {once:true});
    else initialize();
})();
