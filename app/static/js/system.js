/**
 * Raspberry Pi System Diagnostics, Charts, and Service Management Controller.
 */

document.addEventListener('DOMContentLoaded', () => {
  const cpuVal = document.getElementById('sys-cpu-val');
  const tempVal = document.getElementById('sys-temp-val');
  const ramVal = document.getElementById('sys-ram-val');
  const diskVal = document.getElementById('sys-disk-val');
  const archVal = document.getElementById('sys-arch-val');
  const ramDetail = document.getElementById('sys-ram-detail');
  const diskDetail = document.getElementById('sys-disk-detail');
  const thermalStatus = document.getElementById('sys-thermal-status');
  const serviceStatusPill = document.getElementById('service-status-pill');
  const logConsole = document.getElementById('sys-log-console');
  const refreshLogsBtn = document.getElementById('refresh-logs-btn');

  const canvas = document.getElementById('sys-telemetry-chart');
  const ctx = canvas.getContext('2d');

  let historyData = {
    cpu: [],
    ram: [],
    temp: [],
    timestamps: []
  };

  // Poll metrics every 2.0s
  async function pollMetrics() {
    try {
      const res = await fetch('/api/system/metrics');
      const data = await res.json();

      cpuVal.textContent = `${data.cpu_percent || 0}%`;
      tempVal.textContent = `${data.cpu_temp_c || 42}°C`;
      ramVal.textContent = `${data.ram_percent || 0}%`;
      diskVal.textContent = `${data.disk_percent || 0}%`;

      archVal.textContent = `${data.machine || 'ARMv8'} | ${data.uptime_str || ''}`;
      ramDetail.textContent = `${data.ram_used_mb || 0} MB / ${data.ram_total_mb || 0} MB`;
      diskDetail.textContent = `${data.disk_free_gb || 0} GB Free of ${data.disk_total_gb || 0} GB`;

      if (data.cpu_temp_c > 75) {
        thermalStatus.textContent = 'High Temperature Warning!';
        thermalStatus.style.color = 'var(--accent-red)';
      } else {
        thermalStatus.textContent = 'Nominal Thermal State';
        thermalStatus.style.color = 'var(--accent-green)';
      }

      if (data.history) {
        historyData = data.history;
        drawChart();
      }
    } catch (e) {
      console.warn('Metrics poll failed:', e);
    }
  }

  // Draw Multi-line Resource Chart
  function drawChart() {
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let y = 0; y <= h; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    const maxPoints = 30;
    const stepX = w / (maxPoints - 1);

    function plotLine(arr, color, maxVal = 100) {
      if (!arr || arr.length < 2) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      arr.forEach((val, i) => {
        const x = i * stepX;
        const norm = Math.min(maxVal, Math.max(0, val)) / maxVal;
        const y = h - (norm * (h - 20)) - 10;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    plotLine(historyData.cpu, '#00f0ff', 100);
    plotLine(historyData.ram, '#7c4dff', 100);
    plotLine(historyData.temp, '#ff9100', 90);
  }

  // Check Service Status
  async function pollService() {
    try {
      const res = await fetch('/api/system/service/status');
      const d = await res.json();
      serviceStatusPill.textContent = d.status || 'Active';
      serviceStatusPill.className = `badge ${d.is_active ? 'badge-info' : 'badge-warning'}`;
    } catch (e) {
      // ignore
    }
  }

  // Fetch Logs
  async function fetchLogs() {
    try {
      const res = await fetch('/api/system/logs');
      const d = await res.json();
      const logs = d.logs || [];
      if (logs.length > 0) {
        logConsole.innerHTML = logs.map(l => {
          let color = '#a0aec0';
          if (l.includes('CRITICAL') || l.includes('ERROR')) color = '#ff1744';
          else if (l.includes('WARNING')) color = '#ff9100';
          else if (l.includes('INFO')) color = '#00f0ff';
          return `<div style="color:${color};">${escapeHtml(l)}</div>`;
        }).join('');
        logConsole.scrollTop = logConsole.scrollHeight;
      }
    } catch (e) {
      logConsole.textContent = 'Log fetch error.';
    }
  }

  function escapeHtml(str) {
    return str.replace(/[&<>"']/g, m => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
  }

  refreshLogsBtn.addEventListener('click', fetchLogs);

  setInterval(pollMetrics, 2000);
  setInterval(pollService, 4000);
  pollMetrics();
  pollService();
  fetchLogs();
});

// Service Actions Handler
window.triggerServiceAction = async (action) => {
  const msgBox = document.getElementById('service-action-msg');
  msgBox.textContent = `Executing '${action}'...`;
  try {
    const res = await fetch(`/api/system/service/${action}`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      msgBox.textContent = data.message || `Action ${action} succeeded.`;
      msgBox.style.color = 'var(--accent-green)';
    } else {
      msgBox.textContent = `Error: ${data.error}`;
      msgBox.style.color = 'var(--accent-red)';
    }
  } catch (err) {
    msgBox.textContent = `Request error: ${err.message}`;
    msgBox.style.color = 'var(--accent-red)';
  }
};
