(() => {
    async function getStatus() {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) throw new Error("status api fout");
        return await response.json();
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function setPill(id, service) {
        const element = document.getElementById(id);
        if (!element) return;

        const running = service && service.active;
        element.textContent = running ? "RUNNING" : (service ? service.state.toUpperCase() : "-");
        element.classList.toggle("running", running);
    }

    function renderDevices(devices) {
        const container = document.getElementById("radio-devices");
        if (!container) return;

        container.innerHTML = "";

        for (const dev of devices || []) {
            const item = document.createElement("div");
            item.className = "radio-device";
            item.innerHTML = `
                <strong>${dev.name || dev.id}</strong><br>
                Serial: ${dev.serial || "-"}<br>
                Role: ${dev.role || "-"}<br>
                Locked: ${dev.locked ? "YES" : "NO"}
            `;
            container.appendChild(item);
        }
    }

    async function updateRadioPage() {
        try {
            const data = await getStatus();
            const sdr2 = data.sdr2 || {};

            setText("radio-sdr2-status", sdr2.status || "-");
            setText("radio-sdr2-profile", sdr2.profile || "-");
            setText("radio-sdr2-locked", sdr2.locked ? "YES" : "NO");
            setText("radio-sdr2-process", sdr2.process || "-");
            setText("radio-sdr2-updated", sdr2.updated || "-");

            setPill("radio-ais-pill", data.ais);
            setPill("radio-adsb-pill", data.adsb);

            renderDevices(data.devices || []);
        } catch (error) {
            console.log("Radio update mislukt:", error.message);
        }
    }

    updateRadioPage();
    setInterval(updateRadioPage, 3000);
})();
