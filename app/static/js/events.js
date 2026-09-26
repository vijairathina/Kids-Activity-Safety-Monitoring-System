/**
 * Event History and Media Evidence Review Controller.
 */

document.addEventListener('DOMContentLoaded', () => {
  const tableBody = document.getElementById('events-table-body');
  const typeSelect = document.getElementById('filter-type-select');
  const sevSelect = document.getElementById('filter-severity-select');
  const refreshBtn = document.getElementById('refresh-events-btn');
  const purgeBtn = document.getElementById('purge-events-btn');
  const timeFilterBtns = document.querySelectorAll('[data-range]');

  const statTotal = document.getElementById('stat-total-events');
  const statToday = document.getElementById('stat-today-events');
  const statUnack = document.getElementById('stat-unack-critical');

  const mediaModal = document.getElementById('media-modal');
  const modalTitle = document.getElementById('modal-title');
  const modalBody = document.getElementById('modal-body');
  const modalDetailsText = document.getElementById('modal-details-text');
  const modalTimeText = document.getElementById('modal-time-text');
  const closeModalBtn = document.getElementById('close-modal-btn');

  let activeTimeRange = 'today';

  // Time filter button clicks
  timeFilterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      timeFilterBtns.forEach(b => b.classList.remove('btn-primary'));
      btn.classList.add('btn-primary');
      activeTimeRange = btn.getAttribute('data-range');
      fetchEvents();
    });
  });

  typeSelect.addEventListener('change', fetchEvents);
  sevSelect.addEventListener('change', fetchEvents);
  refreshBtn.addEventListener('click', fetchEvents);

  if (closeModalBtn) {
    closeModalBtn.addEventListener('click', () => {
      mediaModal.classList.remove('show');
      modalBody.innerHTML = '';
    });
  }

  // Purge Old Events
  if (purgeBtn) {
    purgeBtn.addEventListener('click', async () => {
      if (confirm('Purge events and media older than 7 days?')) {
        try {
          const res = await fetch('/api/events/purge', { method: 'POST' });
          const d = await res.json();
          alert(`Purged ${d.deleted_count || 0} old event records.`);
          fetchEvents();
        } catch (e) {
          alert(`Purge failed: ${e.message}`);
        }
      }
    });
  }

  // Fetch events from API
  async function fetchEvents() {
    tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-dim);padding:20px;">Fetching records...</td></tr>`;
    try {
      const url = `/api/events?type=${typeSelect.value}&severity=${sevSelect.value}&range=${activeTimeRange}&limit=100`;
      const res = await fetch(url);
      const data = await res.json();

      // Update metrics
      if (data.stats) {
        statTotal.textContent = data.stats.total_events || 0;
        statToday.textContent = data.stats.today_events || 0;
        statUnack.textContent = data.stats.unacknowledged_critical || 0;
      }

      const events = data.events || [];
      if (events.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-dim);padding:30px;">No events recorded matching the current filter.</td></tr>`;
        return;
      }

      tableBody.innerHTML = '';
      events.forEach(ev => {
        const tr = document.createElement('tr');
        const sevClass = (ev.severity || 'INFO').toLowerCase();
        const confPct = Math.round((ev.confidence || 0) * 100);
        const timeFormatted = new Date(ev.timestamp).toLocaleString();

        const snapFilename = ev.snapshot_path ? ev.snapshot_path.split(/[\/\\]/).pop() : '';
        const vidFilename = ev.video_clip_path ? ev.video_clip_path.split(/[\/\\]/).pop() : '';

        // Media Buttons
        let mediaHtml = '<span style="color:var(--text-dim);">-</span>';
        if (snapFilename || vidFilename) {
          mediaHtml = '<div style="display:flex;gap:6px;">';
          if (snapFilename) {
            mediaHtml += `<button class="btn btn-glass" style="font-size:11px;padding:3px 6px;" onclick="viewMedia('image', '/media/snapshots/${snapFilename}', '${ev.event_type}', '${ev.timestamp}')">📷 Photo</button>`;
          }
          if (vidFilename) {
            mediaHtml += `<button class="btn btn-glass" style="font-size:11px;padding:3px 6px;" onclick="viewMedia('video', '/media/recordings/${vidFilename}', '${ev.event_type}', '${ev.timestamp}')">🎬 Clip</button>`;
          }
          mediaHtml += '</div>';
        }

        // Status badge
        const ackBadge = ev.acknowledged
          ? `<span class="badge badge-subtle" style="color:var(--accent-green);">Resolved</span>`
          : `<span class="badge badge-critical">Unread</span>`;

        // Action buttons
        const actionHtml = `
          <div style="display:flex;gap:6px;">
            ${!ev.acknowledged ? `<button class="btn btn-glass" style="font-size:11px;padding:3px 8px;" onclick="acknowledgeEvent(${ev.id})">Acknowledge</button>` : ''}
            <button class="btn btn-glass" style="font-size:11px;padding:3px 6px;color:var(--accent-red);" onclick="deleteEventRecord(${ev.id})">✕</button>
          </div>
        `;

        tr.innerHTML = `
          <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${timeFormatted}</td>
          <td>
            <div style="font-weight:600;color:var(--text-main);">${ev.event_type.replace(/_/g, ' ')}</div>
            <div style="font-size:11px;color:var(--text-muted);">${ev.details?.description || ''}</div>
          </td>
          <td><span class="badge badge-${sevClass}">${ev.severity}</span></td>
          <td><span class="badge badge-subtle">${ev.confidence_level} (${confPct}%)</span></td>
          <td>
            <div style="font-size:12px;">${ev.person_id ? `Person #${ev.person_id}` : 'All'}</div>
            <div style="font-size:11px;color:var(--text-dim);">${ev.location_zone || 'Open Room'}</div>
          </td>
          <td>${mediaHtml}</td>
          <td>${ackBadge}</td>
          <td>${actionHtml}</td>
        `;
        tableBody.appendChild(tr);
      });

    } catch (err) {
      tableBody.innerHTML = `<tr><td colspan="8" style="color:var(--accent-red);padding:20px;text-align:center;">Failed to load events: ${err.message}</td></tr>`;
    }
  }

  fetchEvents();
});

// Media Modal Opener
window.viewMedia = (type, url, title, timestamp) => {
  const modal = document.getElementById('media-modal');
  const mTitle = document.getElementById('modal-title');
  const mBody = document.getElementById('modal-body');
  const mTime = document.getElementById('modal-time-text');

  mTitle.textContent = `${title.replace(/_/g, ' ')} Evidence`;
  mTime.textContent = new Date(timestamp).toLocaleString();

  if (type === 'image') {
    mBody.innerHTML = `<img src="${url}" style="max-width:100%;max-height:480px;border-radius:var(--radius-sm);border:1px solid var(--border-glass);" alt="Snapshot">`;
  } else {
    mBody.innerHTML = `
      <video controls autoplay style="max-width:100%;max-height:480px;border-radius:var(--radius-sm);border:1px solid var(--border-glass);">
        <source src="${url}" type="video/mp4">
        Your browser does not support video playback.
      </video>
    `;
  }
  modal.classList.add('show');
};

// Acknowledge Action
window.acknowledgeEvent = async (id) => {
  try {
    const res = await fetch(`/api/events/${id}/acknowledge`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      document.getElementById('refresh-events-btn').click();
    }
  } catch (e) {
    alert(`Failed to acknowledge: ${e.message}`);
  }
};

// Delete Action
window.deleteEventRecord = async (id) => {
  if (confirm('Delete this event and its media?')) {
    try {
      const res = await fetch(`/api/events/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        document.getElementById('refresh-events-btn').click();
      }
    } catch (e) {
      alert(`Delete failed: ${e.message}`);
    }
  }
};
