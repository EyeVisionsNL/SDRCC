(() => {
  const state = {
    recordings: [],
    history: [],
    selected: null,
    audioMonitor: null,
    liveAudioPlaying: false,
    liveAudioConnecting: false,
    liveAudioMissionId: null,
    refreshingLive: false,
    refreshingResults: false
  };

  const byId = (id) => document.getElementById(id);
  const text = (id, value, fallback = '-') => {
    const element = byId(id);
    if (element) element.textContent = value ?? fallback;
  };
  const escapeHtml = (value) => String(value ?? '').replace(
    /[&<>'"]/g,
    character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character])
  );
  const formatBytes = (bytes) => {
    const value = Number(bytes || 0);
    if (value >= 1073741824) return `${(value / 1073741824).toFixed(1)} GB`;
    if (value >= 1048576) return `${(value / 1048576).toFixed(1)} MB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${value} B`;
  };
  const formatClock = (seconds, fallback = '00:00') => {
    if (seconds === null || seconds === undefined || seconds === '') return fallback;
    const value = Math.max(0, Number(seconds || 0));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const remainder = Math.floor(value % 60);
    return hours
      ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
      : `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  };
  const fetchJson = async (url) => {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  };
  const operationsVisible = () => {
    const tab = byId('tab-images');
    return document.visibilityState !== 'hidden' && Boolean(tab?.classList.contains('active'));
  };
  const normalized = (value) => String(value || '').trim().toUpperCase();
  const receiverLabel = (value) => {
    const receiver = normalized(value).replace(/[\s_-]+/g, '');
    if (['RECEIVER01', 'SDR1', 'RX01'].includes(receiver)) return 'SDR1';
    if (['RECEIVER02', 'SDR2', 'RX02'].includes(receiver)) return 'SDR2';
    return String(value || '-');
  };
  const statusTone = (value) => {
    const status = normalized(value);
    if (/FAILED|ERROR|FAULT|CANCELLED/.test(status)) return 'bad';
    if (/RECORDING|STREAMING|ACTIVE|LIVE/.test(status)) return 'live';
    if (/READY|AVAILABLE|SUCCESS|COMPLETE|CONNECTED/.test(status)) return 'good';
    if (/PREPAR|WAIT|BUFFER|START|STOPPING|FINALIZ|DEMODULAT/.test(status)) return 'warn';
    if (/IDLE|STANDBY|DISCONNECTED|NOT APPLICABLE/.test(status)) return 'standby';
    return 'info';
  };
  const setStateBadge = (id, value, explicitTone = null) => {
    const element = byId(id);
    if (!element) return;
    element.textContent = value || '-';
    element.className = `mission-operations-state ${explicitTone || statusTone(value)}`;
  };
  const satelliteTone = (value) => {
    const satellite = normalized(value);
    if (satellite.includes('M2-3') || satellite.includes('M2 3')) return 'is-meteor-3';
    if (satellite.includes('M2-4') || satellite.includes('M2 4')) return 'is-meteor-4';
    if (satellite.includes('ISS')) return 'is-iss';
    return 'is-neutral';
  };
  const applySatelliteTone = (element, satellite) => {
    if (!element) return;
    element.classList.remove('is-meteor-3', 'is-meteor-4', 'is-iss', 'is-neutral');
    element.classList.add(satelliteTone(satellite));
  };

  const setAudioConnection = (label, className = '') => {
    const element = byId('mission-operations-audio-connection');
    if (!element) return;
    element.textContent = label;
    element.className = `mission-operations-audio-connection ${className || statusTone(label)}`.trim();
  };
  const stopLiveAudio = () => {
    const audio = byId('mission-operations-live-audio');
    if (audio) {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    }
    state.liveAudioPlaying = false;
    state.liveAudioConnecting = false;
    state.liveAudioMissionId = null;
    const button = byId('mission-operations-audio-play');
    if (button) {
      button.textContent = '▶ Live audio';
      button.disabled = !(state.audioMonitor || {}).available;
    }
    setAudioConnection('DISCONNECTED', 'standby');
  };
  const toggleLiveAudio = async () => {
    const audio = byId('mission-operations-live-audio');
    const button = byId('mission-operations-audio-play');
    const monitor = state.audioMonitor || {};
    if (!audio || !button) return;
    if (state.liveAudioPlaying) {
      stopLiveAudio();
      return;
    }
    if (state.liveAudioConnecting || !monitor.available || !monitor.stream_url) return;
    try {
      state.liveAudioConnecting = true;
      button.disabled = true;
      setAudioConnection('CONNECTING', 'warn');
      audio.src = `${monitor.stream_url}&t=${Date.now()}`;
      audio.volume = Number(byId('mission-operations-audio-volume')?.value || 0.85);
      await audio.play();
      state.liveAudioConnecting = false;
      button.disabled = false;
      state.liveAudioPlaying = true;
      state.liveAudioMissionId = monitor.mission_id || null;
      button.textContent = '■ Stop audio';
      setAudioConnection('CONNECTED', 'good');
    } catch (error) {
      state.liveAudioConnecting = false;
      button.disabled = false;
      stopLiveAudio();
      setAudioConnection('ERROR', 'bad');
      text('mission-operations-audio-detail', `Live audio could not start: ${error.message}`);
    }
  };

  const setMode = (active, isIss) => {
    const badge = byId('mission-operations-mode-badge');
    if (!badge) return;
    badge.textContent = active ? (isIss ? 'ISS LIVE' : 'WEATHER LIVE') : 'STANDBY';
    badge.className = `mission-operations-badge ${active ? 'live' : 'standby'} ${isIss ? 'is-iss' : ''}`.trim();
  };
  const setPreview = (monitor) => {
    const image = monitor && monitor.image;
    const preview = byId('mission-operations-preview');
    const empty = byId('mission-operations-preview-empty');
    if (!preview || !empty) return;
    if (image && image.url) {
      const separator = image.url.includes('?') ? '&' : '?';
      const cacheKey = image.modified || monitor.updated_at || image.size_kb || Date.now();
      const nextSource = `${image.url}${separator}v=${encodeURIComponent(cacheKey)}`;
      if (preview.getAttribute('src') !== nextSource) preview.src = nextSource;
      preview.classList.remove('hidden');
      empty.classList.add('hidden');
      setStateBadge('mission-operations-preview-state', image.live ? 'LIVE' : 'LATEST', image.live ? 'live' : 'info');
      const source = monitor.active ? 'LIVE' : 'LATEST';
      const telemetry = monitor.active
        ? ` · ${Number(monitor.frames || 0).toLocaleString('en-GB')} frames · ${formatBytes(monitor.cadu_bytes || 0)} CADU`
        : '';
      text(
        'mission-operations-preview-meta',
        `${source} · ${image.satellite || monitor.satellite || '-'} · ${image.product || image.filename || '-'} · ${image.resolution || '-'}${telemetry}`
      );
      applySatelliteTone(byId('mission-operations-preview-card'), image.satellite || monitor.satellite);
    } else {
      preview.removeAttribute('src');
      preview.classList.add('hidden');
      empty.classList.remove('hidden');
      setStateBadge('mission-operations-preview-state', 'STANDBY', 'standby');
      text('mission-operations-preview-meta', '-');
      applySatelliteTone(byId('mission-operations-preview-card'), null);
    }
  };

  const updateLive = (snapshot, missionMonitor = {}) => {
    const summary = snapshot?.summary || {};
    const iss = snapshot?.iss_voice || {};
    const audio = snapshot?.audio_monitor || {};
    const consoleData = snapshot?.console || {};
    const missionConsole = consoleData.mission || {};
    const rfConsole = consoleData.rf || {};
    const recorderConsole = consoleData.recorder || {};
    const decoderConsole = consoleData.decoder || {};
    const runtimeConsole = consoleData.runtime || {};
    const active = Boolean(summary.active && missionConsole.active !== false);
    const isIss = active && (
      summary.mission_type === 'iss_voice' ||
      summary.plugin_id === 'iss_voice' ||
      missionConsole.mission_type === 'iss_voice' ||
      Boolean(iss.active)
    );
    const satellite = active ? (missionConsole.satellite || summary.satellite || 'Active mission') : null;

    setMode(active, isIss);
    const liveCard = byId('mission-operations-live-card');
    liveCard?.classList.toggle('is-idle', !active);
    liveCard?.classList.toggle('is-active', active);
    liveCard?.classList.toggle('is-iss', isIss);
    applySatelliteTone(liveCard, satellite);
    byId('mission-operations-idle')?.classList.toggle('hidden', active);
    byId('mission-operations-console')?.classList.toggle('hidden', !active);
    byId('mission-operations-progress-track')?.classList.toggle('hidden', !active);

    const missionState = active ? (missionConsole.state || summary.status || 'ACTIVE') : 'IDLE';
    setStateBadge('mission-operations-state', missionState, active ? statusTone(missionState) : 'standby');
    text('mission-operations-satellite', active ? satellite : 'No active mission');
    text('mission-operations-mission-id', active ? (missionConsole.mission_id || summary.mission_id || '-') : '-');
    text(
      'mission-operations-mission-type',
      active ? String(missionConsole.mission_type || (isIss ? 'iss_voice' : 'weather')).replaceAll('_', ' ').toUpperCase() : '-'
    );
    text('mission-operations-scheduler', active ? (runtimeConsole.scheduler_phase || '-') : '-');
    text(
      'mission-operations-detail',
      active ? (summary.detail || missionConsole.detail || 'Mission is active.') : 'Live details appear when a Weather or ISS mission starts.'
    );
    text('mission-operations-elapsed', active ? formatClock(summary.duration_seconds) : '-');
    text('mission-operations-remaining', active ? formatClock(summary.remaining_seconds, '-') : '-');

    text(
      'mission-operations-receiver',
      active ? receiverLabel(rfConsole.receiver || summary.receiver || summary.receiver_id) : '-'
    );
    const frequency = Number(active ? (rfConsole.frequency_hz || summary.frequency || 0) : 0);
    text('mission-operations-frequency', frequency ? `${(frequency / 1e6).toFixed(3)} MHz` : '-');
    text(
      'mission-operations-sample-rate',
      active && rfConsole.sample_rate_hz ? `${(Number(rfConsole.sample_rate_hz) / 1000).toFixed(0)} kS/s` : '-'
    );
    text('mission-operations-rf-mode', active ? (rfConsole.mode || '-') : '-');
    setStateBadge('mission-operations-rf-state', active && rfConsole.active ? 'ACTIVE' : 'STANDBY', active && rfConsole.active ? 'live' : 'standby');
    text('mission-operations-snr', isIss ? 'N/A' : (summary.snr_db == null ? '-' : `${Number(summary.snr_db).toFixed(2)} dB`));
    text('mission-operations-peak-snr', isIss ? 'N/A' : (summary.peak_snr_db == null ? '-' : `${Number(summary.peak_snr_db).toFixed(2)} dB`));
    byId('mission-operations-current-snr-cell')?.classList.toggle('hidden', isIss);
    byId('mission-operations-peak-snr-cell')?.classList.toggle('hidden', isIss);

    text('mission-operations-recorder-heading', isIss ? 'IQ Capture' : 'SatDump');
    setStateBadge('mission-operations-recorder-state', active ? (recorderConsole.status || 'STANDBY') : 'STANDBY');
    text('mission-operations-recorder-type', active ? String(recorderConsole.type || '-').replaceAll('_', ' ').toUpperCase() : '-');
    const captureMetrics = Boolean(active && recorderConsole.metrics_available);
    byId('mission-operations-recorder-group')?.classList.toggle('has-capture-metrics', captureMetrics);
    byId('mission-operations-recorder-bytes-cell')?.classList.toggle('hidden', !captureMetrics);
    byId('mission-operations-recorder-rate-cell')?.classList.toggle('hidden', !captureMetrics);
    text('mission-operations-recorder-bytes', captureMetrics ? formatBytes(recorderConsole.bytes || 0) : '-');
    text('mission-operations-recorder-rate', captureMetrics && recorderConsole.byte_rate ? `${formatBytes(recorderConsole.byte_rate)}/s` : '-');
    text('mission-operations-output', active ? (recorderConsole.output_path || summary.output_path || '-') : '-');

    const decoderApplicable = Boolean(active && decoderConsole.applicable !== false && !isIss);
    byId('mission-operations-decoder-group')?.classList.toggle('hidden', !decoderApplicable);
    setStateBadge('mission-operations-decoder-state', decoderApplicable ? (decoderConsole.status || 'STANDBY') : 'NOT APPLICABLE');
    text('mission-operations-decoder-pipeline', decoderApplicable ? (decoderConsole.pipeline || summary.pipeline || '-') : '-');
    text('mission-operations-frames', decoderApplicable ? (decoderConsole.frames ?? summary.frames ?? 0) : 'N/A');
    text('mission-operations-cadu', decoderApplicable ? formatBytes(decoderConsole.cadu_bytes || summary.cadu_bytes || 0) : 'N/A');
    text('mission-operations-images', decoderApplicable ? (decoderConsole.image_count ?? summary.image_count ?? 0) : 'N/A');

    text('mission-operations-authority', String(runtimeConsole.authority || snapshot?.authority || 'observer_only').replaceAll('_', ' ').toUpperCase());
    text('mission-operations-runtime-receiver', active ? (runtimeConsole.receiver_state || '-') : 'STANDBY');
    text('mission-operations-runtime-scheduler', runtimeConsole.scheduler_mode || '-');
    text('mission-operations-runtime-phase', runtimeConsole.scheduler_phase || '-');
    text('mission-operations-runtime-audio', runtimeConsole.audio_monitor_state || '-');
    text('mission-operations-runtime-clients', runtimeConsole.audio_clients ?? 0);

    const elapsed = Number(summary.duration_seconds || 0);
    const remaining = Number(summary.remaining_seconds || 0);
    const progress = elapsed + remaining > 0 ? Math.min(100, (elapsed / (elapsed + remaining)) * 100) : (active ? 2 : 0);
    const progressBar = byId('mission-operations-progress');
    if (progressBar) progressBar.style.width = `${progress}%`;

    const previewCard = byId('mission-operations-preview-card');
    const audioCard = byId('mission-operations-audio-monitor');
    previewCard?.classList.toggle('hidden', isIss);
    audioCard?.classList.toggle('hidden', !isIss);
    text('mission-operations-preview-title', active ? 'Live Weather Preview' : 'Latest Weather Image');

    setStateBadge('mission-operations-audio-state', audio.stream_state || 'STANDBY');
    text('mission-operations-audio-iq', formatBytes(audio.iq_bytes || 0));
    text('mission-operations-audio-rate', audio.observed_byte_rate ? `${formatBytes(audio.observed_byte_rate)}/s` : '-');
    text('mission-operations-audio-sample-rate', audio.sample_rate_hz ? `${Number(audio.sample_rate_hz / 1000).toFixed(0)} kS/s` : '-');
    text('mission-operations-audio-transport', audio.transport === 'streaming_wav_pcm16' ? 'PCM WAV · 48 kHz' : '-');
    text('mission-operations-audio-listeners', `${Number(audio.active_clients || 0)} / ${Number(audio.max_clients || 3)}`);
    text('mission-operations-audio-detail', audio.detail || 'Waiting for an active ISS Voice IQ recording.');
    state.audioMonitor = audio;
    const play = byId('mission-operations-audio-play');
    if (play) {
      play.disabled = state.liveAudioConnecting || !audio.available;
      play.title = audio.available ? 'Start or stop the read-only live audio monitor' : (audio.detail || 'Live audio unavailable');
    }
    if ((!audio.available || !isIss || (state.liveAudioMissionId && state.liveAudioMissionId !== audio.mission_id)) && state.liveAudioPlaying) {
      stopLiveAudio();
    }
    if (!state.liveAudioPlaying) setAudioConnection(audio.available ? 'READY' : 'DISCONNECTED', audio.available ? 'good' : 'standby');

    if (!isIss) setPreview(missionMonitor || {});
    text('mission-operations-updated', `Updated ${new Date().toLocaleTimeString('en-GB')}`);
  };

  const findHistory = (row) => {
    if (!row) return null;
    const direct = state.history.find(item => item.mission_id === row.mission_id);
    if (direct) return direct;
    const pathParts = String(row.relative_path || '').split('/').filter(Boolean);
    return state.history.find(item => {
      const outputName = String(item.output_path || '').split('/').filter(Boolean).pop();
      return Boolean(outputName && pathParts.includes(outputName));
    }) || null;
  };
  const renderSummary = (row) => {
    const mission = findHistory(row) || {};
    const satellite = mission.satellite || (row.kind === 'audio' ? 'ISS (ZARYA)' : '-');
    const result = mission.result || mission.status || (row.kind === 'audio' ? 'RECORDED' : '-');
    text('mission-operations-result-id', mission.mission_id || row.mission_id || '-');
    text('mission-operations-result-satellite', satellite);
    text('mission-operations-result-receiver', receiverLabel(mission.receiver || mission.receiver_id));
    text('mission-operations-result-pipeline', mission.pipeline || (row.kind === 'audio' ? 'wideband_iq_offline_fm' : '-'));
    text('mission-operations-result-status', result);
    text('mission-operations-result-duration', mission.duration_seconds != null ? formatClock(mission.duration_seconds) : '-');
    const resultElement = byId('mission-operations-result-status');
    if (resultElement) {
      const tone = statusTone(result);
      resultElement.className = `mission-operations-result-value ${tone}`;
      const resultCell = resultElement.closest('div');
      if (resultCell) resultCell.className = `is-${tone}`;
    }
    setStateBadge(
      'mission-operations-selected-kind',
      row.kind === 'audio' ? 'AUDIO' : 'IMAGE',
      satelliteTone(satellite)
    );
    applySatelliteTone(document.querySelector('.mission-recordings-player'), satellite);
  };
  const selectResult = (row) => {
    if (!row) return;
    state.selected = row;
    const audioWrap = byId('mission-recordings-audio-wrap');
    const audio = byId('mission-recordings-audio');
    const empty = byId('capture-empty-images');
    const content = byId('capture-content-images');
    document.querySelectorAll('.recording-item').forEach(element => {
      element.classList.toggle('selected', element.dataset.path === row.relative_path);
    });
    if (row.kind === 'audio') {
      if (audio && audio.getAttribute('src') !== row.url) audio.src = row.url;
      audioWrap?.classList.remove('hidden');
      text('mission-recordings-meta', `${findHistory(row)?.mission_id || row.mission_id || '-'} · ${row.name} · ${formatBytes(row.size_bytes)}`);
      content?.classList.add('hidden');
      empty?.classList.add('hidden');
    } else {
      audioWrap?.classList.add('hidden');
      if (audio?.getAttribute('src')) {
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
      }
      empty?.classList.add('hidden');
      content?.classList.remove('hidden');
      const image = byId('capture-image-images');
      if (image && image.getAttribute('src') !== row.url) image.src = row.url;
      text('capture-name-images', row.name);
      text('capture-size-images', (Number(row.size_bytes || 0) / 1024).toFixed(1));
      text('capture-modified-images', row.modified_epoch ? new Date(row.modified_epoch * 1000).toLocaleString('en-GB') : '-');
      const mission = findHistory(row) || {};
      text('capture-satellite-images', mission.satellite || '-');
      text('capture-pipeline-images', mission.pipeline || '-');
      text('capture-product-images', row.name || '-');
      text('capture-resolution-images', row.resolution || '-');
    }
    renderSummary(row);
  };
  const renderRecordings = () => {
    const list = byId('mission-recordings-list');
    if (!list) return;
    text('mission-operations-result-count', `${state.recordings.length} FILES`);
    list.innerHTML = state.recordings.map(row => {
      const mission = findHistory(row) || {};
      const satellite = mission.satellite || (row.kind === 'audio' ? 'ISS (ZARYA)' : '');
      const missionId = mission.mission_id || row.mission_id || '';
      return `<button class="recording-item ${satelliteTone(satellite)}" data-path="${escapeHtml(row.relative_path)}">` +
        `<span class="recording-item-icon">${row.kind === 'audio' ? '🎵' : '🖼️'}</span>` +
        `<span><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(missionId)}</small></span>` +
        `<small>${formatBytes(row.size_bytes)}</small></button>`;
    }).join('') || '<p class="mission-operations-empty">No mission results found.</p>';
    list.querySelectorAll('.recording-item').forEach((button, index) => {
      button.addEventListener('click', () => selectResult(state.recordings[index]));
    });
    const selectedPath = state.selected?.relative_path;
    const selected = state.recordings.find(row => row.relative_path === selectedPath) || state.recordings[0] || null;
    if (selected) selectResult(selected);
    else state.selected = null;
  };

  const refreshResults = async () => {
    if (state.refreshingResults || !operationsVisible()) return;
    state.refreshingResults = true;
    try {
      const [recordings, history] = await Promise.all([
        fetchJson('/api/mission-recordings'),
        fetchJson('/api/mission-history?limit=250')
      ]);
      state.recordings = Array.isArray(recordings.recordings) ? recordings.recordings : [];
      state.history = Array.isArray(history.missions) ? history.missions : (Array.isArray(history.history) ? history.history : []);
      renderRecordings();
    } catch (error) {
      const list = byId('mission-recordings-list');
      if (list) list.innerHTML = `<p class="error">Mission results could not be loaded: ${escapeHtml(error.message)}</p>`;
    } finally {
      state.refreshingResults = false;
    }
  };
  const refreshLive = async () => {
    if (state.refreshingLive || !operationsVisible()) return;
    state.refreshingLive = true;
    try {
      const values = await Promise.allSettled([
        fetchJson('/api/mission-operations'),
        fetchJson('/api/mission-monitor')
      ]);
      const snapshot = values[0].status === 'fulfilled' ? values[0].value : {};
      const missionMonitor = values[1].status === 'fulfilled' ? values[1].value : {};
      updateLive(snapshot, missionMonitor);
      if (values[0].status === 'rejected') {
        text('mission-operations-detail', `Live status unavailable: ${values[0].reason.message}`);
        setStateBadge('mission-operations-state', 'ERROR', 'bad');
      }
      if (values[1].status === 'rejected') {
        text('mission-operations-preview-meta', `Preview unavailable: ${values[1].reason.message}`);
      }
    } finally {
      state.refreshingLive = false;
    }
  };
  const refreshVisibleOperations = () => {
    if (!operationsVisible()) return;
    refreshLive();
    refreshResults();
  };

  document.addEventListener('DOMContentLoaded', () => {
    const play = byId('mission-operations-audio-play');
    const volume = byId('mission-operations-audio-volume');
    const liveAudio = byId('mission-operations-live-audio');
    play?.addEventListener('click', toggleLiveAudio);
    volume?.addEventListener('input', () => {
      if (liveAudio) liveAudio.volume = Number(volume.value);
    });
    if (liveAudio) {
      liveAudio.addEventListener('playing', () => setAudioConnection('CONNECTED', 'good'));
      liveAudio.addEventListener('waiting', () => setAudioConnection('BUFFERING', 'warn'));
      liveAudio.addEventListener('stalled', () => setAudioConnection('BUFFERING', 'warn'));
      liveAudio.addEventListener('canplay', () => {
        if (state.liveAudioConnecting) setAudioConnection('READY', 'good');
      });
      liveAudio.addEventListener('error', () => {
        if (!state.liveAudioPlaying && !state.liveAudioConnecting) return;
        state.liveAudioPlaying = false;
        state.liveAudioConnecting = false;
        const button = byId('mission-operations-audio-play');
        if (button) button.textContent = '▶ Live audio';
        setAudioConnection('ERROR', 'bad');
      });
      liveAudio.addEventListener('ended', stopLiveAudio);
    }
    document.querySelector('.tab-button[data-tab="images"]')?.addEventListener('click', () => {
      window.setTimeout(refreshVisibleOperations, 0);
    });
    document.addEventListener('visibilitychange', refreshVisibleOperations);
    window.addEventListener('beforeunload', stopLiveAudio);
    refreshVisibleOperations();
    window.setInterval(refreshLive, 3000);
    window.setInterval(refreshResults, 15000);
  });
})();
