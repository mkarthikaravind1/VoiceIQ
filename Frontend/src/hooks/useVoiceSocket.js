import { useRef, useState, useCallback } from 'react'

const WS_URL = 'ws://localhost:8000/ws/voice'
const SAMPLE_RATE = 16000
const BUFFER_SIZE = 4096

export function useVoiceSocket({ onTranscript, onResponse, onStatus, onError, onAudio, onTtsStart, onTtsEnd, onBargeIn }) {
  const wsRef             = useRef(null)
  const connectPromiseRef = useRef(null)
  const streamRef         = useRef(null)
  const processorRef      = useRef(null)
  const contextRef        = useRef(null)

  const [connected, setConnected]   = useState(false)
  const [listening, setListening]   = useState(false)

  // Resolves once the socket is actually open. Calling it again while a
  // connection is open or in progress reuses that one instead of opening another.
  const connect = useCallback(() => {
    const existing = wsRef.current
    if (existing?.readyState === WebSocket.OPEN) return Promise.resolve()
    if (existing?.readyState === WebSocket.CONNECTING && connectPromiseRef.current) {
      return connectPromiseRef.current
    }

    const ws = new WebSocket(WS_URL)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    const promise = new Promise((resolve, reject) => {
      ws.onopen = () => {
        setConnected(true)
        console.log('[WS] Connected')
        resolve()
      }
      ws.onerror = (e) => {
        console.error('[WS] Error', e)
        onError?.({ message: 'WebSocket connection error' })
        reject(new Error('WebSocket connection error'))
      }
    })
    promise.catch(() => {})   // callers that await still see the rejection
    connectPromiseRef.current = promise

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'transcript') onTranscript?.(msg)
        else if (msg.type === 'response') onResponse?.(msg)
        else if (msg.type === 'status')   onStatus?.(msg)
        else if (msg.type === 'error')    onError?.(msg)
        else if (msg.type === 'audio') onAudio?.(msg)
        else if (msg.type === 'barge_in')   onBargeIn?.(msg)
        else if (msg.type === 'tts_start')  onTtsStart?.(msg)
        else if (msg.type === 'tts_end')    onTtsEnd?.(msg)
      } catch (e) {
        console.error('[WS] Parse error', e)
      }
    }

    ws.onclose = () => {
      console.log('[WS] Disconnected')
      // Ignore a stale socket closing after a newer one replaced it
      if (wsRef.current !== ws) return
      wsRef.current = null
      connectPromiseRef.current = null
      setConnected(false)
      setListening(false)
    }

    return promise
  }, [onTranscript, onResponse, onStatus, onError, onAudio, onTtsStart, onTtsEnd, onBargeIn])

  const startListening = useCallback(async () => {
    try {
      await connect()
    } catch {
      return   // onError already reported it
    }

    try {
      // Echo cancellation keeps the agent's own voice (from the speakers)
      // from being heard as the user interrupting.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream

      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE })
      contextRef.current = ctx

      const source    = ctx.createMediaStreamSource(stream)
      const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        if (wsRef.current?.readyState !== WebSocket.OPEN) return
        const float32 = e.inputBuffer.getChannelData(0)
        // Convert float32 → int16 PCM
        const int16 = new Int16Array(float32.length)
        for (let i = 0; i < float32.length; i++) {
          int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768))
        }
        wsRef.current.send(int16.buffer)
      }

      source.connect(processor)
      processor.connect(ctx.destination)

      setListening(true)
    } catch (err) {
      onError?.({ message: `Mic error: ${err.message}` })
    }
  }, [connect, onError])

  const stopListening = useCallback(() => {
    processorRef.current?.disconnect()
    streamRef.current?.getTracks().forEach(t => t.stop())
    contextRef.current?.close()
    processorRef.current = null
    streamRef.current    = null
    contextRef.current   = null

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'end_session' }))
    }
    setListening(false)
  }, [])

  const disconnect = useCallback(() => {
    stopListening()
    wsRef.current?.close()
    wsRef.current = null
    connectPromiseRef.current = null
    setConnected(false)
  }, [stopListening])

  const sendControl = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return { connected, listening, connect, disconnect, startListening, stopListening, sendControl }
}
