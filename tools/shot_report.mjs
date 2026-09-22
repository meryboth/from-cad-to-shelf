// Capture thesis site screenshots through the Chrome DevTools Protocol (headless Chrome)
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9333;
const OUT = 'runs';
mkdirSync(OUT, { recursive: true });
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  '--hide-scrollbars', '--user-data-dir=' + process.env.TEMP + '/cdp-profile', 'about:blank',
], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page;
    } catch {}
    await sleep(500);
  }
  throw new Error('no chrome');
}

const page = await target();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
let id = 0;
const pending = new Map();
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJs = async (expr) => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1200, height: 630, deviceScaleFactor: 1, mobile: false });
// Full-page screenshots of the run report, for sharing outside the browser.
await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: 'http://localhost:5190/runs/' });
await sleep(6000);
await evalJs(`document.querySelectorAll('img').forEach(i => i.loading = 'eager'); scrollTo(0, document.body.scrollHeight);`);
await sleep(6000);
await evalJs('scrollTo(0,0)');
await sleep(1500);
const h = await evalJs('document.body.scrollHeight');
mkdirSync('runs', { recursive: true });
for (let i = 0, y = 0; y < h; i++, y += 1000) {
  const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 80, captureBeyondViewport: true,
    clip: { x: 0, y, width: 1280, height: Math.min(1000, h - y), scale: 1 } });
  writeFileSync(`runs/report-${String(i + 1).padStart(2, '0')}.jpg`, Buffer.from(shot.result.data, 'base64'));
}
console.log('pages', Math.ceil(h / 1000));
chrome.kill(); process.exit(0);
