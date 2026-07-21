export function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value ?? "-";
}

export function setStatus(id, active) {
    const element = document.getElementById(id);
    if (!element) return;

    element.textContent = active ? "RUNNING" : "STOPPED";
    element.className = active ? "ok" : "bad";
}

export function setBar(id, value) {
    const bar = document.getElementById(id);
    if (!bar) return;

    const number = Number(value) || 0;
    bar.style.width = `${number}%`;
    bar.classList.remove("bar-ok", "bar-warn", "bar-bad");

    if (number >= 85) bar.classList.add("bar-bad");
    else if (number >= 65) bar.classList.add("bar-warn");
    else bar.classList.add("bar-ok");
}

export function formatUptime(seconds) {
    if (seconds == null) return "-";

    const days = Math.floor(seconds / 86400);
    seconds %= 86400;

    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;

    const minutes = Math.floor(seconds / 60);

    let text = "";
    if (days > 0) text += days + "d ";
    if (hours > 0 || days > 0) text += hours + "h ";
    text += minutes + "m";

    return text;
}

export function formatCountdown(seconds) {
    if (seconds == null) return "-";
    if (seconds <= 0) return window.SDRCC_UI_TEXT.t("active_now");

    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;

    const minutes = Math.floor(seconds / 60);
    const sec = seconds % 60;

    return (
        String(hours).padStart(2, "0") + ":" +
        String(minutes).padStart(2, "0") + ":" +
        String(sec).padStart(2, "0")
    );
}
