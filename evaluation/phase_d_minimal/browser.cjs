// Real existing page only. No page.route, fixture endpoints, injected cards, or fake outputs.
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) { console.log('browser.cjs --url localhost --case S8 --evidence DIR [--startup-only | --allow-paid] [--playwright PATH] [--executable PATH]'); return; }
  const get = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args[i + 1]; };
  const base = get('--url', 'http://127.0.0.1:49300');
  if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Only experiment localhost pages are allowed');
  const evidence = path.resolve(get('--evidence', 'data/phase-d-runs/browser'));
  const protocol = JSON.parse(fs.readFileSync(path.join(__dirname, 'protocol.json'), 'utf8'));
  const selected = protocol.cases.find(c => c.id === get('--case', 'S8'));
  if (!selected) throw new Error('Unknown frozen case');
  fs.mkdirSync(evidence, { recursive: true });
  const { chromium } = require(get('--playwright', path.join(__dirname, '../../web/node_modules/playwright')));
  const launch = { headless: true, timeout: 30000, args: ['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1'] };
  if (get('--executable')) launch.executablePath = get('--executable');
  const browser = await chromium.launch(launch);
  const context = await browser.newContext(); // fresh temporary context; no existing browser takeover
  const page = await context.newPage();
  const record = (event, value) => fs.appendFileSync(path.join(evidence, 'browser_events.jsonl'), JSON.stringify({ utc: new Date().toISOString(), event, value }) + '\n');
  // Record application frames, never handshake headers, cookies, or auth URL queries.
  let observedTurns = [];
  page.on('websocket', ws => {
    const url = new URL(ws.url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) throw new Error('Unexpected non-local WebSocket');
    if (url.pathname.startsWith('/_next/')) return; // development HMR is not a durable teaching event
    for (const direction of ['framesent', 'framereceived']) ws.on(direction, frame => {
      let payload;
      try { payload = JSON.parse(String(frame.payload)); } catch { return; }
      if (payload.type === 'auth' || payload.token || payload.authorization) return;
      record(direction, payload);
      if (direction === 'framereceived' && ['done', 'error', 'protocol_error'].includes(payload.type)) {
        observedTurns.push({ ...payload, status: payload.metadata?.status || (['error', 'protocol_error'].includes(payload.type) ? 'failed' : undefined) });
      }
    });
  });
  page.on('pageerror', error => record('pageerror', { name: error.name, message: error.message }));
  try {
    const response = await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (!response || !response.ok()) throw new Error(`Actual page HTTP status: ${response?.status() || 'NO_RESPONSE'}`);
    await page.getByRole('textbox').last().waitFor({ state: 'visible', timeout: 60000 });
    if (!args.includes('--startup-only')) await page.getByRole('textbox').last().waitFor({ state: 'visible', timeout: 60000 });
    record('browser_ready', { browser: browser.version(), case: selected.id, status: args.includes('--startup-only') ? 'STARTUP_ONLY_NO_STUDENT_SUBMISSION' : 'REAL_CASE_STARTED' });
    await page.screenshot({ path: path.join(evidence, 'startup.png'), fullPage: true });
    if (args.includes('--startup-only')) return;
    if (!args.includes('--allow-paid')) throw new Error('Student submission requires explicit --allow-paid after safe authentication readiness');
    const inputs = [`题面：${protocol.question}\n\n学生背景与偏好：${protocol.initial_student_state}\n\n我的提交：${selected.first_input}`, ...selected.followups];
    for (let i = 0; i < inputs.length; i++) {
      observedTurns = [];
      const composer = page.getByRole('textbox').last();
      await composer.fill(inputs[i]);
      await composer.press('Enter');
      record('actual_student_submission', { index: i, text: inputs[i] });
      const started = Date.now();
      let confirmed = false;
      // Wait on the real persisted done/error events and actual card.
      while (Date.now() - started < 180000) {
        const method = page.getByRole('button', { name: /Method 2/ }).last();
        if (!confirmed && await method.isVisible().catch(() => false)) {
          await page.screenshot({ path: path.join(evidence, `turn-${i}-method.png`), fullPage: true });
          await method.click();
          await page.getByRole('button', { name: /^(Submit|Submit answers|提交|提交答案)$/ }).last().click();
          record('actual_method_button_click', { index: i, label: 'Method 2' });
          confirmed = true;
        }
        const terminal = observedTurns.find(t => ['completed', 'failed', 'cancelled'].includes(t.state || t.status || t.turn?.status));
        if (terminal) break;
        await page.waitForTimeout(500);
      }
      const terminal = observedTurns.find(t => ['completed', 'failed', 'cancelled'].includes(t.state || t.status || t.turn?.status));
      fs.writeFileSync(path.join(evidence, `turn-${i}-body.txt`), await page.locator('body').innerText());
      await page.screenshot({ path: path.join(evidence, `turn-${i}.png`), fullPage: true });
      record('turn_observed', { index: i, method_confirmed: confirmed, terminal: terminal || 'NOT_OBSERVED' });
      if (!terminal) throw new Error('Actual terminal done/error was not observed; retain evidence, do not retry sample');
      if ((terminal.state || terminal.status || terminal.turn?.status) !== 'completed') throw new Error('Actual turn failed or was cancelled; retain first result');
      // A streamed done may precede durable finalization. Read the existing
      // session endpoint before the next student submission; never retry a
      // rejected start_turn or infer that its request reached the provider.
      if (i + 1 < inputs.length) {
        if (!terminal.session_id) throw new Error('No actual session ID for durable turn synchronization');
        let idle = false;
        for (let poll = 0; poll < 60; poll++) {
          const reply = await page.request.get(new URL(`/api/sessions/${encodeURIComponent(terminal.session_id)}`, base).href);
          if (!reply.ok()) throw new Error(`Actual session readiness HTTP ${reply.status()}`);
          const session = await reply.json();
          if (Array.isArray(session.active_turns) && session.active_turns.length === 0) { idle = true; break; }
          await page.waitForTimeout(250);
        }
        record('actual_session_ready', { session_id: terminal.session_id, idle });
        if (!idle) throw new Error('Actual session remains active; no next submission');
      }
    }
    const before = await page.locator('body').innerText();
    fs.writeFileSync(path.join(evidence, 'before-refresh.txt'), before);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByRole('textbox').last().waitFor({ state: 'visible', timeout: 60000 });
    await page.waitForFunction(() => document.querySelectorAll('[aria-live="polite"]').length > 0, { timeout: 30000 }).catch(() => record('refresh_history_render', 'NOT_OBSERVED'));
    await page.screenshot({ path: path.join(evidence, 'after-refresh.png'), fullPage: true });
    fs.writeFileSync(path.join(evidence, 'after-refresh.txt'), await page.locator('body').innerText());
    record('refresh_observed', { status: 'REVIEW_BODY_EVENTS_AND_SQLITE_FOR_PUBLICATION_REPLAY; not automatic teaching PASS' });
  } catch (error) {
    record('failure', { name: error.name, message: error.message });
    await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
