import React from 'react'
import ReactMarkdown from 'react-markdown'
import CollapsibleThinking from './CollapsibleThinking'
import ChartRenderer from './ChartRenderer'
import FeedbackButtons from './FeedbackButtons'

const SCENE_LABELS = {
  stock_diagnosis: '个股分析',
  stock_selection: '板块行情',
  customer_service: '平台客服',
  chat: '对话',
  unknown: '',
}

export default function MessageBubble({ message, sessionId }) {
  const {
    role, content, degraded, scene, id,
    reasoning_trace = [],
    visualization_data = [],
    tool_call_log = [],
  } = message

  if (role === 'error') {
    return (
      <div className="bubble-row bubble-row--system">
        <div className="bubble bubble--error">{content}</div>
      </div>
    )
  }

  const isUser = role === 'user'
  const hasThinking = !isUser && (reasoning_trace.length > 0 || tool_call_log.length > 0)
  const hasCharts = !isUser && visualization_data.length > 0

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

        {hasThinking && (
          <CollapsibleThinking
            reasoningTrace={reasoning_trace}
            toolCallLog={tool_call_log}
          />
        )}

        <div className="bubble__content">
          {isUser ? (
            <span>{content}</span>
          ) : (
            <ReactMarkdown>{content}</ReactMarkdown>
          )}
        </div>

        {hasCharts && (
          <div className="bubble__charts">
            {visualization_data.map(chart => (
              <ChartRenderer
                key={chart.chart_id}
                chartId={chart.chart_id}
                chartData={chart.data}
                title={chart.title}
              />
            ))}
          </div>
        )}

        {!isUser && (
          <FeedbackButtons
            messageId={String(id)}
            sessionId={sessionId}
          />
        )}
      </div>
    </div>
  )
}
