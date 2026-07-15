import { useRef, useCallback } from 'react'

export function useAudioPlayer() {
  const queueRef   = useRef([])
  const playingRef = useRef(false)
  const ctxRef = useRef(null)
  const sourceRef    = useRef(null) 

  const _getCtx = () => {
    if (!ctxRef.current || ctxRef.current.state === 'closed') {
      ctxRef.current = new AudioContext()
    }
    return ctxRef.current
  }

  const _playNext = useCallback(async () => {
    if (playingRef.current || queueRef.current.length === 0) return
    playingRef.current = true

    const wavBytes = queueRef.current.shift()
    const ctx = _getCtx()

    try {
      const audioBuffer = await ctx.decodeAudioData(wavBytes.buffer)
      const source = ctx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(ctx.destination)
      sourceRef.current = source  
      source.onended = () => {
        sourceRef.current = null 
        playingRef.current = false
        _playNext()
      }
      source.start()
    } catch (e) {
      console.error('[Audio] Playback error', e)
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

  const clearQueue = useCallback(() => {
    queueRef.current = []
    playingRef.current = false
  }, [])

  const stopPlayback = useCallback(() => {
    try { sourceRef.current?.stop() } catch (_) {}
    sourceRef.current = null
    queueRef.current = []
    playingRef.current = false
    console.log('[Audio] Barge-in: playback stopped')
  }, [])

  return { playChunk, clearQueue , stopPlayback}
}
