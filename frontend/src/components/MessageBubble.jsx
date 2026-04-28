import React from 'react'
import ReactMarkdown from 'react-markdown'

const SCENE_LABELS = {
  stock_diagnosis: '个股分析',
  stock_selection: '板块行情',
  customer_service: '平台客服',
  chat: '对话',
  unknown: '',
}

export default function MessageBubble({ message }) {
  const { role, content, degraded, scene } = message

  if (role === 'error') {
    return (
      <div className="bubble-row bubble-row--system">
        <div className="bubble bubble--error">{content}</div>
      </div>
    )
  }

  const isUser = role === 'user'

  return (
    <div className={`bubble-row ${isUser ? 'bubble-row--user' : 'bubble-row--assistant'}`}>
      <div className={`avatar ${isUser ? 'avatar--user' : 'avatar--bot'}`}>
        {isUser ? '你' : '🤖'}
      </div>
      <div className={`bubble ${isUser ? 'bubble--user' : 'bubble--assistant'}`}>
        {degraded && (
          <div className="bubble__degraded-badge">⚠ 部分数据不可用</div>
        )}
        {!isUser && scene && SCENE_LABELS[scene] && (
          <div className="bubble__scene-tag">{SCENE_LABELS[scene]}</div>
        )}
        <div className="bubble__content">
          {isUser ? (
            <span>{content}</span>
          ) : (
            <ReactMarkdown>{content}</ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  )
}
