export function updateStatusbar(data) {
    const left = document.getElementById("statusbar-left");
    const right = document.getElementById("statusbar-right");

    const ais = data.ais && data.ais.active ? "AIS OK" : "AIS OFF";
    const adsb = data.adsb && data.adsb.active ? "ADS-B OK" : "ADS-B OFF";
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
