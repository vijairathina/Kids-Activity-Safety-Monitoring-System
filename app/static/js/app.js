/**
 * Main Live Monitoring Dashboard Controller.
 * Handles SSE real-time safety stream, telemetry polling, and UI interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const liveImg = document.getElementById('live-stream-img');
  const toggleOverlayBtn = document.getElementById('toggle-overlay-btn');
  const takeSnapshotBtn = document.getElementById('take-snapshot-btn');
  const fullscreenBtn = document.getElementById('fullscreen-btn');
  const videoWrapper = document.getElementById('video-wrapper');
  const demoSelect = document.getElementById('demo-scenario-select');

  // Metrics
  const valAiFps = document.getElementById('val-ai-fps');
  const valInfMs = document.getElementById('val-inference-ms');
  const valCpuTemp = document.getElementById('val-cpu-temp');
  const valPersonCount = document.getElementById('val-person-count');
  const streamFpsBadge = document.getElementById('stream-fps-badge');
  const streamLatencyBadge = document.getElementById('stream-latency-badge');
  const camResolutionBadge = document.getElementById('cam-resolution-badge');

  // Sidebar / Header Indicators
  const topSafetyBadge = document.getElementById('top-safety-badge');
  const topSafetyText = document.getElementById('top-safety-text');
  const primaryActivityBadge = document.getElementById('primary-activity-badge');
  const activityDescText = document.getElementById('activity-desc-text');
  const activityConfidencePill = document.getElementById('activity-confidence-pill');
  const audioRmsVal = document.getElementById('audio-rms-val');
  const audioMeterBar = document.getElementById('audio-meter-bar');
  const eventsList = document.getElementById('events-stream-list');
  const emptyEventsMsg = document.getElementById('empty-events-msg');

  let overlayEnabled = true;

  // Request browser notification permissions
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  // 1. Overlay Toggle
  if (toggleOverlayBtn) {
    toggleOverlayBtn.addEventListener('click', () => {
      overlayEnabled = !overlayEnabled;
      liveImg.src = `/video_feed?overlay=${overlayEnabled}&t=${Date.now()}`;
      toggleOverlayBtn.querySelector('span').textContent = `Overlays: ${overlayEnabled ? 'ON' : 'OFF'}`;
      toggleOverlayBtn.classList.toggle('btn-primary', overlayEnabled);
    });
  }

  // 2. Snapshot
  if (takeSnapshotBtn) {
    takeSnapshotBtn.addEventListener('click', () => {
      window.open('/snapshot', '_blank');
    });
  }

  // 3. Fullscreen
  if (fullscreenBtn && videoWrapper) {
    fullscreenBtn.addEventListener('click', () => {
      if (!document.fullscreenElement) {
        videoWrapper.requestFullscreen().catch(err => alert(`Fullscreen error: ${err.message}`));
      } else {
        document.exitFullscreen();
      }
    });
  }

  // 4. Demo Scenario Switcher
  if (demoSelect) {
    demoSelect.addEventListener('change', async (e) => {
      const scenario = e.target.value;
      try {
        await fetch('/api/camera/demo_scenario', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scenario })
        });
      } catch (err) {
        console.error('Failed to change scenario:', err);
      }
    });
  }

  // 5. SSE Real-Time Event Pipeline
  function initSSE() {
    const evtSource = new EventSource('/events/stream');

    evtSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'NEW_SAFETY_EVENT' && data.event) {
          handleIncomingEvent(data.event);
        }
      } catch (err) {
        // Heartbeat or malformed
      }
    };

    evtSource.onerror = () => {
      console.warn('SSE stream disconnected, reconnecting in 3s...');
      evtSource.close();
      setTimeout(initSSE, 3000);
    };
  }
  initSSE();

  function handleIncomingEvent(event) {
    if (emptyEventsMsg) emptyEventsMsg.style.display = 'none';

    // Play chime sound based on severity
    if (window.KidsSafetyAudio) {
      window.KidsSafetyAudio.playChime(event.severity);
    }

    // Trigger Desktop Notification if permitted
    if ('Notification' in window && Notification.permission === 'granted') {
      const title = `Kids Safety: ${event.event_type.replace(/_/g, ' ')}`;
      const body = `${event.confidence_level}: ${event.details?.description || ''}`;
      new Notification(title, { body, icon: '/static/icons/shield.png' });
    }

    // Create and prepend event item card
    const item = document.createElement('div');
    const sevClass = (event.severity || 'INFO').toLowerCase();
    item.className = `event-item ${sevClass}`;

    const snapSrc = event.snapshot_path ? `/media/snapshots/${event.snapshot_path.split(/[\/\\]/).pop()}` : '';
    const imgHtml = snapSrc ? `<img src="${snapSrc}" class="event-thumb" alt="Thumb">` : `<div class="event-thumb" style="display:flex;align-items:center;justify-content:center;color:#666;">📹</div>`;

    const confPct = Math.round((event.confidence || 0) * 100);
    const timeFormatted = new Date(event.timestamp).toLocaleTimeString();

    item.innerHTML = `
      ${imgHtml}
      <div class="event-info">
        <div class="event-header-row">
          <span class="event-name">${event.event_type.replace(/_/g, ' ')}</span>
          <span class="event-time">${timeFormatted}</span>
        </div>
        <div class="event-desc">${event.details?.description || 'Safety condition triggered.'}</div>
        <div style="display: flex; gap: 6px; margin-top: 4px;">
          <span class="badge badge-${sevClass}">${event.severity}</span>
          <span class="badge badge-subtle">${event.confidence_level} (${confPct}%)</span>
        </div>
      </div>
    `;

    eventsList.insertBefore(item, eventsList.firstChild);

    // Limit visible stream to 15 items
    while (eventsList.children.length > 15) {
      eventsList.removeChild(eventsList.lastChild);
    }
  }

  // 6. Polling Telemetry State (/api/status) every 1.5 seconds
  async function pollStatus() {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const data = await res.json();

      // Camera telemetry
      if (data.camera) {
        streamFpsBadge.textContent = `${data.camera.fps || 0} FPS`;
        streamLatencyBadge.textContent = `${data.camera.latency_ms || 0} ms`;
        camResolutionBadge.textContent = data.camera.resolution || '640x480';
        document.getElementById('nav-cam-text').textContent = `Camera: ${data.camera.connected ? 'ONLINE' : 'OFFLINE'}`;
        document.getElementById('nav-cam-dot').className = `status-dot ${data.camera.connected ? 'green' : 'red'}`;
      }

      // AI & Activity telemetry
      if (data.ai) {
        valAiFps.textContent = `${data.ai.ai_fps || 0} FPS`;
        valInfMs.textContent = `${data.ai.inference_ms || 0} ms`;
        valPersonCount.textContent = data.ai.tracked_persons_count || 0;
        document.getElementById('nav-fps-badge').textContent = `${data.ai.ai_fps || 0} FPS`;

        // Update Safety Status pill
        const status = data.ai.safety_status || 'NORMAL';
        topSafetyBadge.className = `safety-status-pill ${status.toLowerCase()}`;
        topSafetyText.textContent = `STATUS: ${status}`;

        // Primary Activity Display
        if (data.ai.tracked_persons && data.ai.tracked_persons.length > 0) {
          const p = data.ai.tracked_persons[0];
          updateActivityDisplay(p.state, p.zone);
        } else {
          updateActivityDisplay('NO_PERSON_DETECTED', 'Room Empty');
        }

        // Audio Metrics
        if (data.ai.audio_metrics) {
          const rms = data.ai.audio_metrics.rms || 0;
          audioRmsVal.textContent = `RMS: ${rms.toFixed(2)}`;
          const meterPct = Math.min(100, Math.round(rms * 200));
          audioMeterBar.style.width = `${meterPct}%`;
        }
      }

      // System telemetry
      if (data.system) {
        valCpuTemp.textContent = `${data.system.cpu_percent || 0}% / ${data.system.cpu_temp_c || 42}°C`;
      }

    } catch (err) {
      console.warn('Status poll failed:', err);
    }
  }

  function updateActivityDisplay(state, zone) {
    let colorStyle = 'background: rgba(0, 230, 118, 0.15); color: var(--accent-green); border: 1px solid rgba(0, 230, 118, 0.3);';
    let text = state.replace(/_/g, ' ');
    let desc = `Active in zone: ${zone || 'Open Room'}`;
    let qualifier = 'DETECTED';

    if (state.includes('FALL')) {
      colorStyle = 'background: rgba(255, 23, 68, 0.2); color: var(--accent-red); border: 1px solid rgba(255, 23, 68, 0.5);';
      qualifier = 'POSSIBLE';
      desc = 'Horizontal posture sustained on ground. Caregiver verification advised.';
    } else if (state.includes('DANGER') || state.includes('CONFLICT')) {
      colorStyle = 'background: rgba(255, 145, 0, 0.2); color: var(--accent-amber); border: 1px solid rgba(255, 145, 0, 0.4);';
      qualifier = 'POSSIBLE';
      desc = 'Interaction with restricted zone or rapid proximity.';
    } else if (state === 'WATCHING_TV') {
      colorStyle = 'background: rgba(0, 240, 255, 0.18); color: var(--accent-cyan); border: 1px solid rgba(0, 240, 255, 0.4);';
      desc = 'Child is seated and actively watching TV.';
      qualifier = 'DETECTED';
    } else if (state === 'DANCING') {
      colorStyle = 'background: rgba(236, 72, 153, 0.2); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.4);';
      desc = 'Rhythmic energetic motion and arm movements detected.';
      qualifier = 'DETECTED';
    } else if (state === 'PLAYING') {
      colorStyle = 'background: rgba(0, 230, 118, 0.18); color: var(--accent-green); border: 1px solid rgba(0, 230, 118, 0.4);';
      desc = 'Active floor play or interaction in safe play area.';
      qualifier = 'DETECTED';
    } else if (state === 'READING') {
      colorStyle = 'background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4);';
      desc = 'Focused posture with book, tablet, or learning material.';
      qualifier = 'DETECTED';
    } else if (state === 'WRITING') {
      colorStyle = 'background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4);';
      desc = 'Seated at table/desk with hands engaged on surface.';
      qualifier = 'DETECTED';
    }

    primaryActivityBadge.style.cssText = colorStyle;
    primaryActivityBadge.textContent = text;
    activityDescText.textContent = desc;
    activityConfidencePill.textContent = qualifier;
  }

  // 360-Degree ONVIF PTZ Controls Handler
  function initPTZControls() {
    const btnUp = document.getElementById('ptz-btn-up');
    const btnDown = document.getElementById('ptz-btn-down');
    const btnLeft = document.getElementById('ptz-btn-left');
    const btnRight = document.getElementById('ptz-btn-right');
    const btnStop = document.getElementById('ptz-btn-stop');
    const btnStepLeft = document.getElementById('ptz-step-left');
    const btnStepRight = document.getElementById('ptz-step-right');
    const speedSlider = document.getElementById('ptz-speed-slider');
    const speedVal = document.getElementById('ptz-speed-val');
    const posDisplay = document.getElementById('ptz-pos-display');
    const motionBadge = document.getElementById('ptz-motion-badge');

    if (!btnUp) return;

    if (speedSlider && speedVal) {
      speedSlider.addEventListener('input', (e) => {
        speedVal.textContent = e.target.value;
      });
    }

    async function sendPTZMove(direction, duration = 0.4) {
      const speed = parseFloat(speedSlider ? speedSlider.value : 0.4);
      if (motionBadge) {
        motionBadge.textContent = 'ROTATING...';
        motionBadge.style.color = 'var(--accent-cyan)';
      }
      try {
        await fetch('/api/camera/ptz/move', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ direction, speed, duration })
        });
      } catch (err) {
        console.error('PTZ move failed:', err);
      }
    }

    async function sendPTZStep(direction, step = 0.15) {
      if (motionBadge) {
        motionBadge.textContent = 'STEPPING...';
        motionBadge.style.color = 'var(--accent-cyan)';
      }
      try {
        await fetch('/api/camera/ptz/step', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ direction, step })
        });
      } catch (err) {
        console.error('PTZ step failed:', err);
      }
    }

    async function sendPTZStop() {
      try {
        await fetch('/api/camera/ptz/stop', { method: 'POST' });
        if (motionBadge) {
          motionBadge.textContent = 'STATIC VIEW';
          motionBadge.style.color = 'var(--text-muted)';
        }
      } catch (err) {
        console.error('PTZ stop failed:', err);
      }
    }

    btnUp.addEventListener('click', () => sendPTZMove('up'));
    btnDown.addEventListener('click', () => sendPTZMove('down'));
    btnLeft.addEventListener('click', () => sendPTZMove('left'));
    btnRight.addEventListener('click', () => sendPTZMove('right'));
    btnStop.addEventListener('click', sendPTZStop);

    if (btnStepLeft) btnStepLeft.addEventListener('click', () => sendPTZStep('left', 0.15));
    if (btnStepRight) btnStepRight.addEventListener('click', () => sendPTZStep('right', 0.15));

    // Keyboard Arrow Keys (Shift + Arrows for PTZ control)
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.shiftKey) {
        if (e.key === 'ArrowUp') { e.preventDefault(); sendPTZMove('up'); }
        if (e.key === 'ArrowDown') { e.preventDefault(); sendPTZMove('down'); }
        if (e.key === 'ArrowLeft') { e.preventDefault(); sendPTZMove('left'); }
        if (e.key === 'ArrowRight') { e.preventDefault(); sendPTZMove('right'); }
        if (e.key === ' ') { e.preventDefault(); sendPTZStop(); }
      }
    });

    // Periodic PTZ status poll
    setInterval(async () => {
      try {
        const res = await fetch('/api/camera/ptz/status');
        const data = await res.json();
        if (posDisplay && data.position) {
          posDisplay.textContent = `Pan: ${data.position.pan?.toFixed(2) ?? '0.00'} | Tilt: ${data.position.tilt?.toFixed(2) ?? '0.00'}`;
        }
        if (motionBadge) {
          if (data.is_moving) {
            motionBadge.textContent = 'ROTATING (ALERTS PAUSED)';
            motionBadge.style.color = '#00f0ff';
            motionBadge.style.borderColor = 'rgba(0, 240, 255, 0.5)';
          } else {
            motionBadge.textContent = 'STATIC VIEW';
            motionBadge.style.color = 'var(--text-muted)';
            motionBadge.style.borderColor = 'transparent';
          }
        }
      } catch (err) {
        // silent
      }
    }, 2000);
  }

  initPTZControls();

  setInterval(pollStatus, 1500);
  pollStatus();
});

// Helper for test sound triggers
async function triggerTestAudio(type) {
  try {
    await fetch('/api/test/trigger_sound', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sound_type: type })
    });
  } catch (e) {
    console.error(e);
  }
}
