const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8879/?mode=lecture');
    await page.waitForFunction(() => !state.syncing);
    const response = await page.request.post('http://127.0.0.1:8879/api/sessions', {data:{course:'CV test'}});
    const session = await response.json();
    await page.evaluate(async id => {
      state.selectedKind='session'; state.selectedId=id;
      await renderSession(await api(`/api/sessions/${id}`), true);
    }, session.id);
    await page.fill('#listenerNotes', 'Unrelated precision notes');
    const question = 'What is regression in YOLO, and how does it relate to the bounding box?';
    await page.fill('#questionOut', question);
    let captured, release;
    await page.route('**/questions', async route => {
      captured = route.request().postDataJSON();
      await new Promise(resolve => release=resolve);
      await route.fulfill({json:{question:'Which bounding-box quantities does YOLO regress?', model:'test', context_source:'Matched lecture excerpts'}});
    });
    await page.locator('#questionOut').press('Meta+Enter');
    await page.waitForFunction(() => document.querySelector('#questionStatus').dataset.state === 'loading');
    assert.equal(await page.locator('#draftQuestion').isDisabled(), true);
    assert.equal(captured.confusion, question);
    assert.equal(captured.preserve_draft, true);
    assert.equal(captured.mode, 'polish');
    assert.equal(captured.use_context, false);
    assert.equal(await page.locator('#transcriptDetails').getAttribute('open'), null);
    assert.equal(await page.locator('#polishedDetails').getAttribute('open'), null);
    assert.ok((await page.locator('#listenerNotes').boundingBox()).height >= 240);
    await page.evaluate(() => setStatus('Recording update'));
    assert.match(await page.locator('#questionStatus').innerText(), /Drafting/);
    await page.fill('#questionOut', 'My newer wording');
    release();
    await page.locator('#questionSuggestion').waitFor({state:'visible'});
    assert.equal(await page.locator('#questionOut').inputValue(), 'My newer wording');
    assert.match(await page.locator('#questionStatus').innerText(), /earlier draft/);
    await page.click('#useQuestion');
    assert.match(await page.locator('#questionOut').inputValue(), /bounding-box/);
    await page.waitForTimeout(600);
    await page.reload();
    await page.waitForFunction(() => !state.syncing);
    await page.evaluate(async id => {
      state.selectedKind='session'; state.selectedId=id;
      await renderSession(await api(`/api/sessions/${id}`), true);
    }, session.id);
    assert.match(await page.locator('#questionOut').inputValue(), /bounding-box/);
    await page.unroute('**/questions');
    await page.route('**/questions', route => route.fulfill({status:504,json:{detail:'AI took too long'}}));
    await page.click('#draftQuestion');
    await page.waitForFunction(() => document.querySelector('#questionStatus').dataset.state === 'error');
    assert.equal(await page.locator('#draftQuestion').innerText(), 'Retry question');
    assert.match(await page.locator('#questionOut').inputValue(), /bounding-box/);
    await page.unroute('**/questions');
    await page.route('**/questions', async route => {
      await new Promise(resolve => release=resolve);
      await route.fulfill({json:{question:'Late result',model:'test'}}).catch(()=>{});
    });
    await page.click('#draftQuestion');
    await page.click('#stopQuestion');
    release();
    assert.match(await page.locator('#questionStatus').innerText(), /Stopped waiting/);
    assert.match(await page.locator('#questionOut').inputValue(), /bounding-box/);
    await page.unroute('**/questions');
    // Exercise the browser's 30s guard and slow-progress state without a 30s test wait.
    await page.evaluate(() => {
      window.originalQuestionTimeout = window.setTimeout;
      window.setTimeout = (fn, ms, ...args) => window.originalQuestionTimeout(fn, ms === 30000 ? 1500 : ms, ...args);
    });
    await page.route('**/questions', async route => {
      await new Promise(resolve => release=resolve);
      await route.fulfill({json:{question:'Too late',model:'test'}}).catch(()=>{});
    });
    await page.click('#draftQuestion');
    await page.evaluate(() => {questionRequest.started -= 9000;});
    await page.waitForFunction(() => document.querySelector('#questionStatus').textContent.includes('Still waiting'));
    await page.waitForFunction(() => document.querySelector('#questionStatus').textContent.includes('No response after 30'));
    release();
    await page.evaluate(() => {window.setTimeout = window.originalQuestionTimeout;});
    await page.unroute('**/questions');
    await page.route('**/questions', async route => {
      await new Promise(resolve => release=resolve);
      await route.fulfill({json:{question:'Wrong lecture result',model:'test'}}).catch(()=>{});
    });
    await page.click('#draftQuestion');
    await page.evaluate(() => {state.selectedId='another-session'; resetQuestionFields();});
    release();
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#questionSuggestion').isVisible(), false);
    assert.equal(await page.locator('#questionOut').inputValue(), '');
    await page.evaluate(async id => {state.selectedId=id; await renderSession(await api(`/api/sessions/${id}`),true);},session.id);
    await page.unroute('**/questions');
    await page.click('#draftQuestion');
    await page.locator('#questionSuggestion').waitFor({state:'visible'});
    await page.waitForFunction(() => !document.querySelector('#draftQuestion').disabled);
    await page.screenshot({path:'/private/tmp/speech-notes-first-verified.png',fullPage:true});
    assert.deepEqual(errors, []);
    console.log('PASS: typed input, immediate progress, recording-status isolation, concurrent editing, explicit apply, saved wording, timeout/retry, stop waiting, successful real API');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exit(1);});
