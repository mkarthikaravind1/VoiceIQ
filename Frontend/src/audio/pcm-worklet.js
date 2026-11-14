// AudioWorklet: runs on the audio thread, converts mic audio at the device's
// sample rate (44.1k / 48k) to 16 kHz int16 PCM and posts it in fixed frames.
// `sampleRate` is a global inside AudioWorkletGlobalScope.

const TARGET_RATE = 16000
const FRAME_SAMPLES = 4096   // ~256 ms per frame sent to the server

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.ratio = sampleRate / TARGET_RATE   // input samples per output sample
    this.pos = 0      // progress toward the next output sample
    this.sum = 0      // input samples are averaged (cheap low-pass before decimating)
    this.count = 0
    this.frame = new Int16Array(FRAME_SAMPLES)
    this.filled = 0
  }

  process(inputs) {
    const channel = inputs[0]?.[0]
    if (!channel) return true

    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i]
      this.count += 1
      this.pos += 1

      if (this.pos >= this.ratio) {
        this.pos -= this.ratio
        const sample = this.sum / this.count
        this.sum = 0
        this.count = 0

        this.frame[this.filled++] = Math.max(-32768, Math.min(32767, sample * 32768))
        if (this.filled === FRAME_SAMPLES) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer])
          this.frame = new Int16Array(FRAME_SAMPLES)
          this.filled = 0
        }
      }
    }
    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
