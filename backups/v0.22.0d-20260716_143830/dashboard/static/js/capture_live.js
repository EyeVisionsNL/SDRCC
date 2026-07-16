let lastCaptureKey = "";

async function fetchCaptureStatus() {
    const response = await fetch("/api/capture-status", {
        cache: "no-store",
    });

    if (!response.ok) {
        throw new Error("Capture status API fout");
    }

    return await response.json();
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = value;
    }
}

function showElement(id, visible) {
    const element = document.getElementById(id);
    if (!element) {
        return;
    }

    if (visible) {
        element.classList.remove("hidden");
    } else {
        element.classList.add("hidden");
    }
}

function updateImageBlock(prefix, capture) {
    const suffix = prefix ? `-${prefix}` : "";

    const image = document.getElementById(`capture-image${suffix}`);
    if (!image) {
        return;
    }

    const cacheBust = `${capture.url}?t=${capture.age_seconds}-${Date.now()}`;

    image.src = cacheBust;

    setText(`capture-name${suffix}`, capture.filename || "-");
    setText(`capture-satellite${suffix}`, capture.satellite || "-");
    setText(`capture-pipeline${suffix}`, capture.pipeline || "-");
    setText(`capture-product${suffix}`, capture.product || "-");
    setText(`capture-resolution${suffix}`, capture.resolution || "-");
    setText(`capture-modified${suffix}`, capture.modified || "-");
    setText(`capture-size${suffix}`, capture.size_kb || "-");
}

async function updateLiveCapture() {
    try {
        const data = await fetchCaptureStatus();

        if (!data.available || !data.latest_capture) {
            showElement("capture-empty", true);
            showElement("capture-content", false);
            showElement("capture-empty-images", true);
            showElement("capture-content-images", false);
            return;
        }

        const capture = data.latest_capture;
        const captureKey = `${capture.relative_path}-${capture.modified}-${capture.size_kb}`;

        if (captureKey === lastCaptureKey) {
            return;
        }

        lastCaptureKey = captureKey;

        showElement("capture-empty", false);
        showElement("capture-content", true);
        showElement("capture-empty-images", false);
        showElement("capture-content-images", true);

        updateImageBlock("", capture);
        updateImageBlock("images", capture);
    } catch (error) {
        console.log("Live capture update mislukt:", error.message);
    }
}

updateLiveCapture();
setInterval(updateLiveCapture, 1000);
