/**
 * Interactive HTML5 Canvas Danger Zone Editor Controller.
 */

document.addEventListener('DOMContentLoaded', async () => {
  const canvas = document.getElementById('zone-canvas');
  const ctx = canvas.getContext('2d');
  const mouseCoords = document.getElementById('canvas-mouse-coords');

  const modePolyBtn = document.getElementById('mode-poly-btn');
  const modeRectBtn = document.getElementById('mode-rect-btn');
  const refreshBgBtn = document.getElementById('refresh-bg-btn');
  const saveAllZonesBtn = document.getElementById('save-all-zones-btn');
  const deleteZoneBtn = document.getElementById('delete-zone-btn');

  // Inspector inputs
  const zoneNameInput = document.getElementById('zone-name-input');
  const zoneTypeSelect = document.getElementById('zone-type-select');
  const zoneSeveritySelect = document.getElementById('zone-severity-select');
  const zoneColorInput = document.getElementById('zone-color-input');
  const zoneDurationInput = document.getElementById('zone-duration-input');
  const zoneAlertAction = document.getElementById('zone-alert-action');
  const zonesCountBadge = document.getElementById('zones-count-badge');
  const zonesChipList = document.getElementById('zones-chip-list');

  let zones = [];
  let selectedZoneIndex = -1;
  let drawMode = 'select'; // 'select', 'polygon', 'rectangle'
  let currentDrawingPoints = [];
  let isDraggingVertex = false;
  let draggedVertexInfo = null; // { zoneIndex, vertexIndex }
  let rectStartPoint = null;

  // Background Image
  const bgImage = new Image();
  bgImage.onload = () => drawCanvas();
  function loadBgSnapshot() {
    bgImage.src = `/snapshot?t=${Date.now()}`;
  }
  loadBgSnapshot();
  refreshBgBtn.addEventListener('click', loadBgSnapshot);

  // Fetch Existing Zones
  try {
    const res = await fetch('/api/zones');
    const data = await res.json();
    zones = data.zones || [];
    updateZonesList();
    if (zones.length > 0) selectZone(0);
  } catch (err) {
    console.error('Failed to load zones:', err);
  }

  // Tool Modes
  modePolyBtn.addEventListener('click', () => {
    drawMode = 'polygon';
    currentDrawingPoints = [];
    modePolyBtn.classList.add('btn-primary');
    modeRectBtn.classList.remove('btn-primary');
  });

  modeRectBtn.addEventListener('click', () => {
    drawMode = 'rectangle';
    currentDrawingPoints = [];
    rectStartPoint = null;
    modeRectBtn.classList.add('btn-primary');
    modePolyBtn.classList.remove('btn-primary');
  });

  function resetMode() {
    drawMode = 'select';
    currentDrawingPoints = [];
    rectStartPoint = null;
    modePolyBtn.classList.remove('btn-primary');
    modeRectBtn.classList.remove('btn-primary');
    drawCanvas();
  }

  // Canvas Mouse Coordinates Helper
  function getCanvasCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: Math.round((e.clientX - rect.left) * scaleX),
      y: Math.round((e.clientY - rect.top) * scaleY)
    };
  }

  // Draw Function
  function drawCanvas() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 1. Draw background snapshot
    if (bgImage.complete && bgImage.naturalWidth > 0) {
      ctx.drawImage(bgImage, 0, 0, canvas.width, canvas.height);
    } else {
      ctx.fillStyle = '#111827';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // 2. Draw existing zones
    zones.forEach((z, idx) => {
      const isSelected = idx === selectedZoneIndex;
      const pts = z.points || [];
      if (pts.length < 3) return;

      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i][0], pts[i][1]);
      }
      ctx.closePath();

      // Fill with semi-transparent zone color
      ctx.fillStyle = hexToRgba(z.color || '#ff3366', isSelected ? 0.38 : 0.22);
      ctx.fill();

      // Outline
      ctx.strokeStyle = z.color || '#ff3366';
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.stroke();

      // Zone label
      ctx.fillStyle = '#fff';
      ctx.font = '12px Inter, sans-serif';
      ctx.fillText(`${z.name} [${z.type}]`, pts[0][0], Math.max(16, pts[0][1] - 8));

      // Control vertices for selected zone
      if (isSelected) {
        pts.forEach((pt, vIdx) => {
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], 6, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.fill();
          ctx.strokeStyle = '#000000';
          ctx.lineWidth = 2;
          ctx.stroke();
        });
      }
    });

    // 3. Draw in-progress polygon points
    if (drawMode === 'polygon' && currentDrawingPoints.length > 0) {
      ctx.beginPath();
      ctx.moveTo(currentDrawingPoints[0][0], currentDrawingPoints[0][1]);
      for (let i = 1; i < currentDrawingPoints.length; i++) {
        ctx.lineTo(currentDrawingPoints[i][0], currentDrawingPoints[i][1]);
      }
      ctx.strokeStyle = '#00f0ff';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      currentDrawingPoints.forEach(pt => {
        ctx.beginPath();
        ctx.arc(pt[0], pt[1], 4, 0, Math.PI * 2);
        ctx.fillStyle = '#00f0ff';
        ctx.fill();
      });
    }

    // 4. Draw in-progress rectangle
    if (drawMode === 'rectangle' && rectStartPoint && currentDrawingPoints.length === 1) {
      const p1 = rectStartPoint;
      const p2 = currentDrawingPoints[0];
      ctx.strokeStyle = '#00f0ff';
      ctx.lineWidth = 2;
      ctx.strokeRect(Math.min(p1.x, p2.x), Math.min(p1.y, p2.y), Math.abs(p2.x - p1.x), Math.abs(p2.y - p1.y));
    }
  }

  function hexToRgba(hex, alpha = 0.3) {
    let c = hex.replace('#', '');
    if (c.length === 3) c = c.split('').map(x => x + x).join('');
    const num = parseInt(c, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
  }

  // Mouse Interactions
  canvas.addEventListener('mousemove', (e) => {
    const coords = getCanvasCoords(e);
    mouseCoords.textContent = `X: ${coords.x}, Y: ${coords.y}`;

    if (isDraggingVertex && draggedVertexInfo) {
      const z = zones[draggedVertexInfo.zoneIndex];
      if (z && z.points[draggedVertexInfo.vertexIndex]) {
        z.points[draggedVertexInfo.vertexIndex] = [coords.x, coords.y];
        drawCanvas();
      }
      return;
    }

    if (drawMode === 'rectangle' && rectStartPoint) {
      currentDrawingPoints = [{ x: coords.x, y: coords.y }];
      drawCanvas();
    }
  });

  canvas.addEventListener('mousedown', (e) => {
    const coords = getCanvasCoords(e);

    // Check if clicking existing vertex in selected zone
    if (selectedZoneIndex >= 0 && selectedZoneIndex < zones.length) {
      const pts = zones[selectedZoneIndex].points || [];
      for (let i = 0; i < pts.length; i++) {
        const dist = Math.hypot(pts[i][0] - coords.x, pts[i][1] - coords.y);
        if (dist <= 10) {
          isDraggingVertex = true;
          draggedVertexInfo = { zoneIndex: selectedZoneIndex, vertexIndex: i };
          return;
        }
      }
    }

    if (drawMode === 'polygon') {
      // Check if closing polygon by clicking near start
      if (currentDrawingPoints.length >= 3) {
        const start = currentDrawingPoints[0];
        if (Math.hypot(start[0] - coords.x, start[1] - coords.y) <= 15) {
          finishNewPolygon();
          return;
        }
      }
      currentDrawingPoints.push([coords.x, coords.y]);
      drawCanvas();
    } else if (drawMode === 'rectangle') {
      if (!rectStartPoint) {
        rectStartPoint = coords;
      } else {
        // Complete rectangle
        const x1 = Math.min(rectStartPoint.x, coords.x);
        const y1 = Math.min(rectStartPoint.y, coords.y);
        const x2 = Math.max(rectStartPoint.x, coords.x);
        const y2 = Math.max(rectStartPoint.y, coords.y);

        const newZone = {
          id: `zone_${Date.now()}`,
          name: `Zone ${zones.length + 1}`,
          type: 'DANGER_ZONE',
          points: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
          color: '#ff9900',
          severity: 'WARNING',
          min_duration_sec: 1.5,
          alert_action: 'immediate'
        };
        zones.push(newZone);
        selectZone(zones.length - 1);
        resetMode();
      }
    } else {
      // Select mode: check if clicked inside any zone
      for (let i = zones.length - 1; i >= 0; i--) {
        if (isPointInside(coords, zones[i].points)) {
          selectZone(i);
          return;
        }
      }
    }
  });

  window.addEventListener('mouseup', () => {
    isDraggingVertex = false;
    draggedVertexInfo = null;
  });

  canvas.addEventListener('dblclick', () => {
    if (drawMode === 'polygon' && currentDrawingPoints.length >= 3) {
      finishNewPolygon();
    }
  });

  function finishNewPolygon() {
    const newZone = {
      id: `zone_${Date.now()}`,
      name: `Zone ${zones.length + 1}`,
      type: 'POWER_ZONE',
      points: currentDrawingPoints,
      color: '#ff3366',
      severity: 'CRITICAL',
      min_duration_sec: 1.5,
      alert_action: 'immediate'
    };
    zones.push(newZone);
    selectZone(zones.length - 1);
    resetMode();
  }

  function isPointInside(pt, poly) {
    if (!poly || poly.length < 3) return false;
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1];
      const xj = poly[j][0], yj = poly[j][1];
      const intersect = ((yi > pt.y) !== (yj > pt.y)) && (pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function selectZone(idx) {
    selectedZoneIndex = idx;
    const z = zones[idx];
    if (z) {
      zoneNameInput.value = z.name || '';
      zoneTypeSelect.value = z.type || 'DANGER_ZONE';
      zoneSeveritySelect.value = z.severity || 'WARNING';
      zoneColorInput.value = z.color || '#ff3366';
      zoneDurationInput.value = z.min_duration_sec || 1.5;
      zoneAlertAction.value = z.alert_action || 'immediate';
    }
    updateZonesList();
    drawCanvas();
  }

  // Update Inspector Fields on user input
  function syncInspectorToZone() {
    if (selectedZoneIndex >= 0 && selectedZoneIndex < zones.length) {
      const z = zones[selectedZoneIndex];
      z.name = zoneNameInput.value.trim() || 'Untitled Zone';
      z.type = zoneTypeSelect.value;
      z.severity = zoneSeveritySelect.value;
      z.color = zoneColorInput.value;
      z.min_duration_sec = parseFloat(zoneDurationInput.value) || 1.5;
      z.alert_action = zoneAlertAction.value;
      updateZonesList();
      drawCanvas();
    }
  }

  zoneNameInput.addEventListener('input', syncInspectorToZone);
  zoneTypeSelect.addEventListener('change', syncInspectorToZone);
  zoneSeveritySelect.addEventListener('change', syncInspectorToZone);
  zoneColorInput.addEventListener('input', syncInspectorToZone);
  zoneDurationInput.addEventListener('input', syncInspectorToZone);
  zoneAlertAction.addEventListener('change', syncInspectorToZone);

  // Delete Zone
  deleteZoneBtn.addEventListener('click', () => {
    if (selectedZoneIndex >= 0 && selectedZoneIndex < zones.length) {
      zones.splice(selectedZoneIndex, 1);
      selectedZoneIndex = zones.length > 0 ? 0 : -1;
      if (selectedZoneIndex >= 0) selectZone(selectedZoneIndex);
      updateZonesList();
      drawCanvas();
    }
  });

  // Save All Zones
  saveAllZonesBtn.addEventListener('click', async () => {
    saveAllZonesBtn.disabled = true;
    saveAllZonesBtn.textContent = 'Saving...';
    try {
      const res = await fetch('/api/zones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zones })
      });
      const data = await res.json();
      if (data.success) {
        alert(`Successfully saved ${zones.length} zones to camera!`);
      }
    } catch (err) {
      alert(`Save error: ${err.message}`);
    } finally {
      saveAllZonesBtn.disabled = false;
      saveAllZonesBtn.textContent = 'Save All Zones';
    }
  });

  function updateZonesList() {
    zonesCountBadge.textContent = zones.length;
    zonesChipList.innerHTML = '';
    zones.forEach((z, idx) => {
      const isSel = idx === selectedZoneIndex;
      const chip = document.createElement('div');
      chip.style.cssText = `
        display: flex; align-items: center; justify-content: space-between;
        padding: 8px 12px; border-radius: var(--radius-sm); cursor: pointer;
        background: ${isSel ? 'rgba(0, 240, 255, 0.12)' : 'rgba(0,0,0,0.25)'};
        border: 1px solid ${isSel ? 'var(--accent-cyan)' : 'var(--border-glass)'};
      `;
      chip.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="width:10px; height:10px; border-radius:50%; background:${z.color};"></span>
          <span style="font-weight:600; font-size:12px;">${z.name}</span>
        </div>
        <span class="badge badge-subtle" style="font-size:10px;">${z.type}</span>
      `;
      chip.onclick = () => selectZone(idx);
      zonesChipList.appendChild(chip);
    });
  }
});
