const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
  try {
    const context = await browser.newContext({permissions:['microphone']});
    await context.addInitScript(() => {
      localStorage.setItem('speech-audio-source','meeting');
      window.shareCalls = 0;
      window.shareKind = 'audio';
      navigator.mediaDevices.getDisplayMedia = async () => {
        shareCalls++;
        if (shareKind === 'cancel') throw new DOMException('Sharing cancelled','NotAllowedError');
        const c = new AudioContext();
        const out = c.createMediaStreamDestination();
        const tone = c.createOscillator(); tone.connect(out); tone.start();
        window.sharedTestStream = shareKind === 'audio' ? out.stream : new MediaStream();
        return sharedTestStream;
      };
    });
    const page = await context.newPage();
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8879/?mode=lecture&record=1');
    await page.waitForFunction(()=>statusEl.textContent.includes('Ready for your meeting'));
    assert.equal(await page.evaluate(()=>shareCalls),0);
    await page.click('#record');
    await page.waitForFunction(()=>state.recording && state.liveSessionId);
    assert.equal(await page.evaluate(()=>state.media.getVideoTracks().length),0);
    await page.waitForFunction(()=>document.getElementById('meetingLevel').value > 0.1);
    await page.evaluate(()=>sharedTestStream.getAudioTracks()[0].dispatchEvent(new Event('ended')));
    await page.waitForFunction(()=>!state.recording && !state.releaseCaptureLock);
    assert.match(await page.locator('#captureNotice').innerText(),/sharing ended/);
    assert.equal(await page.evaluate(()=>sharedTestStream.getAudioTracks()[0].readyState),'ended');
    for (const kind of ['silent','cancel']) {
      await page.evaluate(kind=>window.shareKind=kind,kind);
      await page.click('#record');
      await page.waitForFunction(()=>!state.starting);
      assert.equal(await page.evaluate(()=>state.recording),false);
      assert.ok((await page.locator('#captureNotice').innerText()).length);
    }
    assert.deepEqual(errors,[]);
    console.log('PASS meeting shortcut requires permission click; audio-only mix and signal meter; share-ended stop; missing audio and cancellation never silently record microphone');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
