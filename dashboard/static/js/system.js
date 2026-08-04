import {setText, setBar, formatUptime} from "./utils.js";

function percentage(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
}

function formatPercentage(value) {
    const number = percentage(value);
    return `${Number.isInteger(number) ? number : number.toFixed(1)} %`;
}

function updateHealthCard(cardId, stateId, value) {
    const card = document.getElementById(cardId);
    const state = document.getElementById(stateId);
    if (!card || !state) return;

    const number = percentage(value);
    let tone = "is-ok";
    let label = "NOMINAL";
    if (number >= 85) {
        tone = "is-bad";
        label = "HIGH";
    } else if (number >= 65) {
        tone = "is-warn";
        label = "ELEVATED";
    }

    card.classList.remove("is-loading", "is-ok", "is-warn", "is-bad");
    card.classList.add(tone);
    state.textContent = label;
}

export function updateSystem(data) {
    const system = data && data.system ? data.system : {};
    const cpu = percentage(system.cpu_percent);
    const ram = percentage(system.ram_percent);
    const disk = percentage(system.disk_percent);

    setText("system-cpu", formatPercentage(cpu));
    setText("system-ram", formatPercentage(ram));
    setText("system-disk", formatPercentage(disk));
    setText("system-uptime", formatUptime(system.uptime_seconds));

    setBar("system-cpu-bar", cpu);
    setBar("system-ram-bar", ram);
    setBar("system-disk-bar", disk);

    updateHealthCard("system-cpu-card", "system-cpu-state", cpu);
    updateHealthCard("system-ram-card", "system-ram-state", ram);
    updateHealthCard("system-disk-card", "system-disk-state", disk);
}
