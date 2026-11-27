/* The public site queries its bundled SQLite database in a background worker. */
(() => {
  const worker = new Worker(new URL('database-worker.js', document.currentScript.src));
  const pending = new Map();
  let sequence = 0;
  let failed = false;

  worker.addEventListener('message', ({data}) => {
    const request = pending.get(data.id);
    if (!request) return;
    pending.delete(data.id);
    request.cleanup();
    if (data.error) request.reject(new Error(data.error));
    else request.resolve(data.result);
  });
  worker.addEventListener('error', () => {
    failed = true;
    pending.forEach(request => {
      request.cleanup();
      request.reject(new Error('The directory could not load. Refresh the page to try again.'));
    });
    pending.clear();
  });

  window.researchData = {
    request(path, {signal} = {}) {
      return new Promise((resolve, reject) => {
        if (failed) return reject(new Error('The directory could not load. Refresh the page to try again.'));
        if (signal?.aborted) return reject(new DOMException('Search cancelled.', 'AbortError'));
        const id = ++sequence;
        const abort = () => { pending.delete(id); reject(new DOMException('Search cancelled.', 'AbortError')); };
        const cleanup = () => signal?.removeEventListener('abort', abort);
        signal?.addEventListener('abort', abort, {once: true});
        pending.set(id, {resolve, reject, cleanup});
        worker.postMessage({id, path});
      });
    }
  };
})();
