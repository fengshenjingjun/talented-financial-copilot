import React, { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import InputBar from './InputBar'

export default function ChatInterface({
  messages,
  isLoading,
  sessionId,
  scene,
  useStreaming,
  setUseStreaming,
  onSend,
  onClear,
}) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <div className="chat-interface">
      {/* Header */}
      <header className="chat-header">
        <div className="chat-header__title">
          <span className="chat-header__icon">📊</span>
          十方灵犀
        </div>
        <div className="chat-header__meta">
          {sessionId && (
            <span className="meta-chip" title="Session ID">
              {sessionId.slice(0, 8)}…
            </span>
          )}
          {scene && scene !== 'unknown' && (
            <span className="meta-chip meta-chip--scene">{scene}</span>
          )}
          <label className="toggle-label" title="切换流式/普通模式">
            <input
              type="checkbox"
              checked={useStreaming}
              onChange={e => setUseStreaming(e.target.checked)}
            />
            流式
          </label>
          <button className="clear-btn" onClick={onClear} title="清除会话">
            ✕ 清除
          </button>
        </div>
      </header>

      {/* Message list */}
      <main className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>👋 您好！我是十方灵犀。</p>
            <p>可以问我个股分析、板块行情、交易规则等金融问题。</p>
          </div>
        )}
        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} sessionId={sessionId} />
        ))}
        {isLoading && (
          <div className="bubble-row bubble-row--assistant">
            <div className="avatar avatar--bot">🤖</div>
            <div className="bubble bubble--assistant bubble--thinking">
              <span className="dot-flashing" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      {/* Input */}
      <InputBar onSend={onSend} isLoading={isLoading} />
    </div>
  )
}
