export function updateStatusbar(data) {
    const left = document.getElementById("statusbar-left");
    const right = document.getElementById("statusbar-right");

    const serviceLabel = (label, service) => {
        const state = String(
            service?.lifecycle_state || (service?.active ? "RUNNING" : "STOPPED")
        ).toUpperCase();
        return `${label} ${state}`;
    };
    const ais = serviceLabel("AIS", data.ais);
    const adsb = serviceLabel("ADS-B", data.adsb);
    const tle = data.tle_present ? "TLE OK" : "TLE MISSING";
    const cpu = data.system ? `CPU ${data.system.cpu_percent}%` : "CPU -";
    const phase = data.mission ? data.mission.phase : "MISSION -";

    if (left) {
        left.textContent = `READY | ${phase} | ${ais} | ${adsb} | ${tle} | ${cpu}`;
    }

    if (right) {
        right.textContent = new Date().toLocaleTimeString("nl-NL");
    }
}
