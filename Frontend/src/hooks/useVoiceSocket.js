import { useRef, useState, useCallback } from 'react'

const WS_URL = 'ws://localhost:8000/ws/voice'
const SAMPLE_RATE = 16000
const BUFFER_SIZE = 4096

// ── CHANGE: add onTtsStart, onTtsEnd to params
export function useVoiceSocket({ onTranscript, onResponse, onStatus, onError, onAudio, onTtsStart, onTtsEnd }) {
  const wsRef        = useRef(null)
  const streamRef    = useRef(null)
  const processorRef = useRef(null)
  const contextRef   = useRef(null)

  const [connected, setConnected]   = useState(false)
  const [listening, setListening]   = useState(false)

  const connect = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      console.log('[WS] Connected')
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'transcript') onTranscript?.(msg)
        else if (msg.type === 'response') onResponse?.(msg)
        else if (msg.type === 'status')   onStatus?.(msg)
        else if (msg.type === 'error')    onError?.(msg)
        else if (msg.type === 'audio') onAudio?.(msg)
        else if (msg.type === 'tts_start')  onTtsStart?.()   // ── ADD
        else if (msg.type === 'tts_end')    onTtsEnd?.() 
      } catch (e) {
        console.error('[WS] Parse error', e)
      }
    }

    ws.onclose = () => {
      setConnected(false)
      setListening(false)
      console.log('[WS] Disconnected')
    }

    ws.onerror = (e) => {
      console.error('[WS] Error', e)
      onError?.({ message: 'WebSocket connection error' })
    }
  }, [onTranscript, onResponse, onStatus, onError, onAudio, onTtsStart, onTtsEnd])

  const startListening = useCallback(async () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      await connect()
      await new Promise(r => setTimeout(r, 500))
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
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

    wsRef.current?.send(JSON.stringify({ action: 'end_session' }))
    setListening(false)
  }, [])

  const disconnect = useCallback(() => {
    stopListening()
    wsRef.current?.close()
    wsRef.current = null
    setConnected(false)
  }, [stopListening])

  const sendControl = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return { connected, listening, connect, disconnect, startListening, stopListening, sendControl }
}
