const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:8879';
(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true,
    args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
  try {
    const context = await browser.newContext({permissions:['microphone'], viewport:{width:1280,height:900}});
    const page = await context.newPage();
    // Await promise predicates explicitly; keep journal and network completion
    // checks independent rather than treating a pending promise as success.
    page.waitForFunction = async (fn, arg) => {
      const deadline = Date.now() + 30000;
      while (!await page.evaluate(fn, arg)) {
        if (Date.now() > deadline) throw new Error(`Timed out: ${fn}; ${JSON.stringify(await page.evaluate(async () => ({status:state.lastStatus, busy:recoveryBusy, rows:(await SpeechRecovery.list()).map(r=>({id:r.id,index:r.index,complete:r.complete}))})))}`);
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    };
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/?mode=lecture');
    await page.waitForFunction(() => !state.syncing);
    await page.click('#newItem');
    await page.click('#record');
    await page.waitForFunction(() => state.recording && state.liveSessionId);
    const sid = await page.evaluate(() => state.liveSessionId);
    const other = await context.newPage();
    await other.goto(base + '/?mode=lecture&record=1');
    await other.waitForFunction(() => statusEl.textContent.includes('another Speech Tool tab'));
    assert.equal(await page.evaluate(() => state.recording), true);
    await other.close();
    await page.waitForFunction(async () => (await SpeechRecovery.list()).some(r => r.blob.size));
    // Persisted server write followed by a lost acknowledgement: retry must
    // acknowledge the same capture, not produce a duplicate event.
    let attempts = 0;
    await page.evaluate(() => {
      window.uploadDiagnostics=[];
      const originalFetch=window.fetch;
      window.fetch=async (...args)=>{const r=await originalFetch(...args); if(String(args[0]).includes('/api/events?')) uploadDiagnostics.push(['response',r.status]); return r;};
      const originalRemove=SpeechRecovery.remove;
      SpeechRecovery.remove=(id)=>{uploadDiagnostics.push(['remove',id,new Error().stack]);return originalRemove(id);};
    });
    await page.route('**/api/events?**', async route => {
      attempts++;
      if (attempts === 1) { await route.fetch(); await route.fulfill({status:503,json:{detail:'Injected lost acknowledgement'}}); }
      else await route.continue();
    });
    await page.click('#record');
    await page.waitForFunction(() => !state.recording && !state.releaseCaptureLock);
    await page.waitForFunction(() => uploadingCaptures.size === 0);
    await page.waitForFunction(async () => (await SpeechRecovery.list()).length === 0);
    console.log('Acknowledgement attempts', attempts, 'state', await page.evaluate(() => ({status:state.lastStatus,session:state.liveSessionId,diag:uploadDiagnostics,uploads:uploadingCaptures.size})));
    assert.ok(attempts >= 2);
    let detail = await (await page.request.get(`${base}/api/sessions/${sid}`)).json();
    assert.equal(detail.chunk_count, 1);
    assert.deepEqual(detail.missing_chunk_indices, []);
    await page.unroute('**/api/events?**');
    console.log('PASS dropped acknowledgement, stable capture ID, no duplicate, duplicate-tab microphone guard');

    // Offline upload is retained, stopping is not blocked, reload auto-recovers.
    await page.route('**/api/events?**', route => route.abort());
    await page.click('#record');
    await page.waitForFunction(async () => state.recording && (await SpeechRecovery.list()).some(r => r.blob.size));
    await page.click('#record');
    await page.waitForFunction(() => !state.recording && !state.releaseCaptureLock);
    await page.waitForFunction(async () => (await SpeechRecovery.list()).some(r => r.complete));
    const saved = await page.evaluate(async () => {
      const row = (await SpeechRecovery.list()).find(r => r.complete);
      return {bytes:Array.from(new Uint8Array(await row.blob.arrayBuffer())), type:row.blob.type};
    });
    detail = await (await page.request.get(`${base}/api/sessions/${sid}`)).json();
    assert.equal(detail.status, 'ended');
    assert.deepEqual(detail.missing_chunk_indices, [1]);
    await page.unroute('**/api/events?**');
    await page.reload();
    await page.waitForFunction(async sid => (await (await fetch(`/api/sessions/${sid}`)).json()).chunk_count === 2, sid);
    await page.waitForFunction(async () => (await SpeechRecovery.list()).length === 0);
    detail = await (await page.request.get(`${base}/api/sessions/${sid}`)).json();
    assert.equal(detail.chunk_count, 2);
    assert.deepEqual(detail.missing_chunk_indices, []);
    console.log('PASS stop despite failed upload, expected trailing gap, reload auto-recovery');
    await page.waitForFunction(() => !recoveryBusy && !state.releaseCaptureLock && uploadingCaptures.size === 0);

    // Interrupted capture never auto-uploads. Manual recovery is explicit.
    await page.evaluate(async ({sid,saved}) => {
      await SpeechRecovery.put({id:'partial-fixture-'+sid,sessionId:sid,index:2,complete:false,
        blob:new Blob([new Uint8Array(saved.bytes)],{type:saved.type}),createdAt:Date.now()});
      await automaticRecovery();
    }, {sid,saved});
    assert.equal(await page.evaluate(async () => (await SpeechRecovery.list()).length), 1);
    await page.locator('#recoverAudio').waitFor({state:'visible'});
    const radius = await page.locator('#recoverAudio').evaluate(e => getComputedStyle(e).borderRadius);
    assert.equal(radius, await page.locator('#stamp').evaluate(e => getComputedStyle(e).borderRadius));
    await page.screenshot({path:'/private/tmp/speech-recovery-desktop.png',fullPage:true});
    await page.click('#recoverAudio');
    await page.waitForFunction(async () => (await SpeechRecovery.list()).length === 0);
    console.log('PASS partial capture requires explicit recovery, consistent action styling');

    // An older missing upload must not cause index reuse when resuming.
    await page.evaluate(async ({sid,saved}) => {
      const blob = new Blob([new Uint8Array(saved.bytes)],{type:saved.type});
      await uploadLectureChunk(blob,sid,4,'gap-fixture-'+sid);
      await SpeechRecovery.put({id:'queued-fixture-'+sid,sessionId:sid,index:6,complete:false,blob,createdAt:Date.now()});
      state.selectedKind='session'; state.selectedId=sid;
      await sync();
    }, {sid,saved});
    await page.locator('#lectureHealthTitle').waitFor({state:'visible'});
    assert.match(await page.locator('#lectureHealthDetail').innerText(), /Missing part.*4/);
    await page.fill('#listenerNotes','Keep my own lecture notes unchanged.');
    await page.waitForFunction(() => !state.notesDirty && !state.sessionSavePending);
    await page.click('#record');
    await page.waitForFunction(() => state.recording && !state.syncing && state.chunkIndex === 7);
    assert.equal(await page.locator('#listenerNotes').inputValue(),'Keep my own lecture notes unchanged.');
    await page.click('#discard');
    await page.waitForFunction(() => !state.recording && !state.releaseCaptureLock);
    console.log('PASS resume uses highest server/local index; gap visible; notes preserved');

    // One conflicted capture must not prevent other recordings from recovery.
    await page.evaluate(async ({sid,saved}) => {
      const blob=new Blob([new Uint8Array(saved.bytes)],{type:saved.type});
      await SpeechRecovery.put({id:'conflict-fixture-'+sid,sessionId:sid,index:4,complete:false,blob,createdAt:Date.now()});
      await SpeechRecovery.put({id:'good-fixture-'+sid,sessionId:sid,index:3,complete:false,blob,createdAt:Date.now()});
      await recoverSavedAudio(true);
    }, {sid,saved});
    const left = await page.evaluate(async () => (await SpeechRecovery.list()).map(r=>r.id));
    assert.ok(left.includes('conflict-fixture-'+sid));
    assert.ok(!left.includes('good-fixture-'+sid));
    console.log('PASS per-capture error isolation and conflicting audio retained');
    await page.setViewportSize({width:680,height:850});
    await page.screenshot({path:'/private/tmp/speech-recovery-narrow.png',fullPage:true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
