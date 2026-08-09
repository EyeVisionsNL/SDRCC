export async function getStatus() {
    const response = await fetch("/api/status?include_logs=0", {cache: "no-store"});
    if (!response.ok) {
        throw new Error("Status API fout");
    }
    return await response.json();
}

export async function runActionApi(actionId) {
    const response = await fetch("/api/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: actionId})
    });

    return await response.json();
}
