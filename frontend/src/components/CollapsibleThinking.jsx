import React, { useState } from 'react'

const STEP_TYPE_CONFIG = {
  intent_detection: { label: '意图识别', color: '#4f7fff', icon: '🔍' },
  tool_call:        { label: '工具调用', color: '#f59e0b', icon: '⚙️' },
  data_analysis:    { label: '数据分析', color: '#22c55e', icon: '📊' },
  synthesis:        { label: '综合生成', color: '#a855f7', icon: '✨' },
}

function StepDetail({ details }) {
  const [open, setOpen] = useState(false)
  if (!details || Object.keys(details).length === 0) return null
  return (
    <div className="thinking-step__detail">
      <button className="thinking-step__detail-toggle" onClick={() => setOpen(o => !o)}>
        {open ? '▲ 收起详情' : '▼ 展开详情'}
      </button>
      {open && (
        <pre className="thinking-step__detail-pre">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function CollapsibleThinking({ reasoningTrace = [], toolCallLog = [], defaultExpanded = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const steps = reasoningTrace.length > 0 ? reasoningTrace : []
  if (steps.length === 0 && toolCallLog.length === 0) return null

  const totalSteps = steps.length
  const toolCount = steps.filter(s => s.type === 'tool_call').length

  return (
    <div className="thinking-section">
      <button
        className="thinking-header"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        <span className="thinking-header__icon">{expanded ? '▼' : '▶'}</span>
        <span className="thinking-header__title">
          查看推理过程（{totalSteps} 步{toolCount > 0 ? `，${toolCount} 次工具调用` : ''}）
        </span>
      </button>

      {expanded && (
        <div className="thinking-body">
          <div className="thinking-timeline">
            {steps.map((step, i) => {
              const cfg = STEP_TYPE_CONFIG[step.type] || { label: step.type, color: '#64748b', icon: '•' }
              return (
                <div key={step.step_id || i} className="thinking-step" style={{ '--step-color': cfg.color }}>
                  <div className="thinking-step__marker">{cfg.icon}</div>
                  <div className="thinking-step__content">
                    <div className="thinking-step__header">
                      <span className="thinking-step__type" style={{ color: cfg.color }}>{cfg.label}</span>
                      {step.agent && (
                        <span className="thinking-step__agent">{step.agent}</span>
                      )}
                      {step.details?.duration_ms != null && (
                        <span className="thinking-step__duration">{step.details.duration_ms}ms</span>
                      )}
                    </div>
                    <div className="thinking-step__desc">{step.description}</div>
                    <StepDetail details={step.details} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
