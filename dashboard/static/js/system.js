import {setText, setBar, formatUptime} from "./utils.js";

export function updateSystem(data) {
    setText("system-cpu", data.system.cpu_percent + " %");
    setText("system-ram", data.system.ram_percent + " %");
    setText("system-disk", data.system.disk_percent + " %");
    setText("system-uptime", formatUptime(data.system.uptime_seconds));

    setBar("system-cpu-bar", data.system.cpu_percent);
    setBar("system-ram-bar", data.system.ram_percent);
    setBar("system-disk-bar", data.system.disk_percent);
}
