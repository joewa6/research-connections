/* Read-only browser equivalent of playground/server.py. Tested against its results. */
(function (root) {
  'use strict';
  const PAGE_SIZE = 15;
  const SCOPES = {all: null, research: ['research', 'project'], expertise: ['expertise'],
    needs: ['needs', 'project_needs'], outcomes: ['outcomes', 'project_outcomes']};
  const PERSON_DOCUMENTS = `
    SELECT researcher_id AS owner_id, 'name' AS field, researcher_id AS source_id,
           full_name AS text, 0 AS importance FROM researchers
    UNION ALL SELECT researcher_id, 'research', researcher_id, summary, 1 FROM researchers
    UNION ALL SELECT rc.researcher_id, 'expertise', rc.capability_id,
           c.name || '. ' || rc.offer_description, 2
      FROM researcher_capabilities rc JOIN capabilities c USING(capability_id)
    UNION ALL SELECT researcher_id, 'needs', related_project_id, description, 4 FROM researcher_needs
    UNION ALL SELECT researcher_id, 'outcomes', related_project_id, description, 5 FROM researcher_outcomes
    UNION ALL SELECT rp.researcher_id, 'project', p.project_id, p.title || '. ' || p.summary, 3
      FROM researcher_projects rp JOIN projects p USING(project_id)
    UNION ALL SELECT rp.researcher_id, 'project_needs', n.project_id, n.description, 6
      FROM researcher_projects rp JOIN project_needs n USING(project_id)
    UNION ALL SELECT rp.researcher_id, 'project_outcomes', o.project_id, o.description, 7
      FROM researcher_projects rp JOIN project_outcomes o USING(project_id)`;
  const PROJECT_DOCUMENTS = `
    SELECT project_id AS owner_id, 'name' AS field, project_id AS source_id,
           title AS text, 0 AS importance FROM projects
    UNION ALL SELECT project_id, 'research', project_id, summary, 1 FROM projects
    UNION ALL SELECT n.project_id, 'expertise', n.project_id, c.name || '. ' || n.description, 2
      FROM project_needs n JOIN capabilities c USING(capability_id)
    UNION ALL SELECT project_id, 'needs', project_id, description, 3 FROM project_needs
    UNION ALL SELECT project_id, 'outcomes', project_id, description, 4 FROM project_outcomes`;

  function parseSearch(query) {
    query = query.trim().replace(/[“”]/g, '"');
    if ([...query].length > 200) throw new Error('Keep your search under 200 characters.');
    if (!query) return [];
    if ((query.match(/"/g) || []).length % 2) throw new Error('Add a closing quote to finish the phrase.');
    const groups = [];
    let group = [], expectTerm = true;
    for (const token of query.matchAll(/"([^"]*)"|([^\s"]+)/g)) {
      const phrase = token[1] || '', word = token[2] || '', operator = word.toUpperCase();
      if (operator === 'OR' || operator === 'AND') {
        if (expectTerm) throw new Error(`Add a word or phrase before ${operator}.`);
        if (operator === 'OR') { groups.push(group); group = []; }
        expectTerm = true;
      } else {
        const term = (phrase || word).trim().replace(/\s+/g, ' ');
        if (!term) throw new Error('Add some text inside the quotes.');
        group.push(term);
        expectTerm = false;
      }
    }
    if (expectTerm) throw new Error('Add a word or phrase after OR or AND.');
    groups.push(group);
    if (groups.flat().length > 12) throw new Error('Use at most 12 search words or phrases.');
    return groups;
  }

  function pattern(term) { return '%' + term.replace(/[\\%_]/g, character => '\\' + character) + '%'; }
  function placeholders(items) { return items.map(() => '?').join(','); }

  class ResearchDatabase {
    constructor(database) { this.database = database; }
    rows(sql, values = []) {
      const statement = this.database.prepare(sql);
      try {
        statement.bind(values);
        const result = [];
        while (statement.step()) result.push(statement.getAsObject());
        return result;
      } finally { statement.free(); }
    }
    overview() {
      const counts = {};
      for (const table of ['researchers', 'projects', 'researcher_projects']) {
        counts[table] = this.rows(`SELECT count(*) AS total FROM ${table}`)[0].total;
      }
      return {counts, areas: this.rows('SELECT * FROM research_areas ORDER BY area_id'), roles: ['PI', 'Post-doc', 'PhD']};
    }
    search(kind, parameters) {
      if (!['researchers', 'projects'].includes(kind)) throw new Error('Choose people or projects.');
      const query = (parameters.get('q') || '').trim(), groups = parseSearch(query);
      const scope = parameters.get('scope') || 'all', area = parameters.get('area') || '', role = parameters.get('role') || '';
      if (!Object.hasOwn(SCOPES, scope)) throw new Error('Choose a valid search field.');
      if (area && !['1', '2', '3', '4'].includes(area)) throw new Error('Choose a valid research area.');
      if (role && !['PI', 'Post-doc', 'PhD'].includes(role)) throw new Error('Choose a valid researcher role.');
      const rawOffset = parameters.get('offset') || '0';
      if (!/^[+-]?\d+$/.test(rawOffset)) throw new Error('Choose a valid results page.');
      let offset = Math.max(0, Math.min(Number(rawOffset), 100000));
      const people = kind === 'researchers';
      const table = people ? 'researchers r JOIN research_areas a ON a.area_id=r.primary_area_id'
        : 'projects p JOIN topics t USING(topic_id) JOIN research_areas a USING(area_id)';
      const identifier = people ? 'r.researcher_id' : 'p.project_id';
      const columns = people ? `r.researcher_id, r.researcher_code, r.full_name, r.role, r.summary, a.name AS research_area,
        (SELECT count(*) FROM researcher_projects rp WHERE rp.researcher_id=r.researcher_id) AS project_count`
        : `p.project_id, p.project_code, p.title, p.summary, p.stage, t.name AS topic, a.name AS research_area,
        (SELECT count(*) FROM researcher_projects rp WHERE rp.project_id=p.project_id) AS researcher_count`;
      const predicates = [], filters = [], terms = [...new Set(groups.flat())];
      if (area) { predicates.push('a.area_id=?'); filters.push(Number(area)); }
      if (people && role) { predicates.push('r.role=?'); filters.push(role); }
      const where = predicates.length ? ' WHERE ' + predicates.join(' AND ') : '';
      let cte = '', values = [], matchJoin = '';
      let order = people ? 'r.full_name, r.researcher_id' : 'p.title, p.project_id';
      const documents = people ? PERSON_DOCUMENTS : PROJECT_DOCUMENTS;
      const scopeValues = [...(SCOPES[scope] || [])];
      if (!people && scope === 'research') scopeValues.push('name');
      const patterns = terms.map(pattern), like = "text LIKE ? ESCAPE '\\'";
      const anyTerm = terms.map(() => like).join(' OR ');
      if (groups.length) {
        const sourceScope = scopeValues.length ? ` WHERE field IN (${placeholders(scopeValues)})` : '';
        const cases = terms.map((term, index) => `MAX(CASE WHEN ${like} THEN 1 ELSE 0 END) AS term_${index}`).join(', ');
        const groupsSql = groups.map(group => '(' + group.map(term => `term_${terms.indexOf(term)}=1`).join(' AND ') + ')').join(' OR ');
        cte = `WITH documents AS (${documents}), scoped AS (SELECT * FROM documents${sourceScope}),
          hits AS (SELECT owner_id, ${cases}, MIN(importance) AS relevance
          FROM scoped WHERE ${anyTerm} GROUP BY owner_id HAVING ${groupsSql}) `;
        values = [...scopeValues, ...patterns, ...patterns];
        matchJoin = ` JOIN hits ON hits.owner_id=${identifier}`;
        order = 'hits.relevance, ' + order;
      }
      const total = this.rows(cte + `SELECT count(*) AS total FROM ${table}${matchJoin}${where}`, [...values, ...filters])[0].total;
      if (total && offset >= total) offset = Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE;
      const result = this.rows(cte + `SELECT ${columns} FROM ${table}${matchJoin}${where} ORDER BY ${order} LIMIT ? OFFSET ?`, [...values, ...filters, PAGE_SIZE, offset]);
      if (groups.length && result.length) {
        const ownerKey = people ? 'researcher_id' : 'project_id', ids = result.map(item => item[ownerKey]);
        const excerpts = this.rows(`WITH documents AS (${documents}) SELECT * FROM documents
          WHERE owner_id IN (${placeholders(ids)}) ${scopeValues.length ? `AND field IN (${placeholders(scopeValues)})` : ''}
          AND (${anyTerm}) ORDER BY importance, source_id, text`, [...ids, ...scopeValues, ...patterns]);
        const firstMatch = new Map();
        for (const excerpt of excerpts) if (!firstMatch.has(excerpt.owner_id)) firstMatch.set(excerpt.owner_id, excerpt);
        result.forEach(item => { item.match = firstMatch.get(item[ownerKey]) || null; });
      }
      return {rows: result, total, offset, page_size: PAGE_SIZE, terms, query, kind};
    }
    detail(kind, identifier) {
      let result;
      if (kind === 'researchers') {
        result = this.rows('SELECT r.*, a.name AS primary_area FROM researchers r JOIN research_areas a ON a.area_id=r.primary_area_id WHERE researcher_id=?', [identifier])[0];
        if (!result) return null;
        result.projects = this.rows('SELECT p.project_id, p.project_code, p.title, p.summary, rp.contribution FROM researcher_projects rp JOIN projects p USING(project_id) WHERE rp.researcher_id=? ORDER BY p.project_id', [identifier]);
        result.capabilities = this.rows('SELECT c.name, rc.proficiency, rc.offer_description FROM researcher_capabilities rc JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY c.name', [identifier]);
        result.needs = this.rows('SELECT n.*, c.name AS capability FROM researcher_needs n LEFT JOIN capabilities c USING(capability_id) WHERE researcher_id=? ORDER BY need_id', [identifier]);
        result.outcomes = this.rows('SELECT * FROM researcher_outcomes WHERE researcher_id=? ORDER BY outcome_id', [identifier]);
      } else {
        result = this.rows('SELECT p.*, t.name AS topic, a.name AS research_area FROM projects p JOIN topics t USING(topic_id) JOIN research_areas a USING(area_id) WHERE project_id=?', [identifier])[0];
        if (!result) return null;
        result.researchers = this.rows('SELECT r.researcher_id, r.full_name, r.role, rp.contribution FROM researcher_projects rp JOIN researchers r USING(researcher_id) WHERE project_id=? ORDER BY r.full_name', [identifier]);
        result.needs = this.rows('SELECT n.*, c.name AS capability FROM project_needs n LEFT JOIN capabilities c USING(capability_id) WHERE project_id=? ORDER BY need_id', [identifier]);
        result.outcomes = this.rows('SELECT * FROM project_outcomes WHERE project_id=? ORDER BY outcome_id', [identifier]);
      }
      return result;
    }
    collaborators(identifier) {
      return this.rows(`SELECT provider_id, provider_name, provider_role, matching_capability, need, proficiency, cross_area
        FROM v_potential_collaborators WHERE seeker_id=? ORDER BY cross_area DESC, proficiency DESC, provider_name LIMIT 12`, [identifier]);
    }
    network() {
      const nodes = this.rows(`SELECT r.researcher_id AS id, r.full_name AS name, r.role, r.primary_area_id AS area_id,
        count(rp.project_id) AS project_count FROM researchers r LEFT JOIN researcher_projects rp USING(researcher_id)
        GROUP BY r.researcher_id ORDER BY r.researcher_id`);
      const links = this.rows(`SELECT a.researcher_id AS source, b.researcher_id AS target, count(*) AS shared_projects
        FROM researcher_projects a JOIN researcher_projects b ON a.project_id=b.project_id AND a.researcher_id<b.researcher_id
        GROUP BY a.researcher_id,b.researcher_id ORDER BY a.researcher_id,b.researcher_id`);
      const degrees = new Map(nodes.map(node => [node.id, 0]));
      links.forEach(edge => { degrees.set(edge.source, degrees.get(edge.source) + 1); degrees.set(edge.target, degrees.get(edge.target) + 1); });
      nodes.forEach(node => { node.degree = degrees.get(node.id); });
      return {nodes, links, areas: this.rows('SELECT area_id,name FROM research_areas ORDER BY area_id'),
        isolated_researchers: nodes.filter(node => node.degree === 0).length};
    }
    request(path) {
      const url = new URL(path, 'https://research.invalid/');
      if (url.pathname === '/api/overview') return this.overview();
      if (url.pathname === '/api/network') return this.network();
      const match = url.pathname.match(/^\/api\/(researchers|projects)(?:\/(\d+)(?:\/(collaborators))?)?$/);
      if (!match) throw new Error('Not found.');
      const [, kind, identifier, related] = match;
      if (!identifier) return this.search(kind, url.searchParams);
      const item = this.detail(kind, Number(identifier));
      if (!item) throw new Error('That record does not exist.');
      if (related) {
        if (kind !== 'researchers') throw new Error('Not found.');
        return {rows: this.collaborators(Number(identifier))};
      }
      return item;
    }
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {ResearchDatabase, parseSearch};
  else root.ResearchDatabase = ResearchDatabase;
})(globalThis);
