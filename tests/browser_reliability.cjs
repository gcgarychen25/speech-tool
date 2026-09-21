const { chromium } = require('playwright');
const assert = require('node:assert/strict');
async function until(check) {
  const deadline = Date.now() + 20000;
  while (!await check()) {
    if (Date.now() > deadline) throw new Error('Timed out waiting for durable audio state');
    await new Promise(resolve => setTimeout(resolve, 100));
  }
}

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']});
  try {
    const context = await browser.newContext({permissions: ['microphone', 'clipboard-read', 'clipboard-write'], viewport: {width: 1280, height: 900}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:8879/?mode=lecture');
    await page.waitForFunction(() => !state.syncing);
    await page.click('#newItem');
    await page.click('#record');
    await page.waitForFunction(() => state.recording && state.liveSessionId);
    const session = await page.evaluate(() => state.liveSessionId);
    await page.fill('#listenerNotes', 'Why does broadcasting align from the right?');
    await page.waitForFunction(() => !state.notesDirty && !state.sessionSavePending);
    await page.locator('#listenerNotes').press('Meta+Enter');
    await page.waitForFunction(() => document.querySelector('#suggestedQuestion').textContent.includes('broadcasting'));
    await page.fill('#questionOut', 'My own wording?');
    assert.equal(await page.locator('#copyQuestion').isEnabled(), true);
    // An old request cannot replace this lecture or its editable fields.
    await page.evaluate(() => renderSession({id:'foreign', display_text:'CONTAMINATION'}, true));
    assert.equal(await page.evaluate(() => state.session.id), session);
    assert.equal(await page.locator('#questionOut').inputValue(), 'My own wording?');
    const second = await context.newPage();
    await second.goto('http://127.0.0.1:8879/?mode=lecture&record=1');
    await second.waitForFunction(() => statusEl.textContent.includes('another Speech Tool tab'));
    assert.equal(await page.evaluate(() => state.recording), true);
    await until(() => page.evaluate(async () => (await SpeechRecovery.list()).some(r => r.blob.size > 0)));
    await page.click('#record');
    await page.waitForFunction(() => !state.liveSessionId && !state.recording);
    assert.equal(await page.evaluate(async () => (await SpeechRecovery.list()).length), 0);
    const saved = await (await context.request.get(`http://127.0.0.1:8879/api/sessions/${session}`)).json();
    assert.equal(saved.chunk_count, 1);
    assert.ok(saved.duration_seconds > 0);
    assert.ok(saved.listener_notes.includes('broadcasting'));
    await page.waitForFunction(() => lectureDraft.value.includes('hello world'));
    assert.equal(await page.locator('#copyNote').isEnabled(), true);
    // Fail an upload, reload, then recover the exact same capture once.
    await page.route('**/api/events?**', route => route.abort());
    await page.click('#record');
    await until(() => page.evaluate(async () => state.recording && (await SpeechRecovery.list()).some(r => r.blob.size > 0)));
    await page.click('#record');
    await page.waitForFunction(() => !state.recording && !state.releaseCaptureLock);
    assert.ok(await page.evaluate(async () => (await SpeechRecovery.list()).length > 0));
    const pending = await page.evaluate(async () => (await SpeechRecovery.list()).map(({blob, ...row}) => ({...row, bytes:blob.size})));
    console.log('Pending recovery', pending);
    await page.unroute('**/api/events?**');
    await page.reload();
    await page.locator('#recoverAudio').waitFor({state:'visible'});
    await page.click('#recoverAudio');
    await until(() => page.evaluate(async () => (await SpeechRecovery.list()).length === 0));
    const recovered = await (await context.request.get(`http://127.0.0.1:8879/api/sessions/${session}`)).json();
    console.log('Recovered session', recovered.id, recovered.chunk_count);
    assert.equal(recovered.chunk_count, 2);
    assert.equal(recovered.latest_question, 'My own wording?');
    await page.screenshot({path: '/private/tmp/speech-classroom-verified.png', fullPage: true});
    assert.deepEqual(errors, []);
    console.log('PASS: capture, audio journal, stop/upload, session isolation, question edit persistence, keyboard shortcut, duplicate-tab guard, failed upload/reload/recovery');
  } finally { await browser.close(); }
})();
