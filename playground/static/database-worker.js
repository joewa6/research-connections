importScripts('./vendor/sql-wasm.js', './database.js');

const ready = (async () => {
  const [SQL, response] = await Promise.all([
    initSqlJs({locateFile: file => new URL('vendor/' + file, self.location.href).href}),
    fetch(new URL('data/research.sqlite', self.location.href))
  ]);
  if (!response.ok) throw new Error('Dataset unavailable');
  const database = new SQL.Database(new Uint8Array(await response.arrayBuffer()));
  database.run('PRAGMA query_only=ON');
  return new ResearchDatabase(database);
})();
ready.catch(() => {});

self.addEventListener('message', async ({data: {id, path}}) => {
  let service;
  try {
    service = await ready;
  } catch (error) {
    self.postMessage({id, error: 'The dataset could not load. Refresh the page to try again.'});
    return;
  }
  try {
    self.postMessage({id, result: service.request(path)});
  } catch (error) {
    self.postMessage({id, error: error.message});
  }
});
