import React, { useState, useRef, useEffect } from 'react'

const DEMO_QUESTIONS = [
  '你好，你能做什么？',
  '帮我分析一下贵州茅台（600519）的基本面',
  '白酒板块今天表现怎么样？',
  '开户需要什么条件？佣金怎么收？',
]

export default function InputBar({ onSend, isLoading }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
    }
  }, [text])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function handleSend() {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return
    onSend(trimmed)
    setText('')
  }

  return (
    <div className="input-bar">
      <div className="input-bar__demos">
        {DEMO_QUESTIONS.map(q => (
          <button
            key={q}
            className="demo-chip"
            onClick={() => onSend(q)}
            disabled={isLoading}
          >
            {q}
          </button>
        ))}
      </div>
      <div className="input-bar__row">
        <textarea
          ref={textareaRef}
          className="input-bar__textarea"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入您的金融问题… (Enter 发送，Shift+Enter 换行)"
          rows={1}
          disabled={isLoading}
        />
        <button
          className={`input-bar__send-btn ${isLoading ? 'input-bar__send-btn--loading' : ''}`}
          onClick={handleSend}
          disabled={isLoading || !text.trim()}
        >
          {isLoading ? '…' : '发送'}
        </button>
      </div>
    </div>
  )
}
