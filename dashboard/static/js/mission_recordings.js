(() => {
  const state = { recordings: [], history: [], selected: null, audioMonitor: null, liveAudioPlaying: false, liveAudioMissionId: null };
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

  const setAudioConnection = (label, className = '') => {
    const el = byId('mission-operations-audio-connection');
    if (!el) return;
    el.textContent = label;
    el.className = `mission-operations-audio-connection ${className}`.trim();
  };
  const stopLiveAudio = () => {
    const audio = byId('mission-operations-live-audio');
    if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
    state.liveAudioPlaying = false;
    state.liveAudioMissionId = null;
    const button = byId('mission-operations-audio-play');
    if (button) button.textContent = '▶ Live audio';
    setAudioConnection('DISCONNECTED');
  };
  const toggleLiveAudio = async () => {
    const audio = byId('mission-operations-live-audio');
    const button = byId('mission-operations-audio-play');
    const monitor = state.audioMonitor || {};
    if (!audio || !button) return;
    if (state.liveAudioPlaying) { stopLiveAudio(); return; }
    if (!monitor.available || !monitor.stream_url) return;
    try {
      setAudioConnection('CONNECTING', 'connecting');
      audio.src = `${monitor.stream_url}&t=${Date.now()}`;
      audio.volume = Number(byId('mission-operations-audio-volume')?.value || 0.85);
      await audio.play();
      state.liveAudioPlaying = true;
      state.liveAudioMissionId = monitor.mission_id || null;
      button.textContent = '■ Stop audio';
      setAudioConnection('CONNECTED', 'connected');
    } catch (error) {
      stopLiveAudio();
      setAudioConnection('ERROR', 'error');
      text('mission-operations-audio-detail', `Live audio could not start: ${error.message}`);
    }
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
      const cacheKey = image.modified || monitor.updated_at || image.size_kb || Date.now();
      const nextSrc = `${image.url}${separator}v=${encodeURIComponent(cacheKey)}`;
      if (img.getAttribute('src') !== nextSrc) img.src = nextSrc;
      img.classList.remove('hidden'); empty.classList.add('hidden');
      text('mission-operations-preview-state', image.live ? 'LIVE' : 'LATEST');
      const source = monitor.active ? 'LIVE' : 'LATEST';
      const telemetry = monitor.active
        ? ` · ${Number(monitor.frames || 0).toLocaleString('nl-NL')} frames · ${formatBytes(monitor.cadu_bytes || 0)} CADU`
        : '';
      text('mission-operations-preview-meta', `${source} · ${image.satellite || monitor.satellite || '-'} · ${image.product || image.filename || '-'} · ${image.resolution || '-'}${telemetry}`);
    } else {
      img.removeAttribute('src'); img.classList.add('hidden'); empty.classList.remove('hidden');
      text('mission-operations-preview-state', 'STANDBY'); text('mission-operations-preview-meta', '-');
    }
  };
  const updateLive = (snapshot, missionMonitor = {}) => {
    const summary = snapshot && snapshot.summary || {};
    const rf = snapshot && snapshot.live_rf || {};
    const iss = snapshot && snapshot.iss_voice || {};
    const audio = snapshot && snapshot.audio_monitor || {};
    const active = Boolean(summary.active);
    const isIss = summary.mission_type === 'iss_voice' || summary.plugin_id === 'iss_voice' || Boolean(iss.active);
    setMode(active);
    text('mission-operations-state', summary.status || 'IDLE');
    text('mission-operations-satellite', summary.satellite || 'No active mission');
    text('mission-operations-detail', active ? (summary.detail || 'Mission is active.') : 'Waiting for the next mission.');
    text('mission-operations-receiver', summary.receiver || summary.receiver_id || '-');
    const hz = Number(summary.frequency || 0);
    text('mission-operations-frequency', hz ? `${(hz / 1e6).toFixed(3)} MHz` : '-');
    text('mission-operations-elapsed', formatClock(summary.duration_seconds));
    text('mission-operations-remaining', formatClock(summary.remaining_seconds));
    text('mission-operations-snr', isIss ? 'N/A' : `${Number(summary.snr_db || 0).toFixed(2)} dB`);
    text('mission-operations-peak-snr', isIss ? 'N/A' : `${Number(summary.peak_snr_db || 0).toFixed(2)} dB`);
    text('mission-operations-frames', isIss ? 'N/A' : (summary.frames ?? 0));
    text('mission-operations-cadu', isIss ? 'N/A' : formatBytes(summary.cadu_bytes || 0));
    const elapsed = Number(summary.duration_seconds || 0); const remaining = Number(summary.remaining_seconds || 0);
    const progress = elapsed + remaining > 0 ? Math.min(100, (elapsed / (elapsed + remaining)) * 100) : (active ? 2 : 0);
    const bar = byId('mission-operations-progress'); if (bar) bar.style.width = `${progress}%`;

    const audioCard = byId('mission-operations-audio-monitor');
    if (audioCard) audioCard.classList.toggle('hidden', !isIss);
    text('mission-operations-audio-state', audio.stream_state || 'STANDBY');
    text('mission-operations-audio-iq', formatBytes(audio.iq_bytes || 0));
    text('mission-operations-audio-rate', audio.observed_byte_rate ? `${formatBytes(audio.observed_byte_rate)}/s` : '-');
    text('mission-operations-audio-sample-rate', audio.sample_rate_hz ? `${Number(audio.sample_rate_hz / 1000).toFixed(0)} kS/s` : '-');
    text('mission-operations-audio-detail', audio.detail || 'Waiting for an active ISS Voice IQ recording.');
    state.audioMonitor = audio;
    text('mission-operations-audio-transport', audio.transport === 'streaming_wav_pcm16' ? 'PCM WAV · 48 kHz' : '-');
    const play = byId('mission-operations-audio-play');
    if (play) {
      play.disabled = !audio.available;
      play.title = audio.available ? 'Start or stop the read-only live audio monitor' : (audio.detail || 'Live audio unavailable');
    }
    if ((!audio.available || !isIss || (state.liveAudioMissionId && state.liveAudioMissionId !== audio.mission_id)) && state.liveAudioPlaying) stopLiveAudio();
    if (!state.liveAudioPlaying) setAudioConnection(audio.available ? 'READY' : 'DISCONNECTED');

    if (isIss) setPreview({}); else setPreview(missionMonitor || {});
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
    const values = await Promise.allSettled([
      fetchJson('/api/mission-operations'),
      fetchJson('/api/mission-monitor')
    ]);
    const snapshot = values[0].status === 'fulfilled' ? values[0].value : {};
    const missionMonitor = values[1].status === 'fulfilled' ? values[1].value : {};
    updateLive(snapshot, missionMonitor);
    if (values[0].status === 'rejected') {
      text('mission-operations-detail', `Live status unavailable: ${values[0].reason.message}`);
    }
    if (values[1].status === 'rejected') {
      text('mission-operations-preview-meta', `Preview unavailable: ${values[1].reason.message}`);
    }
  };
  document.addEventListener('DOMContentLoaded', () => {
    const play = byId('mission-operations-audio-play');
    const volume = byId('mission-operations-audio-volume');
    const liveAudio = byId('mission-operations-live-audio');
    if (play) play.addEventListener('click', toggleLiveAudio);
    if (volume) volume.addEventListener('input', () => { if (liveAudio) liveAudio.volume = Number(volume.value); });
    if (liveAudio) {
      liveAudio.addEventListener('playing', () => setAudioConnection('CONNECTED', 'connected'));
      liveAudio.addEventListener('waiting', () => setAudioConnection('BUFFERING', 'connecting'));
      liveAudio.addEventListener('error', () => { if (state.liveAudioPlaying) { state.liveAudioPlaying = false; const b=byId('mission-operations-audio-play'); if(b)b.textContent='▶ Live audio'; setAudioConnection('ERROR','error'); } });
      liveAudio.addEventListener('ended', stopLiveAudio);
    }
    window.addEventListener('beforeunload', stopLiveAudio);
    refreshResults(); refreshLive();
    setInterval(refreshLive, 3000); setInterval(refreshResults, 15000);
  });
})();
