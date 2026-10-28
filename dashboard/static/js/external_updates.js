(() => {
    "use strict";
    const panel = document.getElementById("external-updates");
    const table = document.getElementById("external-update-list");
    const refresh = document.getElementById("external-update-check");
    const result = document.getElementById("external-update-result");
    const badge = document.getElementById("external-update-badge");
    const subtitle = document.getElementById("external-update-summary-detail");
    if (!panel || !table || !refresh || !result || !badge || !subtitle) return;

    const ACTIVE = new Set(["queued", "starting", "backing_up",
        "installing", "verifying", "restoring"]);
    const INSTALLABLE = new Set(["ais-catcher", "satdump", "readsb", "rtl-airband"]);
    let pending = false;
    let starting = false;
    let activeWorker = false;
    let lastSignature = null;

    function node(tag, className, value) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (value !== undefined) element.textContent = String(value);
        return element;
    }

    function stateOf(item) {
        // The backend knows whether a source-based version can be verified.
        // Never infer UP TO DATE merely because a GitHub release was fetched.
        if (["current", "update", "review", "manual", "missing", "ahead"].includes(item.status))
            return item.status;
        if (item.available) return item.can_install ? "update" : "review";
        if (!item.installed) return "missing";
        return item.reason === "Up to date" ? "current" : "manual";
    }
    const STATUS_LABEL = {
        current: "UP TO DATE",
        update: "UPDATE AVAILABLE",
        review: "REVIEW REQUIRED",
        manual: "MANUAL CHECK",
        missing: "NOT INSTALLED",
        ahead: "AHEAD OF STABLE",
    };
    function message(value, kind = "") {
        if (result.textContent !== value) result.textContent = value;
        const style = "control-result" + (kind ? " " + kind : "");
        if (result.className !== style) result.className = style;
    }

    function render(data) {
        const worker = data.worker || {};
        const rows = data.software || [];
        const workerBusy = ACTIVE.has(worker.state);
        const signature = JSON.stringify({
            rows: rows.map(item => [item.id, item.name, item.installed,
                item.latest, item.available, item.can_install, item.status,
                item.source, item.reason, item.url]),
            state: worker.state, software: worker.software, message: worker.message,
            error: data.release_check_error,
            errors: data.release_check_errors,
        });
        // Never rebuild cards on the periodic status poll if their data is
        // unchanged. Replacing buttons every five seconds caused visible flashes.
        if (signature === lastSignature) return;
        lastSignature = signature;
        activeWorker = workerBusy;

        const counts = {current: 0, update: 0, review: 0, manual: 0, missing: 0, ahead: 0};
        const cards = [];
        for (const item of rows) {
            const state = stateOf(item);
            counts[state] += 1;
            const card = node("article", "external-update-row is-" + state);
            card.dataset.software = item.id;
            const head = node("div", "external-update-row-heading");
            head.append(node("strong", "", item.name));
            head.append(node("span", "external-update-state", STATUS_LABEL[state]));
            const latestKind = item.id === "readsb" ? "Latest dev" :
                (item.id === "satdump" || item.id === "rtl-airband") ? "Latest stable" :
                    "Latest release";
            const version = node("p", "external-update-versions",
                "Installed: " + (item.installed || "Not detected") +
                (item.latest ? "   ·   " + latestKind + ": " + item.latest : ""));

            const note = node("p", "external-update-note",
                item.reason || item.source || "Version cannot be checked automatically");
            note.title = item.source || "";
            const actions = node("div", "external-update-actions");
            if (item.url && /^https:\/\/github\.com\//.test(item.url)) {
                const notes = node("a", "external-update-release",
                    item.id === "readsb" ? "Upstream dev" : "Release notes");
                notes.href = item.url;
                notes.target = "_blank";
                notes.rel = "noopener noreferrer";
                actions.append(notes);
            }
            // No empty, disabled, blue update buttons: show an action only
            // for a genuine, installable release.
            if (state === "update" && INSTALLABLE.has(item.id)) {
                const install = node("button", "control-button", "⬆ Install " + item.latest);
                install.type = "button";
                install.disabled = workerBusy;
                install.addEventListener("click", () => start(item));
                actions.append(install);
            }
            card.append(head, version, note, actions);
            cards.push(card);
        }
        table.replaceChildren(...cards);
        refresh.disabled = workerBusy || starting;

        let summary, summaryKind;
        if (workerBusy) {
            summary = "UPDATING";
            summaryKind = "review";
            subtitle.textContent = "Installing " + (worker.software || "external software") + "…";
        } else if (worker.state === "failed" || worker.state === "interrupted") {
            summary = "UPDATE FAILED";
            summaryKind = "error";
            subtitle.textContent = "Last update needs attention · open for details";
        } else if (counts.update) {
            summary = counts.update + " UPDATE" + (counts.update === 1 ? "" : "S") + " AVAILABLE";
            summaryKind = "update";
            subtitle.textContent = counts.current + " up to date · " +
                counts.update + " ready to install · " +
                (counts.manual + counts.review) + " manual/review · " + counts.ahead + " ahead of stable";
        } else if (counts.review) {
            summary = "REVIEW REQUIRED";
            summaryKind = "review";
            subtitle.textContent = counts.current + " up to date · " +
                counts.review + " update(s) need review · " + counts.ahead + " ahead of stable";
        } else if (counts.current === rows.length && rows.length > 0) {
            summary = "ALL UP TO DATE";
            summaryKind = "current";
            subtitle.textContent = "All " + rows.length + " installed tools are current";
        } else {
            const limited = (counts.manual + counts.missing) > 0;
            summary = limited ? "CHECK LIMITED" : "NO UPDATES FOUND";
            summaryKind = limited ? "review" : "current";
            subtitle.textContent = counts.current + " up to date · " + counts.ahead + " ahead of stable · " +
                (counts.manual + counts.missing) + " need verification";
        }
        badge.textContent = summary;
        badge.className = "external-update-summary-state is-" + summaryKind;

        if (workerBusy) {
            message(worker.message || "External software update in progress…", "warn");
        } else if (worker.state === "failed" || worker.state === "interrupted") {
            message("Last " + (worker.software || "external") + " update failed: " +
                (worker.message || "Check backup and logs."), "bad");
        } else if (worker.state === "success") {
            message(worker.message || "External update completed.", "ok");
        } else if (data.release_check_errors &&
                   Object.keys(data.release_check_errors).length) {
            message("Some upstream version checks are unavailable. See each software card.", "warn");
        } else {
            message("No automatic installations. Open release notes to review changes.");
        }
    }

    async function load(manual = false) {
        if (pending || starting) return;
        pending = true;
        if (manual) refresh.disabled = true;
        try {
            const response = await fetch("/api/external-updates" +
                (manual ? "?refresh=1" : ""), {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || !data.ok) throw Error("External status unavailable");
            render(data);
        } catch (error) {
            badge.textContent = "CHECK FAILED";
            badge.className = "external-update-summary-state is-error";
            subtitle.textContent = "Update check failed · open for details";
            message("External update check failed: " + error.message, "bad");
            lastSignature = null;
        } finally {
            pending = false;
            refresh.disabled = activeWorker || starting;
        }
    }

    async function start(item) {
        if (starting || activeWorker || !item.can_install ||
                !INSTALLABLE.has(item.id)) return;
        const impact = {
            "ais-catcher": "AIS sharing will stop temporarily; SDRCC backs up the configuration and restores the service state.",
            "satdump": "Only the Ubuntu APT package will be updated. Active satellite missions must finish first.",
            "readsb": "Stop ADS-B first. SDRCC backs up your existing readsb executable and settings, builds the verified 3.16.20 version and restores the old binary if verification fails. SDRCC will not restart receiver hardware.",
            "rtl-airband": "Stop Traffic Voice first. SDRCC builds 6.2.0 with Auto Gain and scan interval patches; previous binary and settings are backed up.",
        }[item.id];
        if (!window.confirm("Install " + item.name + " " + item.latest + "?\n\n" +
                impact + "\n\nA package rollback cannot always be guaranteed. Continue?")) return;
        starting = true;
        refresh.disabled = true;
        message("Starting " + item.name + " update…", "warn");
        try {
            const response = await fetch("/api/external-updates/install", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({software: item.id}),
            });
            const data = await response.json();
            if (!response.ok || !data.ok)
                throw Error(data.message || "External update rejected");
            message(data.message || "External update started.", "warn");
        } catch (error) {
            message("Update could not start: " + error.message, "bad");
        } finally {
            starting = false;
            lastSignature = null;
            await load();
        }
    }

    refresh.addEventListener("click", () => load(true));
    load();
    // Poll worker status while keeping DOM stable. Remote AIS release checks
    // remain cached by the backend; this does not create/reflash controls.
    setInterval(() => load(), 12000);
})();
