(() => {
    "use strict";

    const POLL_MS = 1000;
    const subscribers = new Set();

    let timerId = null;
    let requestInProgress = false;
    let generation = 0;
    let snapshot = Object.freeze({
        ok: false,
        loading: true,
        error: null,
        active: false,
        state: "UNKNOWN",
        mission: {},
        live_rf: {},
        receiver_manager: {},
        automation_controller: {},
        scheduler: {},
        summary: {},
        generated_at: null,
        received_at: null,
    });

    function deriveActive(data) {
        const mission = data.mission || {};
        const liveRf = data.live_rf || {};
        const missionState = String(
            mission.state || mission.phase || "UNKNOWN"
        ).toUpperCase();

        // READY/STANDBY is leidend zodra Live RF niet werkelijk actief is.
        // Daarmee kan een kort achtergebleven active_job de UI niet heractiveren.
        if (
            ["READY", "STANDBY"].includes(missionState)
            && liveRf.active !== true
        ) {
            return false;
        }

        return Boolean(
            mission.active_job
            || liveRf.active === true
        );
    }

    function deriveState(data) {
        const mission = data.mission || {};
        const liveRf = data.live_rf || {};

        if (mission.active_job && mission.active_job.state) {
            return String(mission.active_job.state).toUpperCase();
        }
        if (mission.state) return String(mission.state).toUpperCase();
        if (liveRf.state) return String(liveRf.state).toUpperCase();
        return "UNKNOWN";
    }

    function buildSnapshot(data, error = null) {
        const receivedAt = new Date().toISOString();
        const source = data && typeof data === "object" ? data : {};

        return Object.freeze({
            ok: error === null && source.ok !== false,
            loading: false,
            error: error ? String(error.message || error) : null,
            active: deriveActive(source),
            state: deriveState(source),
            mission: source.mission || {},
            live_rf: source.live_rf || {},
            receiver_manager: source.receiver_manager || {},
            automation_controller: source.automation_controller || {},
            scheduler: source.scheduler || {},
            summary: source.summary || {},
            generated_at: source.generated_at || null,
            received_at: receivedAt,
        });
    }

    function notify() {
        for (const subscriber of subscribers) {
            try {
                subscriber(snapshot);
            } catch (error) {
                console.error("MissionState subscriber failed:", error);
            }
        }
        window.dispatchEvent(new CustomEvent("sdrcc:mission-state", {
            detail: snapshot,
        }));
    }

    async function requestSnapshot() {
        const response = await fetch("/api/mission-operations", {
            cache: "no-store",
            headers: { "Accept": "application/json" },
        });
        if (!response.ok) {
            throw new Error(`/api/mission-operations: HTTP ${response.status}`);
        }
        return await response.json();
    }

    async function refresh({ force = false } = {}) {
        if (requestInProgress && !force) return snapshot;

        const requestGeneration = ++generation;
        requestInProgress = true;

        try {
            const data = await requestSnapshot();
            if (requestGeneration !== generation) return snapshot;
            snapshot = buildSnapshot(data);
            notify();
            return snapshot;
        } catch (error) {
            if (requestGeneration !== generation) return snapshot;
            snapshot = buildSnapshot({}, error);
            notify();
            return snapshot;
        } finally {
            if (requestGeneration === generation) {
                requestInProgress = false;
            }
        }
    }

    function subscribe(callback, { immediate = true } = {}) {
        if (typeof callback !== "function") {
            throw new TypeError("MissionState.subscribe verwacht een functie");
        }
        subscribers.add(callback);
        if (immediate) callback(snapshot);
        return () => subscribers.delete(callback);
    }

    function getSnapshot() {
        return snapshot;
    }

    function start() {
        if (timerId !== null) return;
        refresh({ force: true });
        timerId = window.setInterval(() => refresh(), POLL_MS);
    }

    function stop() {
        if (timerId !== null) {
            window.clearInterval(timerId);
            timerId = null;
        }
        generation += 1;
        requestInProgress = false;
    }

    window.MissionState = Object.freeze({
        refresh,
        subscribe,
        getSnapshot,
        start,
        stop,
        pollIntervalMs: POLL_MS,
    });

    start();
})();
