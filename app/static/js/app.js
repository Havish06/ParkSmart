async function refreshSlots() {
  const grid = document.getElementById('slot-grid');
  if (!grid) return;
  try {
    const response = await fetch('/api/slots', {headers: {'Accept': 'application/json'}});
    if (!response.ok) return;
    const data = await response.json();
    let available = 0;
    let occupied = 0;
    data.slots.forEach(slot => {
      if (slot.status === 'available') available += 1;
      if (slot.occupied) occupied += 1;
      const card = grid.querySelector(`[data-slot-id="${slot.id}"]`);
      if (!card) return;
      card.className = `slot-card ${slot.status}`;
      const title = card.querySelector('h3');
      const detail = card.querySelector('[data-slot-detail]') || card.querySelector('span:last-child');
      if (title) title.textContent = slot.status.toUpperCase();
      if (detail) detail.textContent = slot.vehicle || `Sensor ${slot.sensor_health}`;
    });
    const availableCount = document.querySelector('[data-count="available"]');
    const occupiedCount = document.querySelector('[data-count="occupied"]');
    if (availableCount) availableCount.textContent = available;
    if (occupiedCount) occupiedCount.textContent = occupied;
  } catch (error) { console.debug('Slot refresh failed', error); }
}

async function refreshFeeEstimate() {
  const input = document.getElementById('estimate-minutes');
  const amount = document.getElementById('estimate-amount');
  if (!input || !amount) return;
  try {
    const response = await fetch(`/api/fee-estimate?minutes=${encodeURIComponent(input.value)}`);
    const data = await response.json();
    amount.textContent = response.ok ? `${data.currency} ${Number(data.amount).toFixed(2)}` : '—';
  } catch (error) { amount.textContent = '—'; }
}

function setupFeeEstimator() {
  const input = document.getElementById('estimate-minutes');
  if (!input) return;
  input.addEventListener('input', refreshFeeEstimate);
  refreshFeeEstimate();
}

async function refreshReservationPlan() {
  const form = document.getElementById('reservation-form');
  const result = document.getElementById('planner-result');
  if (!form || !result) return;
  const fields = ['date', 'start', 'end', 'vehicle_number'].map(name => form.elements[name]);
  if (fields.some(field => !field || !field.value)) return;
  const query = new URLSearchParams(fields.map(field => [field.name, field.value]));
  try {
    const response = await fetch(`/api/reservation-plan?${query}`);
    const data = await response.json();
    if (!response.ok) { result.innerHTML = `<div class="alert alert-warning mb-0">${data.error}</div>`; return; }
    const available = data.slots.filter(slot => slot.available);
    result.innerHTML = `<div class="planner-box"><div class="d-flex justify-content-between gap-3"><div><strong>Explainable planner</strong><p class="small text-muted mb-2">${data.explanation}</p></div><span class="badge text-bg-primary">${available.length} possible</span></div><div class="small">${data.slots.map(slot => `<div class="d-flex justify-content-between border-top py-2"><span><strong>${slot.slot}</strong> ${slot.recommended ? '<span class="badge text-bg-success ms-1">Recommended</span>' : ''}</span><span class="text-muted">${slot.available ? `keeps ${slot.free_after_minutes}m after` : slot.reason}</span></div>`).join('')}</div><p class="small text-muted mb-0 mt-2">${data.notice}</p></div>`;
    const select = form.elements.slot_id;
    if (data.recommended_slot_id) select.value = data.recommended_slot_id;
  } catch (error) { result.innerHTML = '<div class="alert alert-warning mb-0">Planner is temporarily unavailable; you can still choose a slot.</div>'; }
}

function setupReservationPlanner() {
  const form = document.getElementById('reservation-form');
  if (!form) return;
  ['date', 'start', 'end', 'vehicle_number'].forEach(name => form.elements[name].addEventListener('change', refreshReservationPlan));
  form.elements.vehicle_number.addEventListener('input', refreshReservationPlan);
}

function setupNavigation() {
  const path = window.location.pathname;
  document.querySelectorAll('.app-nav .nav-link').forEach(link => {
    if (link.getAttribute('href') === path) link.classList.add('active');
  });
}

function setupFastForms() {
  document.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.dataset.submitting === 'true') {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      const button = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
      if (!button) return;
      // Preserve named submit-button values until the browser serializes the form.
      setTimeout(() => { button.disabled = true; }, 0);
      button.dataset.originalText = button.innerHTML;
      button.innerHTML = '<span class="button-spinner" aria-hidden="true"></span> Processing…';
    });
  });
}

window.addEventListener('pageshow', () => {
  document.querySelectorAll('form[data-submitting]').forEach(form => {
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('button[data-original-text]').forEach(button => {
      button.disabled = false;
      button.innerHTML = button.dataset.originalText;
      delete button.dataset.originalText;
    });
  });
});

function setupSimulator() {
  const controls = document.getElementById('simulator-controls');
  if (!controls) return;
  controls.addEventListener('click', async event => {
    const button = event.target.closest('.sensor-toggle');
    if (!button) return;
    const buttons = [...controls.querySelectorAll('.sensor-toggle')];
    const states = buttons.map(item => item.classList.contains('btn-danger'));
    const index = Number(button.dataset.index);
    states[index] = !states[index];
    try {
      const response = await fetch('/api/simulator/sensors', {method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: JSON.stringify({occupied: states})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Simulator update failed');
      buttons.forEach((item, i) => {
        const occupied = result.slots[i].occupied;
        item.classList.toggle('btn-danger', occupied);
        item.classList.toggle('btn-outline-success', !occupied);
        item.textContent = `${result.slots[i].slot} ${occupied ? 'occupied' : 'free'}`;
      });
      refreshSlots();
    } catch (error) { window.alert(error.message); }
  });
}

function drawBars(container, points, prefix = '') {
  if (!container) return;
  const max = Math.max(...points.map(point => point.value), 1);
  container.innerHTML = points.map(point => `<div class="bar-item" title="${point.label}: ${prefix}${point.value}"><span style="height:${Math.max(3, point.value / max * 100)}%"></span><small>${point.label.slice(-5)}</small></div>`).join('');
}

async function setupAnalytics() {
  if (!document.getElementById('analytics-panel')) return;
  try {
    const response = await fetch('/api/analytics', {headers: {'Accept': 'application/json'}});
    if (!response.ok) return;
    const data = await response.json();
    document.getElementById('analytics-reservations').textContent = data.today_reservations;
    document.getElementById('analytics-duration').textContent = `${data.average_duration} min`;
    document.getElementById('analytics-peak').textContent = data.peak_occupancy;
    document.getElementById('analytics-slot').textContent = data.most_used_slot;
    drawBars(document.getElementById('vehicles-chart'), data.vehicles_per_hour);
    drawBars(document.getElementById('revenue-chart'), data.daily_revenue, 'INR ');
  } catch (error) { console.debug('Analytics unavailable', error); }
}

setupSimulator();
setupAnalytics();
setupFeeEstimator();
setupReservationPlanner();
setupNavigation();
setupFastForms();
refreshSlots();
setInterval(refreshSlots, 3000);
