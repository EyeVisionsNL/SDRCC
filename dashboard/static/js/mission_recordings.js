async function refreshMissionRecordings() {
  const list = document.getElementById('mission-recordings-list');
  const audioWrap = document.getElementById('mission-recordings-audio-wrap');
  const audio = document.getElementById('mission-recordings-audio');
  const meta = document.getElementById('mission-recordings-meta');
  if (!list) return;
  try {
    const response = await fetch('/api/mission-recordings', {cache: 'no-store'});
    const data = await response.json();
    const rows = Array.isArray(data.recordings) ? data.recordings : [];
    list.innerHTML = rows.map((row, index) => `<button class="recording-item" data-url="${row.url}" data-kind="${row.kind}" data-name="${row.name}" data-size="${row.size_bytes}">${row.kind === 'audio' ? '🎵' : '🖼️'} <span>${row.name}</span><small>${(row.size_bytes/1048576).toFixed(1)} MB</small></button>`).join('') || '<p class="muted">Nog geen mission recordings gevonden.</p>';
    list.querySelectorAll('.recording-item').forEach(button => button.addEventListener('click', () => {
      if (button.dataset.kind === 'audio') {
        audio.src = button.dataset.url; audioWrap.classList.remove('hidden');
        meta.textContent = `${button.dataset.name} · ${(Number(button.dataset.size)/1048576).toFixed(1)} MB`;
      } else { window.open(button.dataset.url, '_blank', 'noopener'); }
    }));
    const firstAudio = list.querySelector('[data-kind="audio"]');
    if (firstAudio && !audio.src) firstAudio.click();
  } catch (error) { list.innerHTML = `<p class="error">Mission Recordings kon niet worden geladen: ${error}</p>`; }
}
document.addEventListener('DOMContentLoaded', () => { refreshMissionRecordings(); setInterval(refreshMissionRecordings, 15000); });
