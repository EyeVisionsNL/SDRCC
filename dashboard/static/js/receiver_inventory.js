(() => {
  "use strict";
  const esc = (v) => String(v ?? "-").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const list = (v) => Array.isArray(v) && v.length ? v.join(", ") : "-";
  function render(data) {
    const root=document.getElementById("receiver-inventory"); const status=document.getElementById("receiver-inventory-status");
    if(!root) return;
    const items=Array.isArray(data.receivers)?data.receivers:[];
    if(!data.ok || !items.length){ root.innerHTML='<div class="receiver-inventory-empty">Geen receivergegevens beschikbaar.</div>'; if(status) status.textContent=data.error||"Receiver Inventory niet beschikbaar."; return; }
    root.innerHTML=items.map(r=>`<article class="receiver-inventory-item">
      <div class="receiver-inventory-head"><div><h3>${esc(r.number)} · ${esc(r.name)}</h3><div class="receiver-inventory-serial">RTL-SDR #${esc(r.serial)}</div></div><span class="receiver-inventory-state" data-state="${esc(r.runtime_state)}">${esc(r.runtime_state)}</span></div>
      <dl class="receiver-inventory-details"><dt>Canonical ID</dt><dd>${esc(r.canonical_id)}</dd><dt>Runtime alias</dt><dd>${esc(r.runtime_id)}</dd><dt>Driver</dt><dd>${esc(r.driver)}</dd><dt>Pluginrollen</dt><dd>${esc(list(r.assigned_roles))}</dd><dt>Actieve services</dt><dd>${esc(list(r.active_services))}</dd><dt>Beschikbaar</dt><dd>${r.available?"JA":"NEE"}</dd></dl>
      <div class="receiver-inventory-tags">${(r.capabilities||[]).map(x=>`<span class="receiver-inventory-tag">${esc(x)}</span>`).join("")}</div></article>`).join("");
    if(status) status.textContent=`${items.length} receivers · identity authority: ${data.identity_authority} · read-only`;
  }
  async function load(){ try { const r=await fetch("/api/receiver-inventory",{cache:"no-store"}); render(await r.json()); } catch(e){ render({ok:false,error:e.message,receivers:[]}); } }
  document.addEventListener("DOMContentLoaded",()=>{ load(); window.setInterval(load,10000); });
})();
