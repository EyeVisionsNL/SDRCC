(() => {
    "use strict";
    const panel = document.getElementById("external-updates");
    const table = document.getElementById("external-update-list");
    const refresh = document.getElementById("external-update-check");
    const result = document.getElementById("external-update-result");
    const badge = document.getElementById("external-update-badge");
    const subtitle = document.getElementById("external-update-summary-detail");
    if (!panel || !table || !refresh || !result || !badge || !subtitle) return;

    let pending = false;
    function node(tag, className, value) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (value !== undefined) element.textContent = String(value);
        return element;
    }
    function render(data) {
        const rows = Array.isArray(data.software) ? data.software : [];
        const cards = [];
        let detected = 0, unknown = 0;
        for (const item of rows) {
            const state = ["installed", "unknown", "missing"].includes(item.status)
                ? item.status : "unknown";
            if (state === "installed") detected++;
            if (state === "unknown") unknown++;
            const card = node("article", "external-update-row is-" +
                (state === "installed" ? "current" : state === "unknown" ? "review" : "missing"));
            card.dataset.software = item.id;
            const head = node("div", "external-update-row-heading");
            head.append(node("strong", "", item.name));
            head.append(node("span", "external-update-state", {
                installed: "INSTALLED", unknown: "VERSION UNKNOWN", missing: "NOT INSTALLED",
            }[state]));
            const version = node("p", "external-update-versions",
                "Installed version: " + (item.installed || "Not detected"));
            const note = node("p", "external-update-note", item.reason || item.source || "");
            note.title = item.source || "";
            card.append(head, version, note);
            cards.push(card);
        }
        table.replaceChildren(...cards);
        badge.textContent = detected + "/" + rows.length + " DETECTED";
        badge.className = "external-update-summary-state is-" + (unknown ? "review" : "current");
        subtitle.textContent = detected + " version(s) detected locally · " +
            (rows.length - detected - unknown) + " optional component(s) not installed" +
            (unknown ? " · " + unknown + " version(s) unknown" : "");
        result.textContent = "Read-only inventory. External software is installed during SDRCC " +
            "setup and updated only through tested SDRCC releases when needed.";
        result.className = "control-result";
    }
    async function load() {
        if (pending) return;
        pending = true;
        refresh.disabled = true;
        try {
            const response = await fetch("/api/external-updates", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok || !data.ok) throw Error("Local software inventory unavailable");
            render(data);
        } catch (error) {
            badge.textContent = "CHECK FAILED";
            badge.className = "external-update-summary-state is-error";
            subtitle.textContent = "Local version check failed";
            result.textContent = "Unable to read installed versions: " + error.message;
            result.className = "control-result bad";
        } finally {
            pending = false;
            refresh.disabled = false;
        }
    }
    refresh.addEventListener("click", load);
    load();
})();
