(() => {
    let saving = false;

    function setResult(message, isError = false) {
        const result = document.getElementById("weather-planning-result");
        if (!result) return;
        result.textContent = message;
        result.classList.toggle("error-text", isError);
    }

    function populate(settings) {
        const input = document.getElementById("weather-minimum-elevation");
        if (!input || !settings) return;
        input.min = String(settings.minimum_allowed ?? 5);
        input.max = String(settings.maximum_allowed ?? 90);
        input.value = String(settings.minimum_elevation ?? 40);
    }

    async function load() {
        try {
            const response = await fetch("/api/weather-planning", {cache: "no-store"});
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || "Setting could not be loaded.");
            populate(data.settings);
        } catch (error) {
            setResult(`Laden mislukt: ${error.message}`, true);
        }
    }

    const form = document.getElementById("weather-planning-form");
    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (saving) return;
            const input = document.getElementById("weather-minimum-elevation");
            const button = form.querySelector('button[type="submit"]');
            saving = true;
            if (button) button.disabled = true;
            setResult("Saving minimum elevation...");
            try {
                const response = await fetch("/api/weather-planning", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({minimum_elevation: Number(input.value)}),
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || "Save failed.");
                populate(data.settings);
                setResult(data.message || "Minimale elevatie opgeslagen.");
                window.dispatchEvent(new CustomEvent("sdrcc:weather-planning-changed", {detail: data.settings}));
            } catch (error) {
                setResult(`Save failed: ${error.message}`, true);
            } finally {
                saving = false;
                if (button) button.disabled = false;
            }
        });
    }

    load();
})();
