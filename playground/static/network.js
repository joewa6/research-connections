(() => {
  'use strict';

  const canvas = document.querySelector('#network-canvas');
  const context = canvas.getContext('2d');
  const personSelect = document.querySelector('#network-person');
  const openButton = document.querySelector('#network-open-person');
  const selectionText = document.querySelector('#network-selection');
  const loadingText = document.querySelector('#network-loading');
  const colors = {1: '#b78738', 2: '#ac7062', 3: '#8272a0', 4: '#528b98'};
  const defaultCaption = 'Each dot is a person. Larger dots have more collaborators.';
  let graph, nodesById, neighbors, centers;
  let width = 0, height = 0, worldWidth = 1000, worldHeight = 560, fit = 1;
  let zoom = 1, panX = 0, panY = 0, selected = null, hovered = null, activeArea = null;
  let drag = null, frame = null;

  function scheduleDraw() {
    if (frame !== null) return;
    frame = requestAnimationFrame(() => { frame = null; draw(); });
  }

  function positionNodes() {
    const compact = width < 600;
    worldWidth = compact ? 600 : 1000;
    worldHeight = compact ? 650 : 560;
    centers = compact ? [[165, 180], [435, 180], [165, 465], [435, 465]]
      : [[270, 160], [730, 160], [270, 410], [730, 410]];
    graph.areas.forEach((area, index) => {
      const members = graph.nodes.filter(node => node.area_id === area.area_id)
        .sort((a, b) => b.degree - a.degree || a.id - b.id);
      members.forEach((node, rank) => {
        const angle = rank * 2.39996323 + index * 0.7;
        const radius = Math.sqrt((rank + 0.5) / members.length);
        const uneven = 1 + 0.07 * Math.sin(angle * 3 + index);
        node.x = centers[index][0] + Math.cos(angle) * radius * (compact ? 133 : 208) * uneven;
        node.y = centers[index][1] + Math.sin(angle) * radius * (compact ? 119 : 105) * uneven;
      });
    });
    fit = Math.min(width / worldWidth, height / worldHeight);
  }

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    width = bounds.width;
    height = bounds.height;
    const resolution = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * resolution);
    canvas.height = Math.round(height * resolution);
    context.setTransform(resolution, 0, 0, resolution, 0, 0);
    positionNodes();
    scheduleDraw();
  }

  function screenPoint(node) {
    return {x: width / 2 + panX + (node.x - worldWidth / 2) * fit * zoom,
      y: height / 2 + panY + (node.y - worldHeight / 2) * fit * zoom};
  }

  function nodeRadius(node) {
    return Math.max(1.5, (1.6 + Math.sqrt(node.degree) * 0.42) * fit * Math.sqrt(zoom));
  }

  function draw() {
    if (!graph) return;
    context.clearRect(0, 0, width, height);
    const focus = hovered || selected;
    const connected = focus ? neighbors.get(focus.id) : null;
    const points = new Map(graph.nodes.map(node => [node.id, screenPoint(node)]));
    for (const edge of graph.links) {
      const source = nodesById.get(edge.source), target = nodesById.get(edge.target);
      const focused = focus && (edge.source === focus.id || edge.target === focus.id);
      const inArea = !activeArea || source.area_id === activeArea || target.area_id === activeArea;
      context.globalAlpha = focus ? (focused ? 0.75 : 0.025) : (inArea ? 0.13 : 0.025);
      context.strokeStyle = focused ? colors[focus.area_id] : '#698174';
      context.lineWidth = focused ? 1.25 : 0.65;
      const a = points.get(edge.source), b = points.get(edge.target);
      context.beginPath();
      context.moveTo(a.x, a.y);
      context.lineTo(b.x, b.y);
      context.stroke();
    }
    for (const node of graph.nodes) {
      const point = points.get(node.id);
      const emphasized = focus ? node.id === focus.id || connected.has(node.id) : !activeArea || node.area_id === activeArea;
      context.globalAlpha = emphasized ? 0.9 : 0.15;
      context.fillStyle = colors[node.area_id];
      context.beginPath();
      context.arc(point.x, point.y, nodeRadius(node), 0, Math.PI * 2);
      context.fill();
      if (focus && node.id === focus.id) {
        context.globalAlpha = 1;
        context.strokeStyle = colors[node.area_id];
        context.lineWidth = 1.3;
        context.beginPath();
        context.arc(point.x, point.y, nodeRadius(node) + 4, 0, Math.PI * 2);
        context.stroke();
      }
    }
    context.globalAlpha = 1;
    if (focus) {
      const point = points.get(focus.id);
      context.font = '12px -apple-system, BlinkMacSystemFont, sans-serif';
      const labelWidth = context.measureText(focus.name).width + 18;
      const x = Math.max(5, Math.min(width - labelWidth - 5, point.x - labelWidth / 2));
      const y = Math.max(5, Math.min(height - 33, point.y - 37));
      context.fillStyle = '#ffffff';
      context.strokeStyle = '#dfe5dc';
      context.lineWidth = 1;
      context.fillRect(x, y, labelWidth, 27);
      context.strokeRect(x, y, labelWidth, 27);
      context.fillStyle = '#334238';
      context.textAlign = 'left';
      context.fillText(focus.name, x + 9, y + 18);
    } else if (zoom <= 1.3) {
      context.font = width < 600 ? '10px -apple-system, sans-serif' : '11px -apple-system, sans-serif';
      context.textAlign = 'center';
      graph.areas.forEach((area, index) => {
        const point = screenPoint({x: centers[index][0], y: centers[index][1] - (width < 600 ? 139 : 123)});
        context.fillStyle = colors[area.area_id];
        context.globalAlpha = !activeArea || activeArea === area.area_id ? 1 : 0.3;
        context.fillText(area.name, point.x, point.y);
      });
    }
    context.globalAlpha = 1;
  }

  function hitTest(x, y) {
    let nearest = null, distance = 8;
    for (const node of graph.nodes) {
      const point = screenPoint(node);
      const delta = Math.hypot(point.x - x, point.y - y);
      if (delta < distance) { nearest = node; distance = delta; }
    }
    return nearest;
  }

  function pointerPosition(event) {
    const bounds = canvas.getBoundingClientRect();
    return {x: event.clientX - bounds.left, y: event.clientY - bounds.top};
  }

  function updateCaption() {
    const node = hovered || selected;
    selectionText.textContent = node
      ? `${node.name} · ${node.role} · ${node.project_count} ${node.project_count === 1 ? 'project' : 'projects'} · ${node.degree} ${node.degree === 1 ? 'collaborator' : 'collaborators'}`
      : defaultCaption;
  }

  function selectPerson(node) {
    selected = node;
    personSelect.value = node ? String(node.id) : '';
    openButton.disabled = !node;
    updateCaption();
    scheduleDraw();
  }

  function openPerson(node) {
    if (node) document.dispatchEvent(new CustomEvent('research-person-open', {detail: {researcherId: node.id}}));
  }

  function clearHover() {
    hovered = null;
    canvas.classList.remove('over-node');
    updateCaption();
    scheduleDraw();
  }

  function resetView() {
    zoom = 1; panX = 0; panY = 0; activeArea = null; hovered = null;
    document.querySelectorAll('#network-legend button').forEach(button => button.setAttribute('aria-pressed', 'false'));
    selectPerson(null);
  }

  function bindControls() {
    document.querySelector('#network-zoom-in').addEventListener('click', () => { zoom = Math.min(4.5, zoom * 1.3); scheduleDraw(); });
    document.querySelector('#network-zoom-out').addEventListener('click', () => { zoom = Math.max(0.7, zoom / 1.3); scheduleDraw(); });
    document.querySelector('#network-reset').addEventListener('click', resetView);
    personSelect.addEventListener('change', () => {
      hovered = null;
      const node = nodesById.get(Number(personSelect.value));
      if (node) {
        panX = -(node.x - worldWidth / 2) * fit * zoom;
        panY = -(node.y - worldHeight / 2) * fit * zoom;
      }
      selectPerson(node || null);
    });
    openButton.addEventListener('click', () => openPerson(selected));
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const point = pointerPosition(event);
      drag = {id: event.pointerId, x: point.x, y: point.y, panX, panY, moved: false};
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event => {
      const point = pointerPosition(event);
      if (drag && drag.id === event.pointerId) {
        if (Math.hypot(point.x - drag.x, point.y - drag.y) > 4) drag.moved = true;
        if (drag.moved) {
          panX = drag.panX + point.x - drag.x;
          panY = drag.panY + point.y - drag.y;
          hovered = null;
          canvas.classList.add('is-dragging');
          canvas.classList.remove('over-node');
          updateCaption();
          scheduleDraw();
        }
        return;
      }
      const node = hitTest(point.x, point.y);
      if (node !== hovered) {
        hovered = node;
        canvas.classList.toggle('over-node', Boolean(node));
        updateCaption();
        scheduleDraw();
      }
    });
    canvas.addEventListener('pointerup', event => {
      if (!drag || drag.id !== event.pointerId) return;
      const point = pointerPosition(event);
      if (!drag.moved) {
        const node = hitTest(point.x, point.y);
        selectPerson(node);
        openPerson(node);
      }
      drag = null;
      canvas.classList.remove('is-dragging');
      canvas.releasePointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointercancel', () => { drag = null; canvas.classList.remove('is-dragging'); clearHover(); });
    canvas.addEventListener('pointerleave', () => { if (!drag) clearHover(); });
  }

  async function initialize() {
    try {
      const response = await fetch('/api/network');
      if (!response.ok) throw new Error('Network unavailable');
      graph = await response.json();
      nodesById = new Map(graph.nodes.map(node => [node.id, node]));
      neighbors = new Map(graph.nodes.map(node => [node.id, new Set()]));
      graph.links.forEach(edge => {
        neighbors.get(edge.source).add(edge.target);
        neighbors.get(edge.target).add(edge.source);
      });
      document.querySelector('#network-count').textContent = `${graph.nodes.length.toLocaleString()} researchers · ${graph.links.length.toLocaleString()} shared-project connections`;
      const options = document.createDocumentFragment();
      [...graph.nodes].sort((a, b) => a.name.localeCompare(b.name) || a.id - b.id).forEach(node => {
        const option = document.createElement('option');
        option.value = node.id;
        option.textContent = `${node.name} · ${node.role} · #${node.id}`;
        options.append(option);
      });
      personSelect.append(options);
      graph.areas.forEach(area => {
        const button = document.createElement('button');
        button.setAttribute('aria-pressed', 'false');
        const dot = document.createElement('i');
        dot.className = `network-color-${area.area_id}`;
        dot.setAttribute('aria-hidden', 'true');
        button.append(dot, document.createTextNode(area.name));
        button.addEventListener('click', () => {
          activeArea = activeArea === area.area_id ? null : area.area_id;
          hovered = null;
          selectPerson(null);
          document.querySelectorAll('#network-legend button').forEach(item => item.setAttribute('aria-pressed', String(item === button && activeArea !== null)));
        });
        document.querySelector('#network-legend').append(button);
      });
      bindControls();
      resize();
      new ResizeObserver(resize).observe(canvas);
      loadingText.hidden = true;
    } catch (error) {
      loadingText.textContent = 'The network could not load. You can still search the directory below.';
      document.querySelectorAll('.network-tools button').forEach(button => { button.disabled = true; });
      personSelect.disabled = true;
    }
  }

  initialize();
})();
