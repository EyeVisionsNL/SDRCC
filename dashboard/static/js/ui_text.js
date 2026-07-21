(function (global) {
    "use strict";

    const TEXT = Object.freeze({
        active_now: "NOW / ACTIVE",
        all_events: "No operator events yet.",
        filtered_events: "No events match this filter.",
        images: "Images",
        progress: "Progress",
        result: "Result",
        no_mission_result: "No mission result available yet.",
        no_captures: "No captures found yet.",
        no_image: "No image found yet.",
        not_available: "Not Available",
        delete: "🗑 Delete",
        deleting: "Deleting…",
        delete_mission_aria: "Delete mission {mission}",
        delete_failed: "Mission deletion failed",
        deleted_refreshing: "Mission deleted. Refreshing history…",
        delete_error: "Mission could not be deleted: {error}",
        no_mission_image: "No image available for this mission.",
        diagnostics: "Diagnostics",
        mission_detail_unavailable: "Mission Detail is unavailable.",
        save_failed: "Save failed.",
        save_failed_error: "Save failed: {error}",
        saved: "Saved.",
        failed: "Failed.",
        apply_failed_error: "Apply failed: {error}",
        applied: "Applied.",
        save_roles_first: "Save the changed roles first.",
        no_receiver_status: "No receiver status available.",
        updated_at: "Updated {time}",
        receiver_monitor_unavailable: "Receiver Monitor unavailable: {error}",
        controller_unavailable: "Controller status unavailable",
        mission_queue_unavailable: "Mission Queue unavailable",
        no_next_pass: "No next pass available",
        ground_track_ready: "Ground Track integration is prepared.",
        next_satellite: "Next satellite",
        next_pass_ground_track: "Next pass and future ground track",
        no_sync: "No Sync",
        waiting_aos: "Waiting for AOS",
        archiving_output: "Archiving mission output",
        mission_stopped: "Mission stopped: {result}",
        pipeline_error: "Pipeline error",
        no_live_product: "No live product yet",
        mission_active: "Mission is active.",
        no_completed_mission: "No completed mission yet.",
        mission_stopped_plain: "Mission stopped.",
        telemetry_unavailable: "Telemetry unavailable",
        mission_state_unavailable: "MissionState unavailable",
        next_task: "Next Task",
        present: "present",
        missing: "missing",
        dashboard_update_failed: "Dashboard update failed:",
        loading_noaa_meteor: "Waiting for NOAA / METEOR output..."
    });


    const RUNTIME_EXACT = Object.freeze({
        "Wachten op volgende METEOR-passage": "Waiting for the next METEOR pass",
        "Signaal gezien, maar geen decoder-lock": "Signal detected, but no decoder lock",
        "Passage geselecteerd": "Pass selected",
        "Weather-ontvanger gewijzigd": "Weather receiver changed",
        "Event Bus gestart": "Event Bus started",
        "RF-instellingen opgeslagen": "RF settings saved",
        "Rollen opgeslagen": "Roles saved",
        "Receiver-services gebruiken deze rollen al": "Receiver services already use these roles",
        "Niet bevestigd": "Not confirmed",
        "Vrij": "Free",
        "Wachten": "Waiting",
        "Schepen": "Ships",
        "Berichten/s": "Messages/s",
        "Vliegtuigen": "Aircraft",
        "Met positie": "With position"
    });

    function runtime(value) {
        if (value === null || value === undefined) return value;
        let text = String(value);
        if (Object.prototype.hasOwnProperty.call(RUNTIME_EXACT, text)) return RUNTIME_EXACT[text];
        const replacements = [
            [/\bWachten op volgende METEOR-passage\b/gi, "Waiting for the next METEOR pass"],
            [/\bSignaal gezien, maar geen decoder-lock\b/gi, "Signal detected, but no decoder lock"],
            [/\bPassage geselecteerd\b/gi, "Pass selected"],
            [/\bWeather-ontvanger gewijzigd\b/gi, "Weather receiver changed"],
            [/\bEvent Bus gestart\b/gi, "Event Bus started"],
            [/\bopgeslagen\b/gi, "saved"],
            [/\bgewijzigd\b/gi, "changed"],
            [/\bgestart\b/gi, "started"],
            [/\bgestopt\b/gi, "stopped"],
            [/\bwachten\b/gi, "waiting"],
            [/\bvrij\b/gi, "free"],
            [/\bgeen\b/gi, "no"],
            [/\bsignaal\b/gi, "signal"],
            [/\bmissie\b/gi, "mission"],
            [/\bpassage\b/gi, "pass"],
            [/\bontvanger\b/gi, "receiver"]
        ];
        for (const [pattern, replacement] of replacements) text = text.replace(pattern, replacement);
        return text;
    }

    function t(key) {
        return Object.prototype.hasOwnProperty.call(TEXT, key) ? TEXT[key] : key;
    }

    function tf(key, values = {}) {
        return t(key).replace(/\{([A-Za-z0-9_]+)\}/g, (match, name) => (
            Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        ));
    }

    global.SDRCC_UI_TEXT = Object.freeze({TEXT, t, tf, runtime});
})(window);
