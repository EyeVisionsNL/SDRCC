(() => {
  const state = { recordings: [], history: [], selected: null };
  const byId = (id) => document.getElementById(id);
  const text = (id, value, fallback = '-') => { const el = byId(id); if (el) el.textContent = value ?? fallback; };
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const formatBytes = (bytes) => {
    const n = Number(bytes || 0);
    if (n >= 1073741824) return `${(n / 1073741824).toFixed(1)} GB`;
    if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`;
    if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${n} B`;
  };
  const formatClock = (seconds) => {
    const n = Math.max(0, Number(seconds || 0));
    const h = Math.floor(n / 3600); const m = Math.floor((n % 3600) / 60); const s = Math.floor(n % 60);
    return h ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  };
  const fetchJson = async (url) => {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  };
  const setMode = (active) => {
    const badge = byId('mission-operations-mode-badge');
    if (!badge) return;
    badge.textContent = active ? 'LIVE' : 'RESULT';
    badge.classList.toggle('live', active); badge.classList.toggle('result', !active);
  };
  const setPreview = (monitor) => {
    const image = monitor && monitor.image;
    const img = byId('mission-operations-preview');
    const empty = byId('mission-operations-preview-empty');
    if (!img || !empty) return;
    if (image && image.url) {
      const separator = image.url.includes('?') ? '&' : '?';
      img.src = `${image.url}${separator}t=${Date.now()}`;
      img.classList.remove('hidden'); empty.classList.add('hidden');
      text('mission-operations-preview-state', image.live ? 'LIVE' : 'LATEST');
      text('mission-operations-preview-meta', `${image.satellite || '-'} · ${image.product || image.filename || '-'} · ${image.resolution || '-'}`);
    } else {
      img.removeAttribute('src'); img.classList.add('hidden'); empty.classList.remove('hidden');
      text('mission-operations-preview-state', 'STANDBY'); text('mission-operations-preview-meta', '-');
    }
  };
  const updateLive = (engine, rf, monitor) => {
    const activeJob = engine && engine.active_job;
    const active = Boolean((rf && rf.active) || (monitor && monitor.active) || activeJob);
    setMode(active);
    const stateValue = (rf && rf.state) || (monitor && monitor.state) || (activeJob && activeJob.state) || 'IDLE';
    const satellite = (rf && rf.satellite) || (monitor && monitor.satellite) || (activeJob && (activeJob.satellite || activeJob.target)) || 'No active mission';
    text('mission-operations-state', stateValue);
    text('mission-operations-satellite', satellite);
    text('mission-operations-detail', active ? ((rf && rf.detail) || (engine && engine.detail) || 'Mission is active.') : 'Waiting for the next mission.');
    text('mission-operations-receiver', (rf && (rf.receiver || rf.serial)) || (activeJob && (activeJob.receiver || activeJob.receiver_id)) || '-');
    const hz = Number((rf && rf.frequency_hz) || (activeJob && activeJob.frequency) || 0);
    text('mission-operations-frequency', hz ? `${(hz / 1e6).toFixed(3)} MHz` : '-');
    text('mission-operations-elapsed', formatClock(rf && rf.elapsed_seconds));
    text('mission-operations-remaining', formatClock(rf && rf.remaining_seconds));
    text('mission-operations-snr', `${Number((rf && rf.snr_db) || 0).toFixed(2)} dB`);
    text('mission-operations-peak-snr', `${Number((rf && rf.peak_snr_db) || (monitor && monitor.peak_snr_db) || 0).toFixed(2)} dB`);
    text('mission-operations-frames', (rf && rf.frames) ?? (monitor && monitor.frames) ?? 0);
    text('mission-operations-cadu', formatBytes((rf && rf.cadu_bytes) ?? (monitor && monitor.cadu_bytes) ?? 0));
    const elapsed = Number(rf && rf.elapsed_seconds || 0); const remaining = Number(rf && rf.remaining_seconds || 0);
    const progress = elapsed + remaining > 0 ? Math.min(100, (elapsed / (elapsed + remaining)) * 100) : (active ? 2 : 0);
    const bar = byId('mission-operations-progress'); if (bar) bar.style.width = `${progress}%`;
    setPreview(monitor || {});
    text('mission-operations-updated', `Updated ${new Date().toLocaleTimeString('nl-NL')}`);
  };
  const findHistory = (row) => {
    if (!row) return null;
    return state.history.find(item => item.mission_id === row.mission_id) ||
      state.history.find(item => row.relative_path && item.output_path && row.relative_path.includes(String(item.output_path).split('/').pop())) || null;
  };
  const renderSummary = (row) => {
    const mission = findHistory(row) || {};
    text('mission-operations-result-id', mission.mission_id || row.mission_id || '-');
    text('mission-operations-result-satellite', mission.satellite || (row.kind === 'audio' ? 'ISS (ZARYA)' : '-'));
    text('mission-operations-result-receiver', mission.receiver || mission.receiver_id || '-');
    text('mission-operations-result-pipeline', mission.pipeline || (row.kind === 'audio' ? 'wideband_iq_offline_fm' : '-'));
    text('mission-operations-result-status', mission.result || mission.status || (row.kind === 'audio' ? 'RECORDED' : '-'));
    text('mission-operations-result-duration', mission.duration_seconds != null ? formatClock(mission.duration_seconds) : '-');
  };
  const selectResult = (row) => {
    state.selected = row;
    const audioWrap = byId('mission-recordings-audio-wrap'); const audio = byId('mission-recordings-audio');
    const empty = byId('capture-empty-images'); const content = byId('capture-content-images');
    document.querySelectorAll('.recording-item').forEach(el => el.classList.toggle('selected', el.dataset.path === row.relative_path));
    text('mission-operations-selected-kind', row.kind === 'audio' ? 'AUDIO' : 'IMAGE');
    if (row.kind === 'audio') {
      if (audio) { audio.src = row.url; audioWrap.classList.remove('hidden'); }
      text('mission-recordings-meta', `${row.mission_id || '-'} · ${row.name} · ${formatBytes(row.size_bytes)}`);
      if (content) content.classList.add('hidden'); if (empty) empty.classList.add('hidden');
    } else {
      if (audioWrap) audioWrap.classList.add('hidden');
      if (audio) { audio.pause(); audio.removeAttribute('src'); }
      if (empty) empty.classList.add('hidden'); if (content) content.classList.remove('hidden');
      const image = byId('capture-image-images'); if (image) image.src = row.url;
      text('capture-name-images', row.name); text('capture-size-images', (Number(row.size_bytes || 0) / 1024).toFixed(1));
      text('capture-modified-images', row.modified_epoch ? new Date(row.modified_epoch * 1000).toLocaleString('nl-NL') : '-');
      const mission = findHistory(row) || {};
      text('capture-satellite-images', mission.satellite || '-'); text('capture-pipeline-images', mission.pipeline || '-');
      text('capture-product-images', row.name || '-'); text('capture-resolution-images', '-');
    }
    renderSummary(row);
  };
  const renderRecordings = () => {
    const list = byId('mission-recordings-list'); if (!list) return;
    text('mission-operations-result-count', `${state.recordings.length} FILES`);
    list.innerHTML = state.recordings.map(row => `<button class="recording-item" data-path="${escapeHtml(row.relative_path)}"><span>${row.kind === 'audio' ? '🎵' : '🖼️'}</span><span><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.mission_id || '')}</small></span><small>${formatBytes(row.size_bytes)}</small></button>`).join('') || '<p class="muted">No mission results found.</p>';
    list.querySelectorAll('.recording-item').forEach((button, index) => button.addEventListener('click', () => selectResult(state.recordings[index])));
    if (!state.selected && state.recordings.length) selectResult(state.recordings[0]);
  };
  const refreshResults = async () => {
    try {
      const [recordings, history] = await Promise.all([fetchJson('/api/mission-recordings'), fetchJson('/api/mission-history?limit=250')]);
      state.recordings = Array.isArray(recordings.recordings) ? recordings.recordings : [];
      state.history = Array.isArray(history.missions) ? history.missions : (Array.isArray(history.history) ? history.history : []);
      renderRecordings();
    } catch (error) {
      const list = byId('mission-recordings-list'); if (list) list.innerHTML = `<p class="error">Mission results could not be loaded: ${escapeHtml(error.message)}</p>`;
    }
  };
  const refreshLive = async () => {
    const values = await Promise.allSettled([fetchJson('/api/mission-engine'), fetchJson('/api/live-rf'), fetchJson('/api/mission-monitor')]);
    updateLive(values[0].status === 'fulfilled' ? values[0].value : {}, values[1].status === 'fulfilled' ? values[1].value : {}, values[2].status === 'fulfilled' ? values[2].value : {});
  };
  document.addEventListener('DOMContentLoaded', () => {
    refreshResults(); refreshLive();
    setInterval(refreshLive, 3000); setInterval(refreshResults, 15000);
  });
})();
