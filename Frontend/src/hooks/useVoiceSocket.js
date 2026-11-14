import { useRef, useState, useCallback, useEffect } from 'react'
import pcmWorkletUrl from '../audio/pcm-worklet.js?url'

// Same host as the page by default (Vite proxies /ws to the backend in dev);
// set VITE_WS_URL to point at a backend on another host.
const WS_URL = import.meta.env.VITE_WS_URL
  ?? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/voice`

export function useVoiceSocket(handlers) {
  const wsRef             = useRef(null)
  const connectPromiseRef = useRef(null)
  const streamRef         = useRef(null)
  const nodeRef           = useRef(null)
  const contextRef        = useRef(null)

  // Always call the latest handlers without re-creating the socket callbacks
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  const [connected, setConnected]   = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [listening, setListening]   = useState(false)

  // Release the microphone and audio graph. Safe to call more than once.
  const cleanupAudio = useCallback(() => {
    if (nodeRef.current) {
      nodeRef.current.port.onmessage = null
      nodeRef.current.disconnect()
    }
    streamRef.current?.getTracks().forEach(t => t.stop())
    if (contextRef.current && contextRef.current.state !== 'closed') {
      contextRef.current.close().catch(() => {})
    }
    nodeRef.current    = null
    streamRef.current  = null
    contextRef.current = null
    setListening(false)
  }, [])

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
    setConnecting(true)

    const promise = new Promise((resolve, reject) => {
      ws.onopen = () => {
        setConnecting(false)
        setConnected(true)
        console.log('[WS] Connected')
        resolve()
      }
      ws.onerror = (e) => {
        console.error('[WS] Error', e)
        handlersRef.current.onError?.({ message: 'Cannot reach the server' })
        reject(new Error('WebSocket connection error'))
      }
    })
    promise.catch(() => {})   // callers that await still see the rejection
    connectPromiseRef.current = promise

    ws.onmessage = (event) => {
      const h = handlersRef.current
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'transcript')      h.onTranscript?.(msg)
        else if (msg.type === 'response')   h.onResponse?.(msg)
        else if (msg.type === 'status')     h.onStatus?.(msg)
        else if (msg.type === 'error')      h.onError?.(msg)
        else if (msg.type === 'audio')      h.onAudio?.(msg)
        else if (msg.type === 'barge_in')   h.onBargeIn?.(msg)
        else if (msg.type === 'tts_start')  h.onTtsStart?.(msg)
        else if (msg.type === 'tts_end')    h.onTtsEnd?.(msg)
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
      setConnecting(false)
      setConnected(false)
      cleanupAudio()   // server went away — don't leave the mic running
      handlersRef.current.onClose?.()
    }

    return promise
  }, [cleanupAudio])

  const startListening = useCallback(async () => {
    try {
      await connect()
    } catch {
      return   // onError already reported it
    }

    cleanupAudio()   // never stack a second mic graph on top of an old one

    try {
      // Echo cancellation keeps the agent's own voice (from the speakers)
      // from being heard as the user interrupting.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      streamRef.current = stream

      // Device-rate context (works in every browser); the worklet downsamples to 16 kHz.
      const ctx = new AudioContext()
      contextRef.current = ctx
      await ctx.audioWorklet.addModule(pcmWorkletUrl)

      const source = ctx.createMediaStreamSource(stream)
      const node   = new AudioWorkletNode(ctx, 'pcm-processor')
      nodeRef.current = node

      node.port.onmessage = (e) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(e.data)
      }

      // Route through a muted gain so the graph is pulled without echoing the mic
      const mute = ctx.createGain()
      mute.gain.value = 0
      source.connect(node)
      node.connect(mute)
      mute.connect(ctx.destination)

      setListening(true)
    } catch (err) {
      cleanupAudio()
      handlersRef.current.onError?.({ message: `Mic error: ${err.message}` })
    }
  }, [connect, cleanupAudio])

  const stopListening = useCallback(() => {
    cleanupAudio()
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'end_session' }))
    }
  }, [cleanupAudio])

  const disconnect = useCallback(() => {
    cleanupAudio()
    const ws = wsRef.current
    wsRef.current = null
    connectPromiseRef.current = null
    if (ws) {
      // Detach first so an intentional close isn't reported as an error
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null
      ws.close()
    }
    setConnecting(false)
    setConnected(false)
  }, [cleanupAudio])

  const sendControl = useCallback((msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  // Connect when the page opens; release mic + socket when it goes away
  useEffect(() => {
    connect().catch(() => {})
    return disconnect
  }, [connect, disconnect])

  return { connected, connecting, listening, connect, disconnect, startListening, stopListening, sendControl }
}
