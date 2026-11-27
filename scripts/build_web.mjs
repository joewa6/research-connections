import {copyFile, mkdir, readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(root, 'dist');
const source = path.join(root, 'playground/static');
await mkdir(path.join(output, 'vendor'), {recursive: true});
await mkdir(path.join(output, 'data'), {recursive: true});
for (const file of ['app.js', 'network.js', 'styles.css', 'favicon.svg', 'database.js', 'database-worker.js', 'hosted-api.js']) {
  await copyFile(path.join(source, file), path.join(output, file));
}
for (const file of ['sql-wasm.js', 'sql-wasm.wasm']) {
  await copyFile(path.join(root, 'node_modules/sql.js/dist', file), path.join(output, 'vendor', file));
}
await copyFile(path.join(root, 'node_modules/sql.js/LICENSE'), path.join(output, 'vendor/LICENSE-sql.js.txt'));
await copyFile(path.join(root, 'data/sustech_synthetic.sqlite'), path.join(output, 'data/research.sqlite'));
let html = await readFile(path.join(source, 'index.html'), 'utf8');
html = html.replace('<!-- hosted-api -->', '<script src="./hosted-api.js?v=pages-1" defer></script>')
  .replace('href="/" aria-label="Research Connections home"', 'href="./" aria-label="Research Connections home"')
  .replace('Built with SQLite and Python. The dataset stays read-only.', 'The directory uses a read-only copy of the fictional dataset. Searches stay in your browser.')
  .replace('<meta name="viewport"', '<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\' \'wasm-unsafe-eval\'; style-src \'self\'; img-src \'self\' data:; connect-src \'self\'; worker-src \'self\'; object-src \'none\'; base-uri \'self\'">\n  <meta name="viewport"');
await writeFile(path.join(output, 'index.html'), html);
await writeFile(path.join(output, '.nojekyll'), '');
console.log('Built the public website in dist/');
