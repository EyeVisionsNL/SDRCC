export function updateLatestCapture(capture) {
    updateCaptureBlock(capture, "");

    // Initialiseer het Images-tabblad één keer. Daarna bepaalt een handmatige
    // thumbnailselectie welk beeld zichtbaar blijft tijdens dashboard-refreshes.
    const imagesViewer = document.getElementById("capture-image-images");
    if (!imagesViewer?.getAttribute("src")) {
        updateCaptureBlock(capture, "-images");
    }

    updateImagePipeline(capture);
}

export function updateRecentCaptures(captures) {
    const box = document.getElementById("recent-captures");
    if (!box) return;

    if (!captures || captures.length === 0) {
        box.textContent = "No recordings found yet.";
        return;
    }

    box.innerHTML = "";

    captures.forEach(capture => {
        const item = document.createElement("div");
        item.className = "recent-capture-item";

        item.innerHTML = `
            <strong>${capture.filename}</strong><br>
            <span>${capture.satellite} · ${capture.product}</span><br>
            <small>${capture.modified} · ${capture.resolution}</small>
        `;

        item.addEventListener("click", () => {
            updateCaptureBlock(capture, "-images");
        });

        box.appendChild(item);
    });
}

function updateCaptureBlock(capture, suffix = "") {
    const empty = document.getElementById(`capture-empty${suffix}`);
    const content = document.getElementById(`capture-content${suffix}`);
    const image = document.getElementById(`capture-image${suffix}`);
    const name = document.getElementById(`capture-name${suffix}`);
    const satellite = document.getElementById(`capture-satellite${suffix}`);
    const pipeline = document.getElementById(`capture-pipeline${suffix}`);
    const product = document.getElementById(`capture-product${suffix}`);
    const resolution = document.getElementById(`capture-resolution${suffix}`);
    const modified = document.getElementById(`capture-modified${suffix}`);
    const size = document.getElementById(`capture-size${suffix}`);

    if (!empty || !content || !image || !name || !modified || !size) return;

    if (!capture) {
        empty.style.display = "block";
        empty.textContent = "No image found yet.";
        content.classList.add("hidden");
        image.removeAttribute("src");
        return;
    }

    empty.style.display = "none";
    content.classList.remove("hidden");

    image.src = capture.url + "?t=" + Date.now();

    name.textContent = capture.live
        ? "🔴 LIVE PREVIEW · " + capture.filename
        : capture.filename;

    if (satellite) satellite.textContent = capture.satellite || "-";
    if (pipeline) pipeline.textContent = capture.pipeline || "-";
    if (product) product.textContent = capture.product || "-";
    if (resolution) resolution.textContent = capture.resolution || "-";

    modified.textContent = capture.modified;
    size.textContent = capture.size_kb;
}

function updateImagePipeline(capture) {
    const satellite = document.getElementById("image-pipeline-satellite");
    const pipeline = document.getElementById("image-pipeline-type");
    const product = document.getElementById("image-pipeline-product");
    const status = document.getElementById("image-pipeline-status");

    if (!capture) {
        if (satellite) satellite.textContent = "-";
        if (pipeline) pipeline.textContent = "-";
        if (product) product.textContent = "-";
        if (status) {
            status.textContent = "standby";
            status.className = "warn";
        }
        return;
    }

    if (satellite) satellite.textContent = capture.satellite || "-";
    if (pipeline) pipeline.textContent = capture.pipeline || "-";
    if (product) product.textContent = capture.product || "-";

    if (status) {
        status.textContent = capture.live ? "LIVE" : "READY";
        status.className = capture.live ? "bad" : "ok";
    }
}
