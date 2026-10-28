(() => {
    "use strict";
    const table = document.getElementById("external-update-list");
    const refresh = document.getElementById("external-update-check");
    const result = document.getElementById("external-update-result");
    const badge = document.getElementById("external-update-badge");
    if (!table || !refresh || !result || !badge) return;
    const ACTIVE = new Set(["queued", "starting", "backing_up",
        "installing", "verifying", "restoring"]);
    const labels = {
        "ais-catcher": "AIS-catcher",
        "satdump": "SatDump",
    };
    let busy = false;
    let pending = false;

    function node(tag, cls, value) {
        const el = document.createElement(tag);
        if (cls) el.className = cls;
        if (value !== undefined) el.textContent = String(value);
        return el;
    }
    function message(value, kind = "") {
        result.textContent = value;
        result.className = "control-result" + (kind ? " " + kind : "");
    }
    async function load(force = false) {
        if (pending) return;
        pending = true;
        refresh.disabled = true;
        try {
            const response = await fetch("/api/external-updates" + (force ? "?refresh=1" : ""),
                {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || !data.ok) throw Error("External status unavailable");
            const worker = data.worker || {};
            busy = ACTIVE.has(worker.state);
            table.replaceChildren();
            for (const entry of data.software || []) {
                const card = node("div", "external-update-row");
                const head = node("div", "external-update-row-heading");
                head.append(node("strong", "", entry.name));
                const status = node("span", "muted",
                    entry.can_install ? "UPDATE AVAILABLE" :
                        entry.latest && entry.installed && !/requires|outside/i.test(entry.reason || "")
                            ? "UP TO DATE" : "CHECK / MANUAL");
                head.append(status);
                const detail = node("p", "muted",
                    "Installed: " + (entry.installed || "Not detected")
                    + " · Available: " + (entry.latest || "Not checked")
                    + " · " + (entry.reason || entry.source));
                const actions = node("div", "system-maintenance-ais-actions");
                const release = node("a", "control-button", "Release information");
                release.href = entry.url;
                release.target = "_blank";
                release.rel = "noopener noreferrer";
                actions.append(release);
                if (Object.prototype.hasOwnProperty.call(labels, entry.id)) {
                    const install = node("button", "control-button", "⬆ Update " + entry.name);
                    install.type = "button";
                    install.disabled = !entry.can_install || busy;
                    install.addEventListener("click", () => start(entry));
                    actions.append(install);
                }
                card.append(head, detail, actions);
                table.append(card);
            }
            refresh.disabled = busy;
            badge.textContent = busy ? "UPDATING" :
                data.software.some(row => row.can_install) ? "UPDATES AVAILABLE" : "CHECKED";
            if (busy) message(worker.message || "External update is running...", "warn");
            else if (worker.state === "failed" || worker.state === "interrupted")
                message("Last " + (worker.software || "external") + " update failed: " +
                    (worker.message || "Check status and logs."), "bad");
            else if (worker.state === "success")
                message(worker.message || "External update completed.", "ok");
            else if (data.release_check_error)
                message("AIS release check unavailable: " + data.release_check_error +
                        ". SatDump APT status is still shown.", "warn");
            else message("Updates are never installed automatically. Verify release notes first.");
        } catch (error) {
            message("External update check failed: " + error.message, "bad");
            badge.textContent = "CHECK FAILED";
            refresh.disabled = false;
        } finally {
            pending = false;
        }
    }

    async function start(entry) {
        if (busy || !entry.can_install || !labels[entry.id]) return;
        const impact = entry.id === "ais-catcher"
            ? "AIS sharing and its web interface will stop temporarily. Your managed-mode settings and service state will be backed up and restored."
            : "SatDump will be upgraded only through the configured Ubuntu APT repositories. Active satellite missions must finish first.";
        if (!window.confirm("Update " + entry.name + " to " + entry.latest + "?\n\n"
            + impact + "\n\nA package rollback cannot always be guaranteed. Continue?")) return;
        busy = true;
        refresh.disabled = true;
        message("Starting " + entry.name + " update...", "warn");
        try {
            const response = await fetch("/api/external-updates/install", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({software: entry.id}),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw Error(data.message || "Update rejected");
            message(data.message || "External update started.", "warn");
            await load(false);
        } catch (error) {
            busy = false;
            message("Update could not start: " + error.message, "bad");
            refresh.disabled = false;
        }
    }

    refresh.addEventListener("click", () => load(true));
    load(false);
    setInterval(() => { if (!pending) load(false); }, 5000);
})();
