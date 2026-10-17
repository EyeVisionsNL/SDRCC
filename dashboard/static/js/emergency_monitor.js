(() => {
    "use strict";
    const $ = id => document.getElementById(id);
    const categories = ["lifeliner", "police_helicopter", "knrm", "waterpolitie", "p2000"];
    let busy = false;
    let loaded = false;
    const setMessage = (message, kind = "") => {
        const el = $("em-result");
        if (!el) return;
        el.textContent = message;
        el.className = "em-result " + kind;
    };
    const textArea = (field, category) => $("em-" + field + "-" + category);

    function visibility() {
        const enabled = $("em-enabled").checked;
        const mqtt = $("em-p2000-input").checked || $("em-ha").checked;
        $("em-suboptions").hidden = !enabled;
        $("em-mqtt-config").hidden = !enabled || !mqtt;
        $("em-test").hidden = !enabled || !$("em-ha").checked;
        $("em-state").textContent = enabled ? "ENABLED" : "DISABLED";
        $("em-radius-text").textContent = $("em-radius").value + " km";
    }

    function fill(settings) {
        $("em-enabled").checked = settings.enabled;
        $("em-radius").value = settings.radius_km;
        for (const category of categories) {
            $("em-cat-" + category).checked = Boolean(settings.categories?.[category]);
        }
        $("em-p2000-input").checked = settings.p2000_input;
        $("em-ha").checked = settings.ha_notifications;
        $("em-host").value = settings.mqtt_host || "";
        $("em-port").value = settings.mqtt_port || 1883;
        $("em-user").value = settings.mqtt_user || "";
        $("em-password").value = "";
        $("em-password").placeholder = settings.mqtt_password_set ? "Stored password (leave blank to keep)" : "Optional";
        $("em-tls").checked = settings.mqtt_tls;
        for (const category of ["lifeliner", "police_helicopter"]) {
            textArea("hex", category).value = (settings.aircraft_hex?.[category] || []).join(", ");
        }
        for (const category of ["knrm", "waterpolitie"]) {
            textArea("mmsi", category).value = (settings.vessel_mmsi?.[category] || []).join(", ");
        }
        visibility();
    }

    function read() {
        return {
            enabled: $("em-enabled").checked,
            radius_km: Number($("em-radius").value),
            categories: Object.fromEntries(categories.map(c => [c, $("em-cat-" + c).checked])),
            p2000_input: $("em-p2000-input").checked,
            ha_notifications: $("em-ha").checked,
            mqtt_host: $("em-host").value.trim(),
            mqtt_port: Number($("em-port").value),
            mqtt_user: $("em-user").value.trim(),
            mqtt_password: $("em-password").value,
            mqtt_tls: $("em-tls").checked,
            aircraft_hex: {
                lifeliner: textArea("hex", "lifeliner").value,
                police_helicopter: textArea("hex", "police_helicopter").value
            },
            vessel_mmsi: {
                knrm: textArea("mmsi", "knrm").value,
                waterpolitie: textArea("mmsi", "waterpolitie").value
            }
        };
    }

    function render(snapshot) {
        if (!busy && !loaded) {
            fill(snapshot.settings);
            loaded = true;
        }
        const runtime = snapshot.runtime || {};
        $("em-sources").textContent =
            "ADS-B: " + (runtime.adsb || "OFF") + "  ·  AIS: " + (runtime.ais || "OFF") +
            "  ·  P2000: " + (runtime.p2000 || "OFF") + "  ·  MQTT: " + (runtime.mqtt || "OFF");
        const list = $("em-events");
        list.replaceChildren();
        for (const event of (snapshot.events || []).slice(0, 20)) {
            const row = document.createElement("li");
            const title = document.createElement("strong");
            title.textContent = event.title || "Detection";
            const meta = document.createElement("small");
            const distance = typeof event.distance_km === "number" ? " · " + event.distance_km.toFixed(1) + " km" : "";
            meta.textContent = (event.timestamp || "").replace("T", " ").slice(0, 19) +
                " · " + (event.source || "").toUpperCase() + distance;
            row.append(title, meta);
            list.appendChild(row);
        }
        if (!list.children.length) {
            const item = document.createElement("li");
            item.textContent = "No Emergency Monitor detections recorded yet.";
            list.appendChild(item);
        }
        if (runtime.last_error) setMessage("Source warning: " + runtime.last_error, "error");
    }

    async function refresh() {
        if (!$("em-monitor") || busy) return;
        try {
            const response = await fetch("/api/emergency-monitor", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || data.ok === false) throw new Error(data.message || "Unable to read Emergency Monitor.");
            render(data);
        } catch (error) {
            setMessage(error.message, "error");
        }
    }

    async function save(event) {
        event.preventDefault();
        if (busy) return;
        busy = true;
        $("em-save").disabled = true;
        setMessage("Saving Emergency Monitor settings...");
        try {
            const response = await fetch("/api/emergency-monitor", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(read())
            });
            const data = await response.json();
            if (!response.ok || data.ok === false) throw new Error(data.message || "Save failed.");
            fill(data.settings);
            setMessage(data.settings.enabled ? "Emergency Monitor settings saved." : "Emergency Monitor disabled.", "ok");
        } catch (error) {
            setMessage(error.message, "error");
        } finally {
            busy = false;
            $("em-save").disabled = false;
            await refresh();
        }
    }

    async function test() {
        if (busy || !$("em-ha").checked || !$("em-enabled").checked) return;
        $("em-test").disabled = true;
        try {
            const response = await fetch("/api/emergency-monitor/test", {method: "POST"});
            const data = await response.json();
            if (!response.ok || data.ok === false) throw new Error(data.message || "Test failed.");
            setMessage(data.message || "MQTT test sent.", "ok");
        } catch (error) {
            setMessage(error.message, "error");
        } finally {
            $("em-test").disabled = false;
        }
    }

    function init() {
        if (!$("em-monitor")) return;
        $("em-form").addEventListener("submit", save);
        $("em-test").addEventListener("click", test);
        for (const id of ["em-enabled", "em-p2000-input", "em-ha", "em-radius"]) {
            $(id).addEventListener("change", visibility);
            $(id).addEventListener("input", visibility);
        }
        const panel = $("em-monitor").closest("details");
        panel?.addEventListener("toggle", () => {
            if (panel.open) refresh();
        });
        refresh();
        window.setInterval(() => {
            if (panel?.open) refresh();
        }, 15000);
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, {once: true});
    } else init();
})();
