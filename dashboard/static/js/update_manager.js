(() => {
    const installed = document.getElementById("sdrcc-update-installed");
    const latest = document.getElementById("sdrcc-update-latest");
    const badge = document.getElementById("sdrcc-update-badge");
    const result = document.getElementById("sdrcc-update-result");
    const checkButton = document.getElementById("sdrcc-update-check");
    const installButton = document.getElementById("sdrcc-update-install");
    if (!installed || !latest || !badge || !result || !checkButton || !installButton) return;

    const ACTIVE = new Set([
        "queued", "starting", "downloading", "validating",
        "backing_up", "installing", "restarting",
    ]);
    let polling = null;
    let completingAudio = false;
    let completionAttempted = false;
    let lastWorker = {};

    function setResult(message, kind = "") {
        result.textContent = message;
        result.className = "control-result" + (kind ? ` ${kind}` : "");
    }

    function render(data) {
        installed.textContent = data.installed_version || "-";
        latest.textContent = data.latest_version || "Unavailable";

        const worker = data.worker || {};
        lastWorker = worker;
        if (ACTIVE.has(worker.state)) {
            badge.textContent = "UPDATING";
            installButton.disabled = true;
            checkButton.disabled = true;
            setResult(worker.message || "Update in progress...", "warn");
            return;
        }

        checkButton.disabled = false;

        installButton.textContent = data.can_complete_audio_setup ? "Complete audio setup" : "Install update";
        if (data.can_complete_audio_setup) {
            badge.textContent = "AUDIO SETUP NEEDED";
            installButton.disabled = false;
            setResult("SDRCC is current; complete installation of the audio libraries.", "warn");
        } else if (data.update_available) {
            badge.textContent = "UPDATE AVAILABLE";
            installButton.disabled = false;
            setResult(
                `Update available: ${data.installed_version} → ${data.latest_version}`,
                "warn",
            );
        } else if (data.local_ahead) {
            badge.textContent = "LOCAL AHEAD";
            installButton.disabled = true;
            setResult(
                `Installed ${data.installed_version} is ahead of GitHub main (${data.latest_version}).`,
                "ok",
            );
        } else if (data.same_version) {
            badge.textContent = "UP TO DATE";
            installButton.disabled = true;
            setResult(`SDRCC ${data.installed_version} is up to date.`, "ok");
        } else if (data.check_error) {
            badge.textContent = "CHECK UNAVAILABLE";
            installButton.disabled = true;
            setResult(`Update check unavailable: ${data.check_error}`, "bad");
        } else {
            badge.textContent = "CHECKING";
            installButton.disabled = true;
            setResult("Checking GitHub main for a newer SDRCC version...", "warn");
        }

        if (worker.state === "failed") {
            setResult(`Last update failed: ${worker.message || "unknown error"}`, "bad");
        } else if (worker.state === "success" && data.same_version && !data.can_complete_audio_setup) {
            setResult(worker.message || `SDRCC ${data.installed_version} installed successfully.`, "ok");
        }
    }

    async function loadStatus(refresh = false) {
        const suffix = refresh ? "?refresh=1" : "";
        const response = await fetch(`/api/update-status${suffix}`, {cache: "no-store"});
        const data = await response.json();
        render(data);
        const worker = data.worker || {};
        const age = Date.now() - Date.parse(worker.updated_at || "");
        // Continue a recent explicitly requested update made by an older worker.
        // A repair pass records current==target, preventing automatic retry loops.
        if (data.can_complete_audio_setup && worker.state === "success"
                && worker.target_version === data.installed_version
                && worker.current_version && worker.current_version !== worker.target_version
                && !worker.audio_setup_attempted && age >= 0 && age < 15 * 60 * 1000
                && !completingAudio && !completionAttempted) {
            completionAttempted = true;
            completingAudio = true;
            try {
                const response = await fetch("/api/update/install", {method: "POST",
                    headers: {"Content-Type": "application/json"}, body: "{}"});
                const started = await response.json();
                if (!response.ok || !started.ok) throw new Error(started.message || "Audio setup could not start");
                pollAfterStart();
            } catch (error) {
                setResult("Use Complete audio setup to retry: " + error.message, "warn");
            } finally { completingAudio = false; }
        }
        return data;
    }

    async function pollAfterStart() {
        const previousWorker = JSON.stringify(lastWorker);
        if (polling) clearInterval(polling);
        polling = setInterval(async () => {
            try {
                const data = await loadStatus(false);
                if (JSON.stringify(data.worker || {}) === previousWorker) return;
                const state = (data.worker || {}).state;
                if (state === "success") {
                    clearInterval(polling);
                    polling = null;
                    window.location.reload();
                } else if (state === "failed") {
                    clearInterval(polling);
                    polling = null;
                }
            } catch (error) {
                badge.textContent = "RESTARTING";
                setResult("SDRCC is restarting after the update...", "warn");
            }
        }, 2000);
    }

    checkButton.addEventListener("click", async () => {
        checkButton.disabled = true;
        installButton.disabled = true;
        badge.textContent = "CHECKING";
        setResult("Checking GitHub main...", "warn");
        try {
            await loadStatus(true);
        } catch (error) {
            badge.textContent = "CHECK FAILED";
            setResult(`Update check failed: ${String(error)}`, "bad");
            checkButton.disabled = false;
        }
    });

    installButton.addEventListener("click", async () => {
        const target = latest.textContent;
        const source = installed.textContent;
        if (!confirm(
            (installButton.textContent === "Complete audio setup" ? "Complete audio library installation?\n\n" : `Install SDRCC update ${source} → ${target}?\n\n`)
            + "Active receiver work must be stopped."
            + (installButton.textContent === "Complete audio setup" ? "" : " SDRCC will restart automatically.")
        )) return;

        installButton.disabled = true;
        checkButton.disabled = true;
        badge.textContent = "STARTING";
        setResult("Starting managed SDRCC update...", "warn");

        try {
            const response = await fetch("/api/update/install", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: "{}",
            });
            const data = await response.json();
            if (!response.ok || !data.ok) {
                throw new Error(data.message || "Update could not be started.");
            }
            setResult(data.message || "Update started.", "warn");
            pollAfterStart();
        } catch (error) {
            badge.textContent = "UPDATE FAILED";
            setResult(`Update start failed: ${String(error)}`, "bad");
            checkButton.disabled = false;
            await loadStatus(false).catch(() => {});
        }
    });

    loadStatus(false).catch(() => {
        badge.textContent = "CHECKING";
        setResult("Waiting for the startup update check...", "warn");
    });
    setTimeout(() => loadStatus(false).catch(() => {}), 1500);
    setInterval(() => { if (!polling && !completingAudio) loadStatus(false).catch(() => {}); }, 10000);
})();
