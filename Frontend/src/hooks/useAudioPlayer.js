import { useRef, useCallback } from 'react'

export function useAudioPlayer() {
  const queueRef   = useRef([])
  const playingRef = useRef(false)
  const ctxRef = useRef(null)
  const sourceRef    = useRef(null)
  // Bumped on every stop. Anything started under an older generation
  // (a chunk still decoding, an onended still to fire) is ignored.
  const genRef = useRef(0)

  const _getCtx = () => {
    if (!ctxRef.current || ctxRef.current.state === 'closed') {
      ctxRef.current = new AudioContext()
    }
    return ctxRef.current
  }

  const _playNext = useCallback(async () => {
    if (playingRef.current || queueRef.current.length === 0) return
    playingRef.current = true

    const gen = genRef.current
    const wavBytes = queueRef.current.shift()
    const ctx = _getCtx()

    try {
      const audioBuffer = await ctx.decodeAudioData(wavBytes.buffer)
      if (gen !== genRef.current) return   // stopped while decoding — don't play
      const source = ctx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(ctx.destination)
      sourceRef.current = source
      source.onended = () => {
        if (gen !== genRef.current) return
        sourceRef.current = null
        playingRef.current = false
        _playNext()
      }
      source.start()
    } catch (e) {
      console.error('[Audio] Playback error', e)
      if (gen !== genRef.current) return
      playingRef.current = false
      _playNext()
    }
  }, [])

  const playChunk = useCallback((base64wav) => {
    // Decode base64 → Uint8Array
    const binary = atob(base64wav)
    const bytes  = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

    queueRef.current.push(bytes)
    _playNext()
  }, [_playNext])

  const stopPlayback = useCallback(() => {
    genRef.current += 1
    try { sourceRef.current?.stop() } catch (_) {}
    sourceRef.current = null
    queueRef.current = []
    playingRef.current = false
  }, [])

  // True while audio is audible or queued — this, not the server's tts_end,
  // is what "the agent is speaking" means.
  const isPlaying = useCallback(
    () => playingRef.current || queueRef.current.length > 0,
    []
  )

  return { playChunk, clearQueue: stopPlayback, stopPlayback, isPlaying }
}
