(() => {
  "use strict";
  const by = id => document.getElementById(id);
  const panel = by("local-ai-panel");
  if (!panel) return;
  const status = by("local-ai-status"), badge = by("local-ai-badge");
  const install = by("local-ai-install"), toggle = by("local-ai-toggle");
  const remove = by("local-ai-remove"), send = by("local-ai-send");
  const question = by("local-ai-question"), answer = by("local-ai-answer");
  let snapshot = null, pending = false, timer = null;
  async function api(path, body) {
    const res = await fetch("/api/local-ai/" + path, body === undefined
      ? {cache: "no-store"} : {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Local AI request failed.");
    return data;
  }
  function render() {
    const s = snapshot;
    const busy = pending || !s || s.busy;
    install.disabled = busy || !!s?.installed;
    toggle.disabled = busy || !s?.installed;
    remove.disabled = busy || !s || (!s.installed && !s.has_assets);
    question.disabled = send.disabled = busy || !s?.enabled || !s?.installed;
    toggle.textContent = s?.enabled ? "Disable Local AI" : "Enable Local AI";
    if (!s) return;
    badge.textContent = s.busy ? "BUSY" : s.installed ? (s.enabled ? "ENABLED" : "DISABLED") : "NOT INSTALLED";
    status.textContent = [s.progress || (s.installed ? "Model and engine installed." : "AI is not installed."),
      s.ram_gib + " GiB RAM · " + s.available_gib + " GiB available · " + s.architecture,
      s.error || ""].filter(Boolean).join(" · ");
  }
  function schedule() {
    clearTimeout(timer);
    if (panel.open && snapshot?.busy && !pending) timer = setTimeout(refresh, 2000);
  }
  async function refresh() {
    if (!panel.open || pending) return;
    try { snapshot = await api("status"); render(); }
    catch (err) { status.textContent = err.message; snapshot = null; render(); }
    schedule();
  }
  async function act(action) {
    if (pending) return;
    pending = true; render();
    try { snapshot = await api("action", {action}); }
    catch (err) { answer.textContent = err.message; }
    finally { pending = false; render(); schedule(); }
  }
  install.addEventListener("click", () => {
    if (confirm("Download and verify Local AI and Qwen3-4B? Approximately 2.5 GB of model data.")) act("install");
  });
  toggle.addEventListener("click", () => act(snapshot?.enabled ? "disable" : "enable"));
  remove.addEventListener("click", () => {
    if (confirm("Remove the local AI model and engine? Receiver configuration is not affected.")) act("remove");
  });
  send.addEventListener("click", async () => {
    const q = question.value.trim();
    if (!q || pending) return;
    pending = true; render(); answer.textContent = "Local AI is processing...";
    try { answer.textContent = (await api("chat", {question: q})).answer; }
    catch (err) { answer.textContent = err.message; }
    finally { pending = false; await refresh(); render(); }
  });
  panel.addEventListener("toggle", () => {
    if (panel.open) refresh(); else clearTimeout(timer);
  });
  render();
})();
