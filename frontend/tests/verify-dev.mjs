// Isolated HTTP integration check. Does not use AWS, a PEM, or the live server.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer, loadConfigFromFile } from 'vite';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const frontend = path.join(root, 'frontend');
const python = process.env.KIROTHON_TEST_PYTHON || path.join(root, 'backend', '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const temporary = await mkdtemp(path.join(os.tmpdir(), 'kirothon-r2-http-'));
const freePort = net.createServer();
freePort.listen(0, '127.0.0.1');
await once(freePort, 'listening');
const port = freePort.address().port;
await new Promise(resolve => freePort.close(resolve));
let api;
let vite;
let output = '';

async function stopApi() {
  if (!api || api.exitCode !== null) return;
  const exited = once(api, 'exit');
  api.kill();
  let timeout;
  try {
    await Promise.race([exited, new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error('Test API did not stop')), 5000);
    })]);
  } finally {
    clearTimeout(timeout);
    if (api.exitCode === null) api.kill('SIGKILL');
  }
}

async function startApi() {
  api = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: path.join(root, 'backend'),
    env: { ...process.env, KIROTHON_AI_MODE: 'mock',
      KIROTHON_DB_PATH: path.join(temporary, 'records.sqlite3') },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  api.stdout.on('data', data => { output += data.toString(); });
  api.stderr.on('data', data => { output += data.toString(); });
  let spawnError;
  api.on('error', error => { spawnError = error; });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (spawnError) throw spawnError;
    if (api.exitCode !== null) throw new Error('Test API exited: ' + output);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (response.ok) return;
    } catch { /* Startup is asynchronous. */ }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Test API startup timeout: ' + output);
}

try {
  const config = await loadConfigFromFile({ command: 'serve', mode: 'development' },
    path.join(frontend, 'vite.config.ts'));
  assert.equal(config.config.server.proxy['/api'].target, 'http://127.0.0.1:8000');
  await startApi();
  vite = await createServer({ root: frontend, configFile: path.join(frontend, 'vite.config.ts'),
    server: { host: '127.0.0.1', port: 0, strictPort: false, open: false,
      proxy: { '/api': { target: `http://127.0.0.1:${port}` } } } });
  await vite.listen();
  const origin = `http://127.0.0.1:${vite.httpServer.address().port}`;
  async function call(route, data) {
    const response = await fetch(origin + route, data === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    });
    assert.ok(response.ok, `${route}: HTTP ${response.status}`);
    assert.match(response.headers.get('content-type'), /application\/json/);
    return response.json();
  }
  assert.equal((await call('/api/health')).ai_mode, 'mock');
  assert.deepEqual(await call('/api/records'), []);
  const result = await call('/api/ai/generate', { text: 'Isolated local verification' });
  assert.equal(result.mode, 'mock');
  assert.match(result.text, /모의 응답/);
  assert.deepEqual(await call('/api/records'), []);
  const record = await call('/api/records', { title: 'Verification', content: 'Temporary data' });
  await stopApi();
  await startApi();
  assert.equal((await call(`/api/records/${record.id}`)).content, 'Temporary data');
  console.log('LOCAL_HTTP_PROXY_MOCK_AI_AND_RESTART_PERSISTENCE_OK');
} finally {
  if (vite) await vite.close();
  await stopApi();
  await rm(temporary, { recursive: true, force: true });
}
