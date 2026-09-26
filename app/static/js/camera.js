/**
 * Camera Settings and ONVIF Network Scanner Controller.
 */

document.addEventListener('DOMContentLoaded', async () => {
  const sourceTypeSelect = document.getElementById('cam-source-type');
  const rtspFields = document.getElementById('rtsp-fields');
  const rtspUrlInput = document.getElementById('cam-rtsp-url');
  const subUrlInput = document.getElementById('cam-sub-url');
  const ipInput = document.getElementById('cam-ip');
  const portInput = document.getElementById('cam-port');
  const userInput = document.getElementById('cam-user');
  const passInput = document.getElementById('cam-pass');
  const widthInput = document.getElementById('cam-width');
  const heightInput = document.getElementById('cam-height');
  const fpsInput = document.getElementById('cam-fps');

  const saveBtn = document.getElementById('save-cam-btn');
  const testBtn = document.getElementById('test-cam-btn');
  const testResult = document.getElementById('cam-test-result');
  const scanOnvifBtn = document.getElementById('scan-onvif-btn');
  const onvifResultsBox = document.getElementById('onvif-results-box');

  const diagSource = document.getElementById('diag-source');
  const diagStatus = document.getElementById('diag-status');
  const diagFps = document.getElementById('diag-fps');
  const diagLatency = document.getElementById('diag-latency');
  const diagRes = document.getElementById('diag-res');
  const diagFrames = document.getElementById('diag-frames');
  const previewStatusPill = document.getElementById('preview-status-pill');

  // Toggle RTSP fields visibility
  function updateSourceVisibility() {
    rtspFields.style.display = sourceTypeSelect.value === 'rtsp' ? 'block' : 'none';
  }
  sourceTypeSelect.addEventListener('change', updateSourceVisibility);

  // Load existing config
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    if (cfg && cfg.camera) {
      const c = cfg.camera;
      sourceTypeSelect.value = c.source_type || 'demo';
      rtspUrlInput.value = c.rtsp_url || '';
      subUrlInput.value = c.sub_stream_url || '';
      ipInput.value = c.ip || '192.168.1.100';
      portInput.value = c.onvif_port || 80;
      userInput.value = c.username || 'admin';
      widthInput.value = c.width || 640;
      heightInput.value = c.height || 480;
      fpsInput.value = c.fps || 15;
      updateSourceVisibility();
    }
  } catch (err) {
    console.error('Failed to load camera settings:', err);
  }

  // Save Settings
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Connecting...';
    try {
      const payload = {
        source_type: sourceTypeSelect.value,
        rtsp_url: rtspUrlInput.value.trim(),
        sub_stream_url: subUrlInput.value.trim(),
        ip: ipInput.value.trim(),
        onvif_port: parseInt(portInput.value) || 80,
        username: userInput.value.trim(),
        password: passInput.value.trim(),
        width: parseInt(widthInput.value) || 640,
        height: parseInt(heightInput.value) || 480,
        fps: parseInt(fpsInput.value) || 15
      };

      const res = await fetch('/api/camera/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        alert('Camera settings saved! Stream reconnected.');
        const preview = document.getElementById('preview-img');
        if (preview) preview.src = `/video_feed?overlay=true&t=${Date.now()}`;
      }
    } catch (err) {
      alert(`Save error: ${err.message}`);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save & Connect';
    }
  });

  // Test Camera
  testBtn.addEventListener('click', async () => {
    testResult.textContent = 'Probing camera...';
    testResult.style.color = 'var(--accent-cyan)';
    try {
      const res = await fetch('/api/camera/status');
      const data = await res.json();
      if (data.connected) {
        testResult.textContent = `Connected! ${data.resolution} @ ${data.fps} FPS`;
        testResult.style.color = 'var(--accent-green)';
      } else {
        testResult.textContent = `Connection failed: ${data.last_error || 'Unreachable'}`;
        testResult.style.color = 'var(--accent-red)';
      }
    } catch (err) {
      testResult.textContent = `Error: ${err.message}`;
      testResult.style.color = 'var(--accent-red)';
    }
  });

  // Unified Camera Finder (ONVIF + LAN Subnet + USB Webcams)
  const findAllBtn = document.getElementById('find-all-cams-btn');
  const resultsBox = document.getElementById('camera-finder-results');
  const subnetBadge = document.getElementById('scanner-subnet-badge');

  if (findAllBtn) {
    findAllBtn.addEventListener('click', async () => {
      findAllBtn.disabled = true;
      findAllBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
        <span>Scanning Network & USB...</span>
      `;
      resultsBox.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px;">Scanning local subnet for ONVIF cameras, open RTSP ports, and USB video devices...</p>';

      try {
        const res = await fetch('/api/camera/find_all', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: userInput.value.trim() || 'admin',
            password: passInput.value.trim(),
            include_webcams: true
          })
        });
        const resp = await res.json();

        if (resp.success && resp.data) {
          const d = resp.data;
          subnetBadge.textContent = `Subnet: ${d.subnet}`;

          const cameras = d.cameras || [];
          const webcams = d.webcams || [];

          if (cameras.length === 0 && webcams.length === 0) {
            resultsBox.innerHTML = `
              <div style="background:rgba(255,145,0,0.1);border:1px solid rgba(255,145,0,0.3);padding:14px;border-radius:var(--radius-sm);color:var(--text-muted);">
                <div style="font-weight:600;color:var(--accent-amber);margin-bottom:4px;">No Cameras Found on ${d.subnet}</div>
                No ONVIF or RTSP cameras responded. Ensure your IP camera is powered on and connected to the same Wi-Fi/LAN router. You can still manually enter the RTSP stream URL in the form above.
              </div>
            `;
          } else {
            let html = `
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Device</th>
                    <th>Type / Method</th>
                    <th>Endpoint / Port</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
            `;

            // List local webcams
            webcams.forEach(w => {
              html += `
                <tr>
                  <td>
                    <div style="font-weight:600;color:var(--text-main);">${w.name}</div>
                    <div style="font-size:11px;color:var(--text-dim);">${w.resolution} @ ${w.fps} FPS</div>
                  </td>
                  <td><span class="badge badge-info">USB / Integrated</span></td>
                  <td style="font-family:monospace;font-size:12px;">Index ${w.index} (/dev/video${w.index})</td>
                  <td>
                    <button class="btn btn-primary" style="font-size:11px;padding:4px 10px;" onclick="selectCameraDevice('webcam', '${w.name}', '${w.index}', '', 0)">
                      Connect Webcam
                    </button>
                  </td>
                </tr>
              `;
            });

            // List IP cameras
            cameras.forEach(c => {
              const methodBadge = c.detection_method === 'ONVIF WS-Discovery'
                ? '<span class="badge badge-info">ONVIF</span>'
                : '<span class="badge badge-subtle">RTSP Port 554</span>';

              html += `
                <tr>
                  <td>
                    <div style="font-weight:600;color:var(--text-main);">${c.name}</div>
                    <div style="font-size:11px;color:var(--text-dim);">IP: ${c.ip}</div>
                  </td>
                  <td>${methodBadge}</td>
                  <td>
                    <div style="font-family:monospace;font-size:11px;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${c.main_stream}">
                      ${c.main_stream}
                    </div>
                  </td>
                  <td>
                    <div style="display:flex;gap:6px;">
                      <button class="btn btn-glass" style="font-size:11px;padding:4px 8px;" onclick="testCameraStream('${c.main_stream}')">
                        Test
                      </button>
                      <button class="btn btn-primary" style="font-size:11px;padding:4px 10px;" onclick="selectCameraDevice('rtsp', '${c.name}', '${c.main_stream}', '${c.sub_stream}', ${c.onvif_port}, '${c.ip}')">
                        Connect
                      </button>
                    </div>
                  </td>
                </tr>
              `;
            });

            html += '</tbody></table>';
            resultsBox.innerHTML = html;
          }
        } else {
          resultsBox.innerHTML = `<p style="color:var(--accent-red);padding:10px;">Scan failed: ${resp.error || 'Unknown error'}</p>`;
        }
      } catch (err) {
        resultsBox.innerHTML = `<p style="color:var(--accent-red);padding:10px;">Network scan error: ${err.message}</p>`;
      } finally {
        findAllBtn.disabled = false;
        findAllBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <span>Find Cameras</span>
        `;
      }
    });
  }

  // Poll Diagnostics
  async function pollDiagnostics() {
    try {
      const res = await fetch('/api/camera/status');
      if (!res.ok) return;
      const d = await res.json();

      diagSource.textContent = d.source || 'none';
      diagStatus.textContent = d.connected ? 'Connected' : 'Offline';
      diagStatus.style.color = d.connected ? 'var(--accent-green)' : 'var(--accent-red)';
      diagFps.textContent = `${d.fps || 0} FPS`;
      diagLatency.textContent = `${d.latency_ms || 0} ms`;
      diagRes.textContent = d.resolution || '640x480';
      diagFrames.textContent = d.frame_count || 0;
      previewStatusPill.textContent = d.connected ? 'STREAM ACTIVE' : 'CONNECTING';
      previewStatusPill.className = `badge ${d.connected ? 'badge-info' : 'badge-warning'}`;
    } catch (e) {
      // ignore
    }
  }
  setInterval(pollDiagnostics, 2000);
  pollDiagnostics();
});

// Test RTSP Stream URL
window.testCameraStream = async (url) => {
  if (!url) return;
  alert(`Testing connection to ${url}...`);
  try {
    const res = await fetch('/api/camera/test_rtsp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rtsp_url: url })
    });
    const d = await res.json();
    if (d.success) {
      alert(`Success! Camera stream opened (${d.resolution}).`);
    } else {
      alert(`Stream test failed: ${d.error || 'Connection timed out'}`);
    }
  } catch (err) {
    alert(`Test error: ${err.message}`);
  }
};

// One-click Camera Activation
window.selectCameraDevice = async (type, name, mainStreamOrIndex, subStream, onvifPort, ip) => {
  const user = document.getElementById('cam-user').value.trim();
  const pass = document.getElementById('cam-pass').value.trim();

  try {
    let payload = {
      type: type,
      name: name
    };

    if (type === 'webcam') {
      document.getElementById('cam-source-type').value = 'webcam';
      document.getElementById('rtsp-fields').style.display = 'none';
    } else {
      document.getElementById('cam-source-type').value = 'rtsp';
      document.getElementById('rtsp-fields').style.display = 'block';
      document.getElementById('cam-ip').value = ip || '';
      document.getElementById('cam-port').value = onvifPort || 80;
      document.getElementById('cam-rtsp-url').value = mainStreamOrIndex;
      document.getElementById('cam-sub-url').value = subStream || mainStreamOrIndex;

      payload.ip = ip;
      payload.onvif_port = onvifPort;
      payload.main_stream = mainStreamOrIndex;
      payload.sub_stream = subStream || mainStreamOrIndex;
      payload.username = user;
      payload.password = pass;
    }

    const res = await fetch('/api/camera/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const d = await res.json();

    if (d.success) {
      alert(`Camera '${name}' connected successfully! Live stream updated.`);
      const preview = document.getElementById('preview-img');
      if (preview) preview.src = `/video_feed?overlay=true&t=${Date.now()}`;
    }
  } catch (err) {
    alert(`Failed to activate camera: ${err.message}`);
  }
};

// Legacy helper for one-click ONVIF selection
window.selectOnvifDevice = (ip, port) => {
  window.selectCameraDevice('rtsp', `ONVIF (${ip})`, `rtsp://${ip}:554/live/ch0`, `rtsp://${ip}:554/live/ch1`, port, ip);
};
