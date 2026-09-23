const $ = (id) => document.getElementById(id);
let programmes = [];
let entities = [];
async function api(path, options = {}) { const res = await fetch(path, options); if (!res.ok) throw new Error((await res.json()).message || res.statusText); return res.json(); }
async function loadProgrammes() {
  programmes = (await api('/v1/programmes')).items;
  $('programme-select').innerHTML = programmes.map(p => `<option value="${p.slug}">${p.name}</option>`).join('');
  $('programme-select').value = location.hash.slice(1) || programmes[0].slug;
  await loadProgramme($('programme-select').value);
}
async function loadProgramme(slug) {
  const programme = programmes.find(p => p.slug === slug) || await api(`/v1/programmes/${slug}`);
  document.documentElement.style.setProperty('--primary', programme.theme.primary);
  document.documentElement.style.setProperty('--accent', programme.theme.accent);
  $('programme-name').textContent = programme.name;
  $('programme-description').textContent = programme.description;
  $('rules').innerHTML = `<dt>Activation QSOs</dt><dd>${programme.rules.minimumQsos.activation}</dd><dt>Hunter QSOs</dt><dd>${programme.rules.minimumQsos.hunter}</dd><dt>Public access</dt><dd>${programme.rules.publicAccessRequired ? 'Required' : 'Programme-defined'}</dd>`;
  entities = (await api(`/v1/geodata/entities?programme=${encodeURIComponent(slug)}`)).items;
  $('entity-count').textContent = entities.length;
  $('loading').textContent = `${entities.length} loaded`;
  renderEntities(); renderMarkers();
}
function renderEntities() { $('entities').innerHTML = entities.map(e => `<tr><td><strong>${e.name}</strong><div class="small">${e.id.slice(0, 8)}…</div></td><td>${e.entityType}</td><td><span class="badge ${e.status.toLowerCase()}">${e.status}</span></td><td>${e.provenance?.adapter || '—'}</td><td>${e.status === 'CANDIDATE' ? `<button data-id="${e.id}" class="propose">Propose</button>` : '<span class="small">Reference active</span>'}</td></tr>`).join(''); document.querySelectorAll('.propose').forEach(b => b.onclick = async () => { await api(`/v1/geodata/entities/${b.dataset.id}/propose`, {method:'POST', headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()}, body:JSON.stringify({proposerId:'00000000-0000-4000-8000-000000000001'})}); await loadProgramme($('programme-select').value); }); }
function renderMarkers() { $('markers').innerHTML = entities.map((e, i) => { const c = e.centroid || {lat:40.41 + i * .006, lon:-3.72 + i * .01}; const left = `${35 + ((c.lon + 3.72) * 1200) % 55}%`; const top = `${30 + ((c.lat - 40.40) * 900) % 45}%`; return `<div class="marker ${e.status.toLowerCase()}" title="${e.name} · ${e.status}" style="left:${left};top:${top}"></div>`; }).join(''); }
$('programme-select').onchange = async (e) => { location.hash = e.target.value; await loadProgramme(e.target.value); };
$('refresh').onclick = () => loadProgramme($('programme-select').value);
loadProgrammes().catch(e => { $('loading').textContent = e.message; });

