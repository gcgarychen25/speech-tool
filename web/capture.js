/* Audio-only recording: shared video is used only by the browser picker. */
window.SpeechCapture = {
  async open(mode, onEnded, onLevel) {
    const streams = [];
    let context;
    let meter;
    const close = () => {
      clearInterval(meter);
      streams.forEach(s => s.getTracks().forEach(t => t.stop()));
      if (context) context.close().catch(() => {});
    };
    try {
      let shared;
      if (mode === 'meeting') {
        if (!navigator.mediaDevices.getDisplayMedia) throw new Error('Meeting audio sharing is unavailable. Open Speech Tool in Chrome.');
        // Invoke before any await: screen sharing requires a user gesture.
        shared = await navigator.mediaDevices.getDisplayMedia({
          video: true, audio: {suppressLocalAudioPlayback: false},
          systemAudio: 'include', selfBrowserSurface: 'exclude',
        });
        streams.push(shared);
        if (!shared.getAudioTracks().length) throw new Error('No meeting audio was shared. Choose the meeting tab and enable “Share tab audio”. Some apps/screens cannot share audio on this browser; use the meeting’s browser version. Nothing was recorded.');
      }
      const mic = await navigator.mediaDevices.getUserMedia({audio: true});
      streams.push(mic);
      if (shared && !shared.getAudioTracks().some(t => t.readyState === 'live')) throw new Error('Meeting sharing ended before recording started. Choose the meeting audio again.');
      context = new AudioContext();
      await context.resume();
      const output = context.createMediaStreamDestination();
      const inputs = {microphone: mic};
      if (shared) inputs.meeting = new MediaStream(shared.getAudioTracks());
      const analysers = Object.entries(inputs).map(([name, stream]) => {
        const source = context.createMediaStreamSource(stream);
        const gain = context.createGain();
        gain.gain.value = shared ? 0.7 : 1;
        source.connect(gain).connect(output);
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        return [name, analyser, new Float32Array(analyser.fftSize)];
      });
      meter = setInterval(() => {
        const levels = {};
        analysers.forEach(([name, analyser, data]) => {
          analyser.getFloatTimeDomainData(data);
          levels[name] = Math.min(1, Math.sqrt(data.reduce((s, v) => s + v * v, 0) / data.length) * 5);
        });
        onLevel?.(levels);
      }, 150);
      if (shared) shared.getTracks().forEach(t => t.addEventListener('ended', onEnded, {once:true}));
      streams.push(output.stream);
      return {stream: output.stream, close};
    } catch (error) {close(); throw error;}
  }
};
