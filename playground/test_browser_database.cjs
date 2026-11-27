const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const initSqlJs = require('sql.js');
const {ResearchDatabase, parseSearch} = require('./static/database.js');
const expected = require('./browser_api_fixtures.json');
let database, service;

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}

before(async () => {
  const SQL = await initSqlJs();
  database = new SQL.Database(fs.readFileSync(path.join(__dirname, '../data/sustech_synthetic.sqlite')));
  database.run('PRAGMA query_only=ON');
  service = new ResearchDatabase(database);
});
after(() => database?.close());

for (const [url, fingerprint] of Object.entries(expected)) {
  test('matches the Python API: ' + url, () => {
    const actual = createHash('sha256').update(JSON.stringify(canonical(service.request(url)))).digest('hex');
    assert.equal(actual, fingerprint);
  });
}

test('rejects malformed searches with actionable errors', () => {
  assert.throws(() => parseSearch('"carbon'), /closing quote/);
  assert.throws(() => parseSearch('carbon OR'), /after OR or AND/);
  assert.throws(() => parseSearch('OR carbon'), /before OR/);
  assert.throws(() => parseSearch('""'), /inside the quotes/);
  assert.throws(() => parseSearch('carbon '.repeat(13)), /at most 12/);
  assert.throws(() => service.request('/api/researchers?area=99'), /valid research area/);
  assert.throws(() => service.request('/api/researchers?scope=sql'), /valid search field/);
  assert.throws(() => service.request('/api/researchers/99999'), /does not exist/);
  assert.throws(() => service.request('/api/projects/1/collaborators'), /Not found/);
});

test('browser connection prevents dataset writes', () => {
  assert.throws(() => database.run("UPDATE researchers SET summary='changed'"), /readonly|read-only/i);
});

test('static package works from a repository subdirectory', () => {
  const output = path.join(__dirname, '../dist');
  const html = fs.readFileSync(path.join(output, 'index.html'), 'utf8');
  assert.ok(html.includes('href="./" aria-label="Research Connections home"'));
  assert.ok(html.indexOf('hosted-api.js') < html.indexOf('app.js'));
  for (const match of html.matchAll(/(?:src|href)="([^"#]+)"/g)) {
    if (match[1].startsWith('https:')) continue;
    assert.ok(match[1].startsWith('./'), match[1]);
    assert.ok(fs.existsSync(path.join(output, match[1].split('?')[0])), match[1]);
  }
  assert.deepEqual(fs.readFileSync(path.join(output, 'data/research.sqlite')),
    fs.readFileSync(path.join(__dirname, '../data/sustech_synthetic.sqlite')));
  assert.ok(fs.statSync(path.join(output, 'vendor/sql-wasm.wasm')).size > 100000);
});
