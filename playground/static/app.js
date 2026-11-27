'use strict';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const formatNumber = value => new Intl.NumberFormat().format(value);
const state = {kind:'researchers', offset:0, request:null, results:null, profileToken:0, profileStack:[]};

async function api(path, options = {}) {
  if (window.researchData) return window.researchData.request(path, options);
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Something went wrong. Please try again.');
  return body;
}

function searchParameters() {
  const params = new URLSearchParams();
  const values = {kind:state.kind, q:$('#search-input').value.trim(), area:$('#area-filter').value,
    role:state.kind === 'researchers' ? $('#role-filter').value : '', scope:$('#scope-filter').value, offset:state.offset};
  Object.entries(values).forEach(([key,value]) => { if (value && !(key === 'scope' && value === 'all') && !(key === 'kind' && value === 'researchers')) params.set(key, value); });
  return params;
}

function readLocation() {
  const params = new URLSearchParams(location.search);
  state.kind = params.get('kind') === 'projects' ? 'projects' : 'researchers';
  state.offset = Math.max(0, parseInt(params.get('offset'), 10) || 0);
  $('#search-input').value = params.get('q') || '';
  $('#area-filter').value = ['1','2','3','4'].includes(params.get('area')) ? params.get('area') : '';
  $('#role-filter').value = ['PI','Post-doc','PhD'].includes(params.get('role')) ? params.get('role') : '';
  $('#scope-filter').value = ['research','expertise','needs','outcomes'].includes(params.get('scope')) ? params.get('scope') : 'all';
}

function updateControls() {
  $('#role-label').hidden = state.kind === 'projects';
  $$('[data-kind]').forEach(button => { button.setAttribute('aria-selected', String(button.dataset.kind === state.kind)); button.tabIndex = button.dataset.kind === state.kind ? 0 : -1; });
  $('#results-panel').setAttribute('aria-labelledby', state.kind === 'researchers' ? 'people-tab' : 'projects-tab');
  $('#clear-filters').hidden = !($('#area-filter').value || ($('#role-filter').value && state.kind === 'researchers') || $('#scope-filter').value !== 'all');
}

function highlight(text, terms) {
  const escaped = terms.filter(Boolean).sort((a,b) => b.length-a.length).map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!escaped.length) return esc(text);
  const regex = new RegExp(escaped.join('|'), 'gi');
  let result = '', last = 0;
  for (const match of text.matchAll(regex)) {
    result += esc(text.slice(last, match.index)) + '<mark>' + esc(match[0]) + '</mark>';
    last = match.index + match[0].length;
  }
  return result + esc(text.slice(last));
}

function excerpt(text, terms) {
  const positions = terms.map(term => text.toLowerCase().indexOf(term.toLowerCase())).filter(position => position >= 0);
  const first = positions.length ? Math.min(...positions) : 0;
  let start = Math.max(0, first - 70);
  if (start > 0) { const space = text.indexOf(' ', start); if (space >= 0 && space < first) start = space + 1; }
  let end = Math.min(text.length, start + 265);
  if (end < text.length) { const space = text.lastIndexOf(' ', end); if (space > start + 180) end = space; }
  return (start ? '…' : '') + highlight(text.slice(start, end), terms) + (end < text.length ? '…' : '');
}

function renderResults(result) {
  const people = state.kind === 'researchers';
  $('#results').innerHTML = result.rows.map(item => {
    const id = people ? item.researcher_id : item.project_id;
    const title = people ? item.full_name : item.title;
    const meta = people ? item.research_area : item.research_area + ' · ' + item.stage;
    const text = item.match ? item.match.text : item.summary;
    const labels = {name:people ? 'Name' : 'Project title',research:'Research description',expertise:people ? 'Expertise offered' : 'Expertise needed',needs:'Support need',outcomes:'Desired outcome',project:'Project description',project_needs:'Project support need',project_outcomes:'Project outcome'};
    let source = '';
    if (item.match) {
      const field = item.match.field;
      const projectLink = people && ['project','project_needs','project_outcomes','needs','outcomes'].includes(field);
      source = `<p class="result-source">Matched in ${esc(labels[field] || field)}${projectLink ? `<span>·</span><button data-project="${item.match.source_id}">View related project</button>` : ''}</p>`;
    }
    return `<article class="result-row"><div><h2><button class="record-name" data-${people ? 'person' : 'project'}="${id}">${esc(title)}</button></h2><p class="result-meta">${esc(meta)}</p><p class="result-excerpt">${excerpt(text, result.terms)}</p>${source}</div><div class="row-side">${people ? `<span class="role">${esc(item.role)}</span><span>${item.project_count} ${item.project_count === 1 ? 'project' : 'projects'}</span>` : `<span>${item.researcher_count} ${item.researcher_count === 1 ? 'person' : 'people'}</span>`}<button data-${people ? 'person' : 'project'}="${id}">View ${people ? 'profile' : 'project'} ↗</button></div></article>`;
  }).join('');
  $('#empty-results').hidden = result.total !== 0;
  const noun = people ? (result.total === 1 ? 'person' : 'people') : (result.total === 1 ? 'project' : 'projects');
  $('#result-count').textContent = `${formatNumber(result.total)} ${noun}${result.query ? ' found' : ''}`;
  $('.pagination').hidden = result.total <= result.page_size;
  $('#previous-page').disabled = result.offset === 0;
  $('#next-page').disabled = result.offset + result.page_size >= result.total;
  $('#page-info').textContent = result.total ? `${result.offset + 1}–${Math.min(result.offset + result.page_size, result.total)} of ${formatNumber(result.total)}` : '';
}

async function search(push = true) {
  state.request?.abort();
  const controller = new AbortController();
  state.request = controller;
  updateControls();
  const params = searchParameters();
  if (push) {
    const next = location.pathname + (params.size ? '?' + params : '');
    if (next !== location.pathname + location.search) history.pushState(null, '', next);
  }
  $('#search-error').hidden = true;
  $('#results-panel').setAttribute('aria-busy', 'true');
  $('#result-count').textContent = 'Searching…';
  $('#search-submit').textContent = 'Searching…';
  $('#results').innerHTML = '';
  $('#empty-results').hidden = true;
  $('.pagination').hidden = true;
  try {
    const result = await api(`/api/${state.kind}?${params}`, {signal:controller.signal});
    if (state.request !== controller) return;
    state.results = result;
    state.offset = result.offset;
    renderResults(result);
  } catch (error) {
    if (controller.signal.aborted) return;
    state.results = null;
    $('#search-error').textContent = error.message;
    $('#search-error').hidden = false;
    $('#result-count').textContent = 'Search not completed';
  } finally {
    if (state.request === controller) { $('#search-submit').textContent = 'Search'; $('#results-panel').setAttribute('aria-busy', 'false'); }
  }
}

function resetFilters() { $('#area-filter').value = ''; $('#role-filter').value = ''; $('#scope-filter').value = 'all'; }

async function openProfile(kind, id, addToHistory = true) {
  const token = ++state.profileToken;
  if (addToHistory) state.profileStack.push({kind,id});
  $('#profile-back').hidden = state.profileStack.length < 2;
  $('#profile-content').innerHTML = '<h2 id="profile-title" class="loading-text">Loading profile…</h2>';
  if (!$('#profile-dialog').open) $('#profile-dialog').showModal();
  $('#profile-dialog').scrollTop = 0;
  try {
    const item = await api(`/api/${kind}/${id}`);
    if (token !== state.profileToken) return;
    const person = kind === 'researchers';
    const header = `<div class="profile-heading"><span class="record-code">${esc(person ? item.researcher_code : item.project_code)} · Fictional record</span><h2 id="profile-title">${esc(person ? item.full_name : item.title)}</h2><p class="meta">${esc(person ? item.role : item.stage)} · ${esc(person ? item.primary_area : item.research_area)}</p><p class="profile-summary">${esc(item.summary)}</p></div>`;
    const offers = person ? `<section class="profile-section"><h3>Expertise</h3><ul class="expertise-list">${item.capabilities.map(cap => `<li title="${esc(cap.offer_description)}">${esc(cap.name)}</li>`).join('')}</ul></section>` : '';
    const connected = person ? `<section class="profile-section"><h3>Projects (${item.projects.length})</h3>${item.projects.map(project => `<div class="profile-item"><button class="profile-link" data-project="${project.project_id}">${esc(project.title)}</button><p>${esc(project.contribution)}</p></div>`).join('')}</section>` : `<section class="profile-section"><h3>People (${item.researchers.length})</h3>${item.researchers.map(researcher => `<div class="profile-item"><button class="profile-link" data-person="${researcher.researcher_id}">${esc(researcher.full_name)}</button><div class="item-meta">${esc(researcher.role)}</div><p>${esc(researcher.contribution)}</p></div>`).join('')}</section>`;
    const needs = `<section class="profile-section"><h3>Support needs</h3>${item.needs.map(need => `<div class="profile-item"><div class="item-meta">${esc(need.category)} · ${esc(need.priority)} priority</div><p>${esc(need.description)}</p></div>`).join('')}</section>`;
    const outcomes = `<section class="profile-section"><h3>Desired outcomes</h3>${item.outcomes.map(outcome => `<div class="profile-item"><div class="item-meta">${esc(outcome.category || 'Project target')} · ${outcome.horizon_months} months</div><p>${esc(outcome.description)}</p></div>`).join('')}</section>`;
    const matching = person ? '<section class="profile-section"><h3>People who may be able to help</h3><p class="match-intro">Matches expertise needs with skills offered by people outside this person’s current project teams. Availability is not assessed.</p><button id="find-matches" class="outline-button">Find people with matching expertise</button><div id="profile-matches" aria-live="polite"></div></section>' : '';
    $('#profile-content').innerHTML = header + offers + connected + needs + outcomes + matching;
    if (person) $('#find-matches').addEventListener('click', async event => {
      const button = event.target;
      button.disabled = true; button.textContent = 'Finding matches…';
      try {
        const response = await api(`/api/researchers/${id}/collaborators`);
        if (token !== state.profileToken) return;
        $('#profile-matches').innerHTML = response.rows.length ? response.rows.map(match => `<div class="profile-item"><button class="profile-link" data-person="${match.provider_id}">${esc(match.provider_name)}</button><p>${esc(match.matching_capability)}</p><div class="item-meta">${esc(match.provider_role)}${match.cross_area ? ' · Different research area' : ''}</div></div>`).join('') : '<p class="match-intro">No matching expertise offers were found.</p>';
        button.hidden = true;
      } catch (error) { if (token === state.profileToken) { $('#profile-matches').textContent = error.message; button.disabled = false; button.textContent = 'Try again'; } }
    });
  } catch (error) { if (token === state.profileToken) $('#profile-content').innerHTML = `<h2 id="profile-title">Could not open this record</h2><p class="error-message">${esc(error.message)}</p>`; }
}

function bindEvents() {
  document.addEventListener('research-person-open', event => openProfile('researchers', event.detail.researcherId));
  $('#search-form').addEventListener('submit', event => { event.preventDefault(); state.offset = 0; search(); });
  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.person) openProfile('researchers', Number(button.dataset.person));
    if (button.dataset.project) openProfile('projects', Number(button.dataset.project));
    if (button.dataset.kind) { state.kind = button.dataset.kind; state.offset = 0; search(); }
    if (button.dataset.example) { $('#search-input').value = button.dataset.example; state.offset = 0; search(); }
  });
  $$('[role=tab]').forEach(tab => tab.addEventListener('keydown', event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); const next = tab.id === 'people-tab' ? $('#projects-tab') : $('#people-tab'); next.focus(); next.click(); } }));
  ['area-filter','role-filter','scope-filter'].forEach(id => $('#' + id).addEventListener('change', () => { state.offset = 0; search(); }));
  $('#clear-filters').addEventListener('click', () => { resetFilters(); state.offset = 0; search(); });
  $('#clear-search').addEventListener('click', () => { resetFilters(); $('#search-input').value = ''; state.offset = 0; search(); });
  $('#previous-page').addEventListener('click', () => { state.offset = Math.max(0,state.offset - state.results.page_size); search(); $('.result-tabs').scrollIntoView({block:'start'}); });
  $('#next-page').addEventListener('click', () => { state.offset += state.results.page_size; search(); $('.result-tabs').scrollIntoView({block:'start'}); });
  window.addEventListener('popstate', () => { readLocation(); search(false); });
  $('#about-button').addEventListener('click', () => $('#about-dialog').showModal());
  $('#close-about').addEventListener('click', () => $('#about-dialog').close());
  $('#close-profile').addEventListener('click', () => $('#profile-dialog').close());
  $('#profile-dialog').addEventListener('close', () => { state.profileToken++; state.profileStack = []; });
  $('#profile-back').addEventListener('click', () => { state.profileStack.pop(); const previous = state.profileStack[state.profileStack.length - 1]; if (previous) openProfile(previous.kind, previous.id, false); });
}

async function init() {
  bindEvents();
  try {
    const overview = await api('/api/overview');
    $('#dataset-size').textContent = `${formatNumber(overview.counts.researchers)} people · ${formatNumber(overview.counts.projects)} projects · Four research areas`;
    $('#area-filter').innerHTML = '<option value="">All areas</option>' + overview.areas.map(area => `<option value="${area.area_id}">${esc(area.name)}</option>`).join('');
    readLocation();
    await search(false);
  } catch (error) {
    $('#search-error').textContent = window.researchData
      ? 'The directory could not load. Check your connection and refresh the page.'
      : 'The directory is unavailable. Check that the local server is running, then reload.';
    $('#search-error').hidden = false;
    $('#result-count').textContent = 'Connection unavailable';
    $('#results-panel').setAttribute('aria-busy', 'false');
  }
}

init();
