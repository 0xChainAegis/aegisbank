#!/usr/bin/env node
/**
 * AegisBank U4 real browser integration run.
 *
 * This script intentionally uses a real Chromium browser (Microsoft Edge),
 * the real Vite dev server, the real FastAPI app and a brand-new SQLite file.
 * It does not use jsdom and does not mock any API response.
 *
 * Run from the repository root in WSL:
 *   node scripts/u4-browser-e2e.mjs
 *
 * Optional environment variables:
 *   U4_EDGE_PATH   absolute WSL path to the Windows Edge executable
 *   U4_DB_PATH     database path (default: a fresh /tmp/u4-browser-e2e-*.db)
 *   U4_BASE_URL    frontend URL (default: http://127.0.0.1:5173)
 *   U4_CDP_PORT    fixed DevTools port (default: an ephemeral free port)
 *   U4_EVIDENCE_LABEL  output suffix (default: 2026-10-30; use a new label for new runs)
 *   U4_VIEWPORT_WIDTH / U4_VIEWPORT_HEIGHT  CSS viewport (default: 1440 / 1200)
 */

import { spawn, execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { openSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const fixtureDir = path.join(repoRoot, 'docs', 'fixtures');
mkdirSync(fixtureDir, { recursive: true });

const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
const dbPath = process.env.U4_DB_PATH || `/tmp/u4-browser-e2e-${stamp}-${process.pid}.db`;
const baseUrl = (process.env.U4_BASE_URL || 'http://127.0.0.1:5173').replace(/\/$/, '');
const backendHealthUrl = 'http://127.0.0.1:8000/api/health/ready';
const backendLog = `/tmp/u4-browser-e2e-backend-${stamp}-${process.pid}.log`;
const frontendLog = `/tmp/u4-browser-e2e-frontend-${stamp}-${process.pid}.log`;
const evidenceLabel = process.env.U4_EVIDENCE_LABEL || '2026-10-30';
if (!/^[a-zA-Z0-9-]+$/.test(evidenceLabel)) throw new Error('Invalid U4_EVIDENCE_LABEL');
const viewportWidth = Number(process.env.U4_VIEWPORT_WIDTH || 1440);
const viewportHeight = Number(process.env.U4_VIEWPORT_HEIGHT || 1200);
if (![viewportWidth, viewportHeight].every((value) => Number.isInteger(value) && value >= 320 && value <= 4096)) {
  throw new Error('Viewport dimensions must be integers between 320 and 4096');
}
const evidencePath = path.join(fixtureDir, `u4-real-integration-${evidenceLabel}.json`);
const amendedScreenshotName = `u4-real-integration-${evidenceLabel}-amended-confirmation.png`;
const historyScreenshotName = `u4-real-integration-${evidenceLabel}-final-history.png`;

const actionLog = [];
const domAssertions = [];
const browserFailures = [];
const apiRecords = [];
let apiSequence = 0;
let backendChild = null;
let frontendChild = null;
let edgeChild = null;
let cdp = null;
let cdpPort = Number(process.env.U4_CDP_PORT || 9223);
let edgeOwned = false;
let edgeProfile = null;

function log(...args) {
  console.log(`[u4-e2e ${new Date().toISOString()}]`, ...args);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function bool(value) {
  return value === true;
}

function toPlain(value) {
  if (value === null || value === undefined) return value;
  if (typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(toPlain);
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, toPlain(item)]));
}

function pickHeaders(headers, wanted) {
  const out = {};
  for (const [key, value] of Object.entries(headers || {})) {
    if (wanted.test(key.toLowerCase())) out[key] = value;
  }
  return out;
}

function parseMaybeJson(text) {
  if (typeof text !== 'string') return undefined;
  const trimmed = text.trim();
  if (!trimmed) return '';
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

function requestUrlInfo(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return { path: parsed.pathname, query: parsed.search, origin: parsed.origin };
  } catch {
    return { path: rawUrl, query: '', origin: '' };
  }
}

async function freeTcpPort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

async function serviceResponds(url, timeoutMs = 1200) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    return response.status;
  } catch {
    return null;
  }
}

function spawnLogged(command, args, cwd, env, logFile) {
  const fd = openSync(logFile, 'w');
  const child = spawn(command, args, {
    cwd,
    env,
    detached: true,
    stdio: ['ignore', fd, fd],
  });
  child.unref();
  return child;
}

async function waitForService(name, url, child, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastStatus = null;
  while (Date.now() < deadline) {
    if (child && child.exitCode !== null) {
      throw new Error(`${name} exited before becoming ready (exit ${child.exitCode})`);
    }
    lastStatus = await serviceResponds(url);
    if (lastStatus !== null && lastStatus >= 200 && lastStatus < 500) return lastStatus;
    await sleep(300);
  }
  throw new Error(`Timed out waiting for ${name} at ${url}; last status=${lastStatus}`);
}

function findEdgeExecutable() {
  const candidates = [
    process.env.U4_EDGE_PATH,
    '/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    '/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  ].filter(Boolean);
  return candidates.find((candidate) => {
    if (candidate.startsWith('/')) return existsSync(candidate);
    return true;
  });
}

function windowsPublicProfilePath() {
  return `C:\\Users\\Public\\aegisbank-u4-edge-${stamp}-${process.pid}`;
}

class CdpClient {
  constructor(websocketUrl) {
    this.websocketUrl = websocketUrl;
    this.ws = null;
    this.nextId = 0;
    this.pending = new Map();
    this.handlers = new Map();
  }

  on(method, handler) {
    const current = this.handlers.get(method) || [];
    current.push(handler);
    this.handlers.set(method, current);
  }

  async connect(timeoutMs = 15_000) {
    await new Promise((resolve, reject) => {
      let finished = false;
      const ws = new WebSocket(this.websocketUrl);
      this.ws = ws;
      const timer = setTimeout(() => {
        if (finished) return;
        finished = true;
        reject(new Error(`Timed out connecting to CDP: ${this.websocketUrl}`));
      }, timeoutMs);
      ws.addEventListener('open', () => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        resolve();
      }, { once: true });
      ws.addEventListener('error', (event) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        reject(new Error(`CDP WebSocket error: ${event?.message || 'unknown error'}`));
      }, { once: true });
      ws.addEventListener('message', (event) => this.handleMessage(event));
      ws.addEventListener('close', () => {
        for (const { reject } of this.pending.values()) reject(new Error('CDP connection closed'));
        this.pending.clear();
      });
    });
  }

  handleMessage(event) {
    let message;
    try {
      message = JSON.parse(typeof event.data === 'string' ? event.data : Buffer.from(event.data).toString('utf8'));
    } catch {
      return;
    }
    if (message.id) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
      else pending.resolve(message.result || {});
      return;
    }
    for (const handler of this.handlers.get(message.method) || []) {
      try {
        handler(message.params || {});
      } catch (error) {
        log(`CDP event handler error (${message.method}): ${error?.stack || error}`);
      }
    }
  }

  send(method, params = {}, timeoutMs = 45_000) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error(`CDP WebSocket is not open for ${method}`));
        return;
      }
      const id = ++this.nextId;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Timed out sending CDP ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    try {
      this.ws?.close();
    } catch {
      // Ignore close errors.
    }
  }
}

async function evalValue(expression, { userGesture = false, timeoutMs = 45_000 } = {}) {
  const result = await cdp.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
    userGesture,
    includeCommandLineAPI: true,
  }, timeoutMs);
  if (result.exceptionDetails) {
    const description = result.exceptionDetails.exception?.description
      || result.exceptionDetails.text
      || 'unknown browser exception';
    throw new Error(`Browser evaluation failed: ${description}`);
  }
  return result.result?.value;
}

async function bodyExcerpt(maxChars = 2500) {
  try {
    const text = await evalValue('document.body ? document.body.innerText : ""');
    return String(text || '').slice(0, maxChars);
  } catch {
    return '';
  }
}

async function waitForExpression(expression, label, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await evalValue(expression);
    } catch (error) {
      last = { evaluation_error: String(error?.message || error) };
    }
    if (last) return last;
    await sleep(150);
  }
  const excerpt = await bodyExcerpt();
  throw new Error(`Timed out waiting for ${label}. Last value: ${JSON.stringify(last)}\nDOM excerpt:\n${excerpt}`);
}

async function assertDom(name, expression, timeoutMs = 30_000) {
  const actual = await waitForExpression(expression, name, timeoutMs);
  domAssertions.push({
    name,
    passed: true,
    captured_at: new Date().toISOString(),
    actual: toPlain(actual),
  });
  log(`DOM PASS: ${name}`);
  return actual;
}

async function assertDomIncludes(name, selector, expectedTexts, timeoutMs = 30_000) {
  const expression = `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return false;
    return { text: (el.innerText || el.textContent || '').slice(0, 5000) };
  })()`;
  const actual = await waitForExpression(expression, name, timeoutMs);
  const missing = expectedTexts.filter((text) => !String(actual.text).includes(text));
  if (missing.length) {
    throw new Error(`DOM assertion failed: ${name}; missing ${JSON.stringify(missing)}; actual=${JSON.stringify(actual.text)}`);
  }
  const passed = {
    name,
    passed: true,
    captured_at: new Date().toISOString(),
    selector,
    expected_texts: expectedTexts,
    actual_text: actual.text,
  };
  domAssertions.push(passed);
  log(`DOM PASS: ${name}`);
  return passed;
}

async function clickByText(step, text, { selector = 'button', contains = false, requireEnabled = true } = {}) {
  const expression = `(() => {
    const normalize = (value) => String(value || '').replace(/\\s+/g, '');
    const expected = normalize(${JSON.stringify(text)});
    const nodes = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
    const node = nodes.find((candidate) => {
      const actual = normalize(candidate.textContent);
      return ${contains ? 'actual.includes(expected)' : 'actual === expected'};
    });
    if (!node) {
      return {
        ok: false,
        reason: 'not_found',
        available: nodes.map((candidate) => String(candidate.textContent || '').trim()).filter(Boolean).slice(0, 30),
      };
    }
    if (${requireEnabled ? 'Boolean(node.disabled)' : 'false'}) {
      return { ok: false, reason: 'disabled', text: String(node.textContent || '').trim() };
    }
    node.scrollIntoView({ block: 'center' });
    node.click();
    return {
      ok: true,
      text: String(node.textContent || '').trim(),
      tag: node.tagName,
      aria_label: node.getAttribute('aria-label'),
      disabled: Boolean(node.disabled),
    };
  })()`;
  const result = await evalValue(expression, { userGesture: true });
  if (!result?.ok) {
    throw new Error(`Unable to click ${JSON.stringify(text)}: ${JSON.stringify(result)}`);
  }
  const entry = {
    step,
    captured_at: new Date().toISOString(),
    mechanism: 'CDP Runtime.evaluate + real Chromium HTMLElement.click()',
    selector,
    requested_text: text,
    contains,
    result,
  };
  actionLog.push(entry);
  log(`CLICK: ${step} -> ${result.text}`);
  return entry;
}

async function fillField(step, selector, value, { fieldKind = 'input' } = {}) {
  const expression = `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return { ok: false, reason: 'not_found' };
    if (el.disabled) return { ok: false, reason: 'disabled', value: el.value };
    const prototype = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    if (!setter) return { ok: false, reason: 'no_native_value_setter' };
    el.focus();
    setter.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return {
      ok: true,
      selector: ${JSON.stringify(selector)},
      value: el.value,
      tag: el.tagName,
      aria_label: el.getAttribute('aria-label'),
    };
  })()`;
  const result = await evalValue(expression, { userGesture: true });
  if (!result?.ok || result.value !== value) {
    throw new Error(`Unable to fill ${selector}: ${JSON.stringify(result)}`);
  }
  const entry = {
    step,
    captured_at: new Date().toISOString(),
    mechanism: 'CDP Runtime.evaluate + native HTMLInputElement value setter + input event',
    field_kind: fieldKind,
    selector,
    value,
    result,
  };
  actionLog.push(entry);
  log(`FILL: ${step} -> ${selector} = ${value}`);
  return entry;
}

function recordNetwork(requestId) {
  return apiRecords.find((item) => item.request_id === requestId) || null;
}

async function waitForApi({ step, method = 'POST', pathname, after = 0, predicate = () => true, timeoutMs = 45_000 }) {
  const deadline = Date.now() + timeoutMs;
  let observed = [];
  while (Date.now() < deadline) {
    observed = apiRecords.slice(after).filter((item) => item.request.method === method
      && requestUrlInfo(item.request.url).path === pathname);
    for (const item of observed) {
      if (!item.bodyPromise) continue;
      await item.bodyPromise;
      if (item.response.status !== null && predicate(item.response.body, item)) {
        return item;
      }
    }
    await sleep(120);
  }
  throw new Error(
    `Timed out waiting for API ${method} ${pathname} (${step}). Observed=${JSON.stringify(
      observed.map((item) => ({ status: item.response.status, body: item.response.body, error: item.bodyError })),
    )}`,
  );
}

async function enableNetworkCapture(client) {
  client.on('Network.requestWillBeSent', (params) => {
    const info = requestUrlInfo(params.request?.url || '');
    if (!info.path.startsWith('/api/')) return;
    const bodyText = params.request?.postData;
    const record = {
      sequence: ++apiSequence,
      request_id: params.requestId,
      captured_at: new Date((params.wallTime || Date.now() / 1000) * 1000).toISOString(),
      request: {
        method: params.request?.method || '',
        url: params.request?.url || '',
        ...info,
        headers: pickHeaders(params.request?.headers, /^(content-type|accept|x-aegis-role|idempotency-key|origin|referer)$/i),
        headers_extra: {},
        body_text: typeof bodyText === 'string' ? bodyText : null,
        body: parseMaybeJson(bodyText),
      },
      response: {
        status: null,
        status_text: null,
        mime_type: null,
        headers: {},
        received_at: null,
        finished_at: null,
        body_text: null,
        body: undefined,
      },
      bodyPromise: null,
      bodyError: null,
    };
    apiRecords.push(record);
  });

  client.on('Network.requestWillBeSentExtraInfo', (params) => {
    const record = recordNetwork(params.requestId);
    if (!record) return;
    record.request.headers_extra = pickHeaders(
      params.headers,
      /^(content-type|accept|x-aegis-role|idempotency-key|origin|referer)$/i,
    );
  });

  client.on('Network.responseReceived', (params) => {
    const record = recordNetwork(params.requestId);
    if (!record) return;
    record.response.status = params.response?.status ?? null;
    record.response.status_text = params.response?.statusText ?? null;
    record.response.mime_type = params.response?.mimeType ?? null;
    record.response.headers = pickHeaders(
      params.response?.headers,
      /^(content-type|content-length|cache-control|vary|access-control-allow-origin)$/i,
    );
    record.response.received_at = new Date().toISOString();
  });

  client.on('Network.loadingFinished', (params) => {
    const record = recordNetwork(params.requestId);
    if (!record || !record.response.status) return;
    record.response.finished_at = new Date().toISOString();
    record.bodyPromise = client.send('Network.getResponseBody', { requestId: params.requestId }, 20_000)
      .then(({ body, base64Encoded }) => {
        const text = base64Encoded ? Buffer.from(body || '', 'base64').toString('utf8') : body;
        record.response.body_text = text;
        record.response.body = parseMaybeJson(text);
      })
      .catch((error) => {
        record.bodyError = String(error?.message || error);
      });
  });
}

function selectApiRecords(pathnames) {
  return apiRecords
    .filter((item) => pathnames.includes(requestUrlInfo(item.request.url).path))
    .map((item) => ({
      sequence: item.sequence,
      captured_at: item.captured_at,
      request_id: item.request_id,
      request: {
        method: item.request.method,
        url: item.request.url,
        path: item.request.path,
        query: item.request.query,
        headers: { ...item.request.headers, ...item.request.headers_extra },
        body: item.request.body,
        body_text: item.request.body_text,
      },
      response: {
        status: item.response.status,
        status_text: item.response.status_text,
        mime_type: item.response.mime_type,
        received_at: item.response.received_at,
        finished_at: item.response.finished_at,
        headers: item.response.headers,
        body: item.response.body,
        body_text: item.response.body_text,
        body_error: item.bodyError,
      },
    }));
}

let DatabaseSyncCtor = null;
try {
  ({ DatabaseSync: DatabaseSyncCtor } = await import('node:sqlite'));
} catch {
  DatabaseSyncCtor = null;
}

function queryDb(sql) {
  if (DatabaseSyncCtor) {
    const db = new DatabaseSyncCtor(dbPath, { readOnly: true });
    try {
      return db.prepare(sql).all().map((row) => ({ ...row }));
    } finally {
      db.close();
    }
  }
  const python = [
    'import sqlite3,json,sys',
    'con=sqlite3.connect(sys.argv[1])',
    'con.row_factory=sqlite3.Row',
    'rows=[dict(r) for r in con.execute(sys.argv[2]).fetchall()]',
    'print(json.dumps(rows,ensure_ascii=False))',
    'con.close()',
  ].join(';');
  const output = execFileSync('python3', ['-c', python, dbPath, sql], { encoding: 'utf8' });
  return JSON.parse(output);
}

function dbEvidence(name, sql) {
  const rows = queryDb(sql);
  return { name, queried_at: new Date().toISOString(), sql, rows };
}

async function captureScreenshot(filename) {
  const result = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const absolutePath = path.join(fixtureDir, filename);
  const buffer = Buffer.from(result.data, 'base64');
  await writeFile(absolutePath, buffer);
  return {
    path: `docs/fixtures/${filename}`,
    bytes: buffer.length,
    captured_at: new Date().toISOString(),
  };
}

async function fetchJsonActual(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  return {
    url,
    status: response.status,
    status_text: response.statusText,
    headers: pickHeaders(Object.fromEntries(response.headers.entries()), /^(content-type|content-length)$/i),
    body_text: text,
    body: parseMaybeJson(text),
  };
}

function sourceCommit() {
  try {
    return execFileSync('git', ['-C', repoRoot, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  } catch {
    return null;
  }
}

function sourceWorkingTreeStatus() {
  try {
    return execFileSync('git', ['-C', repoRoot, 'status', '--porcelain'], { encoding: 'utf8' })
      .trim().split('\n').filter(Boolean);
  } catch {
    return null;
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function cleanup() {
  try {
    if (cdp && edgeOwned) await cdp.send('Browser.close', {}, 3000);
  } catch {
    // Browser may already be closed.
  }
  cdp?.close();
  for (const child of [frontendChild, backendChild]) {
    if (!child) continue;
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      try { child.kill('SIGTERM'); } catch { /* ignore */ }
    }
  }
  await sleep(600);
}

let failure = null;
try {
  log(`repository=${repoRoot}`);
  log(`database=${dbPath}`);
  log(`backend log=${backendLog}`);
  log(`frontend log=${frontendLog}`);

  if (await serviceResponds('http://127.0.0.1:8000/api/health', 800) !== null) {
    throw new Error('Port 8000 is already serving something; refusing to reuse an unknown database.');
  }
  if (await serviceResponds(baseUrl, 800) !== null) {
    throw new Error(`Port for ${baseUrl} is already serving something; refusing to use an unknown frontend.`);
  }

  // A fresh database is mandatory for the "exactly one -30000 cent transfer" assertion.
  if (['', '-wal', '-shm'].some((suffix) => existsSync(`${dbPath}${suffix}`))) {
    throw new Error(`Refusing to overwrite an existing database: ${dbPath}`);
  }

  const backendCwd = path.join(repoRoot, '.runtime', 'backend');
  const frontendCwd = path.join(repoRoot, '.runtime', 'frontend');
  log('assembling current six-module source into .runtime');
  execFileSync('python3', [path.join(repoRoot, 'scripts', 'assemble.py')], {
    cwd: repoRoot,
    stdio: 'inherit',
  });
  if (!existsSync(backendCwd)) throw new Error(`Missing assembled backend: ${backendCwd}`);
  if (!existsSync(frontendCwd)) throw new Error(`Missing assembled frontend: ${frontendCwd}`);

  const pathWithUv = `${os.homedir()}/.local/bin:${process.env.PATH || ''}`;
  backendChild = spawnLogged(
    'uv',
    ['run', 'uvicorn', 'aegisbank_api.main:app', '--host', '0.0.0.0', '--port', '8000'],
    backendCwd,
    {
      ...process.env,
      PATH: pathWithUv,
      AEGIS_DATABASE_PATH: dbPath,
      AEGIS_PLANNER_MODE: 'rule',
      AEGIS_AUTOMATION_ENABLED: 'false',
    },
    backendLog,
  );
  frontendChild = spawnLogged(
    'pnpm',
    ['dev', '--host', '0.0.0.0', '--port', '5173', '--strictPort'],
    frontendCwd,
    process.env,
    frontendLog,
  );

  await Promise.all([
    waitForService('FastAPI', backendHealthUrl, backendChild),
    waitForService('Vite', `${baseUrl}/`, frontendChild),
  ]);
  const readiness = await fetchJsonActual(backendHealthUrl);
  assert(readiness.status === 200, `Backend readiness returned ${readiness.status}`);
  assert(readiness.body?.status === 'ready', `Backend readiness body was not ready: ${JSON.stringify(readiness.body)}`);
  log('backend and Vite are ready');

  const cdpHttp = `http://127.0.0.1:${cdpPort}`;
  let browserVersion = null;
  try {
    const existing = await fetch(`${cdpHttp}/json/version`, { signal: AbortSignal.timeout(900) });
    if (existing.ok) browserVersion = await existing.json();
  } catch {
    // No existing CDP endpoint; launch Edge below.
  }

  let edgePath = null;
  let edgeArgs = [];
  if (!browserVersion) {
    edgePath = findEdgeExecutable();
    if (!edgePath) throw new Error('Microsoft Edge executable not found; set U4_EDGE_PATH.');
    edgeProfile = windowsPublicProfilePath();
    edgeArgs = [
      '--headless=new',
      `--remote-debugging-port=${cdpPort}`,
      `--user-data-dir=${edgeProfile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--disable-sync',
      '--disable-gpu',
      '--window-size=1440,1200',
      'about:blank',
    ];
    edgeChild = spawn(edgePath, edgeArgs, { detached: true, stdio: 'ignore' });
    edgeChild.unref();
    edgeOwned = true;
    const cdpDeadline = Date.now() + 30_000;
    while (Date.now() < cdpDeadline && !browserVersion) {
      try {
        const response = await fetch(`${cdpHttp}/json/version`, { signal: AbortSignal.timeout(1000) });
        if (response.ok) browserVersion = await response.json();
      } catch {
        // Edge is still starting.
      }
      if (!browserVersion) await sleep(300);
    }
  }
  if (!browserVersion) throw new Error(`Edge CDP did not start on ${cdpHttp}`);

  let target = null;
  try {
    const listResponse = await fetch(`${cdpHttp}/json/list`, { signal: AbortSignal.timeout(3000) });
    const targets = listResponse.ok ? await listResponse.json() : [];
    target = targets.find((item) => item.type === 'page' && item.url === 'about:blank') || null;
  } catch {
    // Fall through to explicitly creating a target.
  }
  if (!target) {
    const newTargetResponse = await fetch(`${cdpHttp}/json/new?about:blank`, { method: 'PUT' });
    if (!newTargetResponse.ok) throw new Error(`Could not create CDP page: HTTP ${newTargetResponse.status}`);
    target = await newTargetResponse.json();
  }
  cdp = new CdpClient(target.webSocketDebuggerUrl);
  await cdp.connect();

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');
  await cdp.send('Log.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: viewportWidth,
    height: viewportHeight,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await enableNetworkCapture(cdp);

  cdp.on('Runtime.exceptionThrown', (params) => {
    browserFailures.push({
      kind: 'Runtime.exceptionThrown',
      captured_at: new Date().toISOString(),
      detail: params.exceptionDetails,
    });
  });
  cdp.on('Runtime.consoleAPICalled', (params) => {
    if (params.type === 'error' || params.type === 'assert') {
      browserFailures.push({
        kind: 'console',
        captured_at: new Date().toISOString(),
        type: params.type,
        args: (params.args || []).map((arg) => arg.value ?? arg.description ?? arg.type),
      });
    }
  });
  cdp.on('Log.entryAdded', (params) => {
    if (params.entry?.level === 'error') {
      browserFailures.push({
        kind: 'Log.entryAdded',
        captured_at: new Date().toISOString(),
        level: params.entry.level,
        text: params.entry.text,
        source: params.entry.source,
        url: params.entry.url,
        line_number: params.entry.lineNumber,
      });
    }
  });

  await cdp.send('Page.navigate', { url: `${baseUrl}/#/console` });
  await assertDom('console page loaded with real React UI', `(() => {
    const textarea = document.querySelector('textarea#instruction');
    const title = document.querySelector('.assistant-intro h1');
    return textarea && title
      ? { title: document.title, heading: title.textContent, url: location.href, readyState: document.readyState }
      : false;
  })()`, 45_000);

  await assertDom('backend readiness gate opened writes', `(() => {
    const code = document.querySelector('.readiness-ok .readiness-code');
    const blocked = document.querySelector('.command-blocked');
    const submit = document.querySelector('form.command-form button[type="submit"]');
    return code && code.textContent.trim() === 'ready' && !blocked
      ? {
          readiness: code.textContent.trim(),
          command_blocked: false,
          empty_instruction_submit_disabled: submit ? submit.disabled : null,
        }
      : false;
  })()`, 45_000);

  const initialDom = await evalValue(`({
    title: document.title,
    url: location.href,
    readiness: document.querySelector('.readiness-banner')?.innerText || '',
    headings: Array.from(document.querySelectorAll('h1,h2')).map((node) => node.innerText).slice(0, 20),
  })`);

  // 1. First real UI task: "给妈妈转钱".
  const firstMark = apiRecords.length;
  await fillField('输入首轮转账指令', 'textarea#instruction', '给妈妈转钱', { fieldKind: 'textarea' });
  await assertDom('initial submit enabled after typing', `(() => {
    const button = document.querySelector('form.command-form button[type="submit"]');
    return button && !button.disabled ? { text: button.innerText, disabled: button.disabled } : false;
  })()`);
  await clickByText('提交首轮转账任务', '提交任务', { contains: true, selector: 'form.command-form button[type="submit"]' });
  const initialApi = await waitForApi({
    step: '首轮缺失金额澄清',
    pathname: '/api/agent/run',
    after: firstMark,
    predicate: (body) => body?.status === 'needs_clarification' && body?.reason_code === 'missing_amount',
  });
  const initialResult = initialApi.response.body;
  assert(initialResult.draft?.status === 'awaiting_amount', 'Initial draft was not awaiting_amount');
  assert(initialResult.draft?.missing_slots?.includes('amount'), 'Initial draft did not report missing amount');
  await assertDomIncludes('clarification prompt visible', '.clarification-panel', ['请补充金额']);
  await assertDom('follow-up button visible beside clarification', `(() => {
    const button = Array.from(document.querySelectorAll('button')).find(
      (candidate) => String(candidate.textContent || '').replace(/\\s+/g, '') === '补充上一条任务信息'
    );
    return button && !button.disabled
      ? { button_text: button.innerText, disabled: button.disabled, body_has_prompt: document.body.innerText.includes('上一条任务需要补充信息') }
      : false;
  })()`);

  // 2. Click the UI's follow-up entry point, then answer with "五百".
  await clickByText('点击补充上一条任务信息', '补充上一条任务信息', { contains: true });
  await assertDom('follow-up mode is visually active', `(() => {
    const text = document.body.innerText;
    return text.includes('当前输入将补充上一条任务') ? { follow_up_banner: true } : false;
  })()`);
  const fillMark = apiRecords.length;
  await fillField('输入补充金额', 'textarea#instruction', '五百', { fieldKind: 'textarea' });
  await assertDom('follow-up submit enabled after typing amount', `(() => {
    const button = document.querySelector('form.command-form button[type="submit"]');
    return button && !button.disabled ? { text: button.innerText, disabled: button.disabled } : false;
  })()`);
  await clickByText('提交补充金额五百', '提交任务', { contains: true, selector: 'form.command-form button[type="submit"]' });
  const filledApi = await waitForApi({
    step: '补充金额生成 500 元确认',
    pathname: '/api/agent/run',
    after: fillMark,
    predicate: (body) => body?.status === 'awaiting_confirmation'
      && body?.plan?.steps?.some((step) => step.tool_name === 'transfer_to_contact' && step.arguments?.amount_cny === 500),
  });
  const filledResult = filledApi.response.body;
  const oldActionId = filledResult.confirmation?.id;
  const oldDraft = filledResult.draft;
  assert(oldActionId, 'No old confirmation action id was returned');
  assert(oldDraft?.version === 2, `Expected old draft version 2, got ${oldDraft?.version}`);
  assert(filledApi.request.body.session_id === initialResult.session_id, 'Follow-up did not send the real session id');
  assert(filledApi.request.body.draft_id === initialResult.draft.draft_id, 'Follow-up did not send the real draft id');
  assert(filledApi.request.body.draft_version === initialResult.draft.version, 'Follow-up did not send the real draft version');
  await assertDomIncludes('500 CNY confirmation modal visible', '[role="dialog"]', ['确认', '转账', '修改金额', '尚未执行']);
  await assertDomIncludes('500 CNY amount is in the confirmation modal', '.confirm-summary', ['500.00']);
  await assertDomIncludes('debit account is shown from the compiled plan', '.confirm-summary', ['ACC-1001']);

  // 3. Use the product UI amount amendment path.
  await clickByText('打开修改金额面板', '修改金额', { contains: false });
  await assertDom('amount amendment field is present', `(() => {
    const input = document.querySelector('input[aria-label="新金额（元）"]');
    return input && !input.disabled ? { aria_label: input.getAttribute('aria-label'), value: input.value } : false;
  })()`);
  const amendMark = apiRecords.length;
  await fillField('输入新金额 300', 'input[aria-label="新金额（元）"]', '300', { fieldKind: 'input' });
  await assertDom('submit amendment enabled', `(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const button = buttons.find((item) => String(item.textContent || '').replace(/\\s+/g, '') === '提交修改');
    return button && !button.disabled ? { text: button.innerText, disabled: button.disabled } : false;
  })()`);
  await clickByText('提交金额修改', '提交修改', { contains: false });
  const amendedApi = await waitForApi({
    step: '修改金额后生成新确认',
    pathname: '/api/agent/run',
    after: amendMark,
    predicate: (body) => body?.status === 'awaiting_confirmation'
      && body?.plan?.steps?.some((step) => step.tool_name === 'transfer_to_contact' && step.arguments?.amount_cny === 300)
      && body?.confirmation?.id
      && body.confirmation.id !== oldActionId,
  });
  const amendedResult = amendedApi.response.body;
  const newActionId = amendedResult.confirmation?.id;
  const newDraft = amendedResult.draft;
  assert(newActionId && newActionId !== oldActionId, 'Amendment did not produce a new action id');
  assert(newDraft?.version === 3, `Expected new draft version 3, got ${newDraft?.version}`);
  assert(amendedApi.request.body.instruction === '不是500，改成300', `Unexpected amendment instruction: ${amendedApi.request.body.instruction}`);
  assert(amendedApi.request.body.draft_id === oldDraft.draft_id, 'Amendment did not use the old draft id');
  assert(amendedApi.request.body.draft_version === oldDraft.version, 'Amendment did not use the old draft version');
  await assertDomIncludes('300 CNY confirmation modal visible after amendment', '[role="dialog"]', ['确认', '转账', '300.00', '修改金额', '尚未执行']);
  await assertDom('new confirmation action differs in DOM/backend state', `(() => {
    const dialog = document.querySelector('[role="dialog"]');
    const confirmButton = Array.from(document.querySelectorAll('[role="dialog"] button')).find(
      (button) => String(button.textContent || '').replace(/\\s+/g, '') === '确认执行'
    );
    return dialog && dialog.innerText.includes('300.00') && confirmButton && !confirmButton.disabled
      ? { modal_text_excerpt: dialog.innerText.slice(0, 1200), confirm_button: confirmButton.innerText }
      : false;
  })()`);

  const amendedScreenshot = await captureScreenshot(amendedScreenshotName);

  // 4. Prove the superseded action is rejected by the real backend before executing the new one.
  const oldConfirmRequest = {
    method: 'POST',
    url: `${baseUrl}/api/confirmations/${encodeURIComponent(oldActionId)}`,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Aegis-Role': 'user',
    },
    body: {
      approved: true,
      user_id: 'demo-user',
      session_id: initialResult.session_id,
      draft_id: oldDraft.draft_id,
      draft_version: oldDraft.version,
    },
  };
  const oldConfirmResponse = await fetchJsonActual(oldConfirmRequest.url, {
    method: oldConfirmRequest.method,
    headers: oldConfirmRequest.headers,
    body: JSON.stringify(oldConfirmRequest.body),
  });
  const oldConfirmAttempt = {
    captured_at: new Date().toISOString(),
    executor: 'Node.js fetch outside the browser DOM, through the real Vite /api proxy to FastAPI',
    request: oldConfirmRequest,
    response: oldConfirmResponse,
    assertions: {
      http_status_409: oldConfirmResponse.status === 409,
      error_code_draft_version_conflict: oldConfirmResponse.body?.detail?.code === 'draft_version_conflict',
    },
  };
  assert(oldConfirmResponse.status === 409, `Old confirmation returned ${oldConfirmResponse.status}: ${oldConfirmResponse.body_text}`);
  assert(oldConfirmResponse.body?.detail?.code === 'draft_version_conflict', 'Old confirmation did not return draft_version_conflict');
  const beforeConfirmationTransfer = dbEvidence(
    'before final confirmation: superseded action did not write a transfer',
    "SELECT transaction_id, merchant, category, amount_cents, occurred_at FROM bank_transactions WHERE category='transfer' ORDER BY occurred_at, transaction_id",
  );
  assert(beforeConfirmationTransfer.rows.length === 0, `A transfer existed before confirmation: ${JSON.stringify(beforeConfirmationTransfer.rows)}`);

  // 5. Confirm the newly amended action through the product UI.
  const confirmMark = apiRecords.length;
  await clickByText('确认执行新的 300 元转账', '确认执行', { contains: false });
  const confirmedApi = await waitForApi({
    step: '真实确认接口执行新转账',
    pathname: `/api/confirmations/${newActionId}`,
    after: confirmMark,
    predicate: (body) => body?.status === 'completed' && Array.isArray(body?.results),
  });
  const confirmedResult = confirmedApi.response.body;
  assert(confirmedResult.results?.some((result) => result.tool_name === 'transfer_to_contact'), 'Confirmed response lacked transfer_to_contact result');
  assert(confirmedApi.request.body.draft_version === newDraft.version, 'Confirmation did not send the new draft version');
  await assertDomIncludes('transfer receipt visible after execution', '.business-receipt-transfer', ['转账回执', '300.00']);
  await assertDom('confirmation dialog closed after execution', `(() => {
    const dialog = document.querySelector('[role="dialog"]');
    return dialog ? false : { dialog_closed: true, result_text_excerpt: document.querySelector('.result-card')?.innerText.slice(0, 1500) || '' };
  })()`);

  // 6. Query the most recent transfer amount through the UI.
  const historyMark = apiRecords.length;
  await fillField('输入最近转账金额查询', 'textarea#instruction', '我刚才转了多少', { fieldKind: 'textarea' });
  await waitForExpression(`(() => {
    const button = document.querySelector('form.command-form button[type="submit"]');
    return button && !button.disabled ? true : false;
  })()`, 'history amount submit enabled');
  await clickByText('提交最近转账金额查询', '提交任务', { contains: true, selector: 'form.command-form button[type="submit"]' });
  const historyAmountApi = await waitForApi({
    step: '最近转账金额真实回读',
    pathname: '/api/agent/run',
    after: historyMark,
    predicate: (body) => body?.status === 'completed'
      && body?.results?.some((result) => result.tool_name === 'query_recent_transfer' && result.data?.found === true),
  });
  const historyAmountResult = historyAmountApi.response.body;
  const recentAmount = historyAmountResult.results.find((result) => result.tool_name === 'query_recent_transfer').data;
  assert(recentAmount.contact_name === '妈妈', `History amount contact was ${recentAmount.contact_name}`);
  assert(recentAmount.amount_cny === 300, `History amount was ${recentAmount.amount_cny}`);
  const historyReceiptOne = await assertDomIncludes(
    'history receipt shows 妈妈 and 300.00 after amount query',
    '[aria-label="最近转账查询结果"]',
    ['最近转账查询结果', '妈妈', '300.00'],
  );

  // 7. Query the recipient through the UI once more.
  const whoMark = apiRecords.length;
  await fillField('输入最近转账对象查询', 'textarea#instruction', '我刚才转给谁', { fieldKind: 'textarea' });
  await waitForExpression(`(() => {
    const button = document.querySelector('form.command-form button[type="submit"]');
    return button && !button.disabled ? true : false;
  })()`, 'history recipient submit enabled');
  await clickByText('提交最近转账对象查询', '提交任务', { contains: true, selector: 'form.command-form button[type="submit"]' });
  const whoApi = await waitForApi({
    step: '最近转账对象真实回读',
    pathname: '/api/agent/run',
    after: whoMark,
    predicate: (body) => body?.status === 'completed'
      && body?.results?.some((result) => result.tool_name === 'query_recent_transfer' && result.data?.found === true),
  });
  const whoResult = whoApi.response.body;
  const recentRecipient = whoResult.results.find((result) => result.tool_name === 'query_recent_transfer').data;
  assert(recentRecipient.contact_name === '妈妈', `Recipient query contact was ${recentRecipient.contact_name}`);
  assert(recentRecipient.amount_cny === 300, `Recipient query amount was ${recentRecipient.amount_cny}`);
  const finalReceipt = await assertDomIncludes(
    'final history receipt shows 妈妈 and 300.00 after recipient query',
    '[aria-label="最近转账查询结果"]',
    ['最近转账查询结果', '妈妈', '300.00'],
  );
  const finalReceiptText = finalReceipt.actual_text;
  const currencyTokenMatch = finalReceiptText.match(/(?:¥|￥)\s?300\.00/);
  assert(currencyTokenMatch, `Final receipt did not contain a CNY 300.00 token: ${finalReceiptText}`);
  await assertDom('final query was served by the completed backend response', `(() => {
    const receipt = document.querySelector('[aria-label="最近转账查询结果"]');
    const result = document.querySelector('.result-card');
    return receipt && result && receipt.innerText.includes('妈妈') && receipt.innerText.includes('300.00')
      ? {
          receipt_innerText: receipt.innerText,
          result_innerText_excerpt: result.innerText.slice(0, 3000),
          url: location.href,
          title: document.title,
        }
      : false;
  })()`);

  await evalValue(`(() => {
    const receipt = document.querySelector('[aria-label="最近转账查询结果"]');
    receipt?.scrollIntoView({ block: 'center' });
    return true;
  })()`);
  await sleep(300);
  const historyScreenshot = await captureScreenshot(historyScreenshotName);

  // Allow all captured response bodies to finish before serializing evidence.
  for (let i = 0; i < 50; i += 1) {
    const pendingBodies = apiRecords.filter((item) => item.response.status && !item.bodyPromise);
    if (pendingBodies.length === 0) break;
    await sleep(100);
  }
  await Promise.allSettled(apiRecords.map((item) => item.bodyPromise).filter(Boolean));

  const finalDom = await evalValue(`(() => {
    const receipt = document.querySelector('[aria-label="最近转账查询结果"]');
    const result = document.querySelector('.result-card');
    return {
      url: location.href,
      title: document.title,
      readiness: document.querySelector('.readiness-banner')?.innerText || '',
      receipt: receipt?.innerText || null,
      result_card: result?.innerText || null,
      body_text_excerpt: document.body.innerText.slice(0, 5000),
    };
  })()`);

  const transferRowsFinal = dbEvidence(
    'final: exactly one real transfer row at -30000 cents',
    "SELECT transaction_id, user_id, account_id, merchant, category, amount_cents, occurred_at, status, note FROM bank_transactions WHERE category='transfer' ORDER BY occurred_at, transaction_id",
  );
  const pendingRowsFinal = dbEvidence(
    'final: old and new confirmation states',
    'SELECT id, user_id, instruction, risk_level, status, state, created_at, expires_at, resolved_at, result_json FROM pending_actions ORDER BY created_at, id',
  );
  const auditRowsFinal = dbEvidence(
    'final: transfer execution audit rows',
    "SELECT id, created_at, event, tool_name, confirmation_state, risk_level, arguments_json, result_json FROM audit_log WHERE tool_name IN ('transfer_to_contact','transfer') ORDER BY id",
  );
  const accountRowsFinal = dbEvidence(
    'final: account balances after transfer',
    'SELECT account_id, name, balance_cents, available_cents FROM bank_accounts ORDER BY account_id',
  );

  assert(transferRowsFinal.rows.length === 1, `Expected exactly one transfer row, got ${transferRowsFinal.rows.length}`);
  assert(Number(transferRowsFinal.rows[0].amount_cents) === -30000, `Expected -30000 cents, got ${transferRowsFinal.rows[0].amount_cents}`);
  assert(pendingRowsFinal.rows.some((row) => row.id === oldActionId && String(row.state).toUpperCase() !== 'EXECUTED'), 'Old action unexpectedly appears executed');
  assert(pendingRowsFinal.rows.some((row) => row.id === newActionId), 'New action was not persisted');

  const keyApiInteractions = selectApiRecords(['/api/agent/run', '/api/confirmations', `/api/confirmations/${newActionId}`]);
  const finalBrowserVersion = await cdp.send('Browser.getVersion');
  const backendLogTail = execFileSync('tail', ['-n', '120', backendLog], { encoding: 'utf8' });
  const frontendLogTail = execFileSync('tail', ['-n', '80', frontendLog], { encoding: 'utf8' });

  const evidence = {
    schema: 'aegisbank-u4-real-integration-evidence/v1',
    title: 'AegisBank U4 real browser + real FastAPI/Vite/SQLite integration evidence',
    generated_at: new Date().toISOString(),
    source: {
      repository: repoRoot,
      commit: sourceCommit(),
      working_tree_dirty: (sourceWorkingTreeStatus() || []).length > 0,
      working_tree_status: sourceWorkingTreeStatus(),
      note: 'commit is the base HEAD; working_tree_status records the U4 changes that were present at capture time. Evidence came from the only source repository and a fresh assembly/runtime, not from a second code tree.',
    },
    scope: {
      integration_type: 'real browser UI -> real Vite dev server -> real Vite /api proxy -> real FastAPI -> fresh SQLite',
      mocked_or_jsdom: false,
      browser_automation: 'Microsoft Edge headless via Chrome DevTools Protocol; Runtime.evaluate dispatches real DOM click/input events in Chromium',
      backend: 'uvicorn aegisbank_api.main:app',
      frontend: 'Vite 7 dev server',
      database: 'fresh SQLite file created for this run',
    },
    environment: {
      viewport: { width: viewportWidth, height: viewportHeight, mobile_emulation: false },
      node_version: process.version,
      node_platform: process.platform,
      linux_release: os.release(),
      hostname: os.hostname(),
      browser: {
        product: finalBrowserVersion.product,
        revision: finalBrowserVersion.revision,
        user_agent: finalBrowserVersion.userAgent,
        js_version: finalBrowserVersion.jsVersion,
        protocol_version: browserVersion['Protocol-Version'],
        edge_executable: edgePath,
        launch_command: [edgePath, ...edgeArgs],
        user_data_dir: edgeProfile,
        cdp_http: cdpHttp,
        cdp_target: target.url,
      },
      services: {
        backend: {
          cwd: backendCwd,
          command: 'PATH="$HOME/.local/bin:$PATH" AEGIS_DATABASE_PATH=' + dbPath + ' uv run uvicorn aegisbank_api.main:app --host 0.0.0.0 --port 8000',
          argv: ['uv', 'run', 'uvicorn', 'aegisbank_api.main:app', '--host', '0.0.0.0', '--port', '8000'],
          log: backendLog,
          health: readiness,
        },
        frontend: {
          cwd: frontendCwd,
          command: 'pnpm dev --host 0.0.0.0 --port 5173 --strictPort',
          argv: ['pnpm', 'dev', '--host', '0.0.0.0', '--port', '5173', '--strictPort'],
          url: baseUrl,
          log: frontendLog,
          proxy_note: 'The browser called /api on port 5173; Vite proxied those calls to FastAPI on 127.0.0.1:8000.',
        },
        database: { path: dbPath, fresh_for_this_run: true },
      },
    },
    ui_flow: {
      initial_dom: initialDom,
      actions: actionLog,
      dom_assertions: domAssertions,
      final_dom: finalDom,
      screenshots: [amendedScreenshot, historyScreenshot],
    },
    api_evidence: {
      capture_method: 'CDP Network.requestWillBeSent + Network.responseReceived + Network.getResponseBody',
      api_request_count: apiRecords.length,
      key_interactions: keyApiInteractions,
      old_confirmation_rejected_outside_browser: oldConfirmAttempt,
    },
    database_evidence: {
      before_final_confirmation: beforeConfirmationTransfer,
      final_transfer_rows: transferRowsFinal,
      final_pending_actions: pendingRowsFinal,
      final_transfer_audit_rows: auditRowsFinal,
      final_accounts: accountRowsFinal,
      queries_executed_with: DatabaseSyncCtor ? 'node:sqlite DatabaseSync (readOnly)' : 'python3 sqlite3',
    },
    browser_console_errors: browserFailures,
    key_identifiers: {
      session_id: initialResult.session_id,
      draft_id: initialResult.draft.draft_id,
      old_action_id: oldActionId,
      new_action_id: newActionId,
      old_draft_version: oldDraft.version,
      new_draft_version: newDraft.version,
      final_transfer_transaction_id: transferRowsFinal.rows[0]?.transaction_id || null,
      history_transaction_id: recentRecipient.transaction_id || null,
    },
    assertions: {
      real_browser_ui_used: true,
      real_vite_proxy_used: true,
      real_fastapi_used: true,
      fresh_sqlite_used: true,
      first_turn_asked_for_missing_amount: true,
      second_turn_amount_500_created_confirmation: true,
      ui_amount_amendment_created_new_action: true,
      old_action_rejected_with_409_draft_version_conflict: oldConfirmAttempt.assertions.http_status_409
        && oldConfirmAttempt.assertions.error_code_draft_version_conflict,
      no_transfer_before_old_confirmation_rejection: beforeConfirmationTransfer.rows.length === 0,
      exactly_one_transfer_row: transferRowsFinal.rows.length === 1,
      transfer_amount_is_minus_30000_cents: Number(transferRowsFinal.rows[0]?.amount_cents) === -30000,
      history_amount_receipt_contains_mama_and_300_00: recentAmount.contact_name === '妈妈' && recentAmount.amount_cny === 300,
      history_recipient_receipt_contains_mama_and_300_00: recentRecipient.contact_name === '妈妈' && recentRecipient.amount_cny === 300,
      final_dom_receipt_contains_mama_and_currency_300: finalReceiptText.includes('妈妈') && Boolean(currencyTokenMatch),
    },
    logs: {
      backend_tail: backendLogTail,
      frontend_tail: frontendLogTail,
    },
    limitations: [
      'This is the deterministic Mock Bank Core and simulated transfers; it does not connect to a real bank or payment network.',
      'The browser is headless Microsoft Edge controlled through CDP; DOM interactions are real Chromium events but not human physical mouse/keyboard input.',
      'The fresh SQLite path and service logs live under /tmp and are intentionally not committed; the query results and actual raw values are captured in this fixture.',
      'MFA tokens are demo-only; the 300 CNY transfer is yellow risk and therefore required explicit light confirmation, not OTP.',
    ],
  };

  await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  log(`EVIDENCE: ${evidencePath}`);
  log(`SCREENSHOT: docs/fixtures/${amendedScreenshotName}`);
  log(`SCREENSHOT: docs/fixtures/${historyScreenshotName}`);
  log(`FINAL TRANSFER ROWS: ${JSON.stringify(transferRowsFinal.rows)}`);
  log(`OLD CONFIRM: HTTP ${oldConfirmResponse.status} ${JSON.stringify(oldConfirmResponse.body)}`);
  log(`FINAL RECEIPT: ${finalReceiptText.replace(/\n/g, ' | ')}`);
  log('U4 REAL BROWSER E2E PASSED');
} catch (error) {
  failure = error;
  console.error(`[u4-e2e ${new Date().toISOString()}] U4 REAL BROWSER E2E FAILED`);
  console.error(error?.stack || error);
  try {
    if (cdp) {
      const html = await bodyExcerpt(6000);
      console.error(`[u4-e2e] DOM at failure:\n${html}`);
      try {
        const shot = await captureScreenshot(`u4-real-integration-${evidenceLabel}-failure.png`);
        console.error(`[u4-e2e] failure screenshot: ${JSON.stringify(shot)}`);
      } catch {
        // Screenshot is best-effort on failure.
      }
    }
  } catch {
    // Diagnostics are best-effort.
  }
  process.exitCode = 1;
} finally {
  await cleanup();
  if (failure) {
    console.error(`[u4-e2e] logs retained: backend=${backendLog} frontend=${frontendLog} db=${dbPath}`);
  }
}
