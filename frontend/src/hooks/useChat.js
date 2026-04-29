import { useState, useRef, useCallback, useEffect } from 'react'

const API_BASE = '/api'

export function useChat() {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(
    () => localStorage.getItem('fc_session_id') || null
  )
  const [scene, setScene] = useState('unknown')
  const [useStreaming, setUseStreaming] = useState(true)
  const msgCounterRef = useRef(0)

  useEffect(() => {
    if (sessionId) localStorage.setItem('fc_session_id', sessionId)
  }, [sessionId])

  function _nextId() {
    msgCounterRef.current += 1
    return `msg_${Date.now()}_${msgCounterRef.current}`
  }

  const addMessage = useCallback((role, content, meta = {}) => {
    setMessages(prev => [...prev, { role, content, ...meta, id: _nextId() }])
  }, [])

  const updateLastAssistantMessage = useCallback((token) => {
    setMessages(prev => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, content: last.content + token }
      } else {
        copy.push({ role: 'assistant', content: token, id: _nextId(), reasoning_trace: [], visualization_data: [], tool_call_log: [] })
      }
      return copy
    })
  }, [])

  const finalizeLastAssistantMessage = useCallback((meta = {}) => {
    setMessages(prev => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant') {
        copy[copy.length - 1] = { ...last, ...meta }
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

  const sendFeedback = useCallback(async (messageId, rating, comment = null) => {
    const response = await fetch(`${API_BASE}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message_id: messageId,
        session_id: sessionId,
        rating,
        comment,
        timestamp: Date.now() / 1000,
      }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return await response.json()
  }, [sessionId])

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
          let data
          try {
            data = JSON.parse(line.slice(6))
          } catch {
            continue
          }

          if (data.token) {
            updateLastAssistantMessage(data.token)
          }
          if (data.done) {
            if (data.session_id) setSessionId(data.session_id)
            if (data.scene) setScene(data.scene)
            finalizeLastAssistantMessage({
              scene: data.scene,
              reasoning_trace: data.reasoning_trace || [],
              visualization_data: data.visualization_data || [],
              tool_call_log: data.tool_call_log || [],
            })
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
      addMessage('assistant', data.response, {
        degraded: data.degraded,
        scene: data.scene,
        reasoning_trace: data.reasoning_trace || [],
        visualization_data: data.visualization_data || [],
        tool_call_log: data.tool_call_log || [],
      })
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
    sendFeedback,
    clearSession,
  }
}
