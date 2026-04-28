import { useState, useRef, useCallback, useEffect } from 'react'

const API_BASE = '/api'
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/chat`

export function useChat() {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(
    () => localStorage.getItem('fc_session_id') || null
  )
  const [scene, setScene] = useState('unknown')
  const [useStreaming, setUseStreaming] = useState(true)

  // Persist session ID
  useEffect(() => {
    if (sessionId) localStorage.setItem('fc_session_id', sessionId)
  }, [sessionId])

  const addMessage = useCallback((role, content, meta = {}) => {
    setMessages(prev => [...prev, { role, content, ...meta, id: Date.now() + Math.random() }])
  }, [])

  const updateLastAssistantMessage = useCallback((token) => {
    setMessages(prev => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: last.content + token }
      } else {
        copy.push({ role: 'assistant', content: token, id: Date.now() })
      }
      return copy
    })
  }, [])

  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || isLoading) return
    addMessage('user', text)
    setIsLoading(true)

    if (useStreaming) {
      await _streamSSE(text)
    } else {
      await _sendREST(text)
    }
  }, [isLoading, sessionId, useStreaming])

  async function _streamSSE(text) {
    try {
      const resp = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6))
          if (data.token) {
            updateLastAssistantMessage(data.token)
          }
          if (data.done) {
            if (data.session_id) setSessionId(data.session_id)
            if (data.scene) setScene(data.scene)
          }
          if (data.error) {
            addMessage('error', `错误：${data.error}`)
          }
        }
      }
    } catch (err) {
      addMessage('error', `连接失败：${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  async function _sendREST(text) {
    try {
      const resp = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      addMessage('assistant', data.response, { degraded: data.degraded, scene: data.scene })
      setSessionId(data.session_id)
      setScene(data.scene)
    } catch (err) {
      addMessage('error', `请求失败：${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  const clearSession = useCallback(() => {
    localStorage.removeItem('fc_session_id')
    setSessionId(null)
    setMessages([])
    setScene('unknown')
  }, [])

  return {
    messages,
    isLoading,
    sessionId,
    scene,
    useStreaming,
    setUseStreaming,
    sendMessage,
    clearSession,
  }
}
