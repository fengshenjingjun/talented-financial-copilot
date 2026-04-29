import React, { useState, useCallback } from 'react'

export default function FeedbackButtons({ messageId, sessionId, onFeedbackSubmitted }) {
  const [rating, setRating] = useState(null)       // null | 1 | 2
  const [submitted, setSubmitted] = useState(false)
  const [showComment, setShowComment] = useState(false)
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(false)
  const [toast, setToast] = useState(null)

  const showToast = useCallback((msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2500)
  }, [])

  async function submitFeedback(selectedRating, finalComment = '') {
    if (loading || submitted) return
    setLoading(true)
    setRating(selectedRating)

    try {
      const resp = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message_id: messageId,
          session_id: sessionId,
          rating: selectedRating,
          comment: finalComment || null,
          timestamp: Date.now() / 1000,
        }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setSubmitted(true)
      setShowComment(false)
      showToast('感谢您的反馈！')
      onFeedbackSubmitted?.({ messageId, rating: selectedRating, comment: finalComment })
    } catch (err) {
      showToast('反馈提交失败，请稍后重试', 'error')
      setRating(null)
    } finally {
      setLoading(false)
    }
  }

  function handleThumb(value) {
    if (submitted || loading) return
    setRating(value)
    setShowComment(true)
  }

  return (
    <div className="feedback-buttons">
      <div className="feedback-buttons__row">
        <span className="feedback-buttons__label">这个回答有帮助吗？</span>
        <button
          className={`feedback-btn feedback-btn--up ${rating === 2 ? 'feedback-btn--selected' : ''}`}
          onClick={() => handleThumb(2)}
          disabled={submitted || loading}
          aria-label="有帮助"
          title="有帮助"
        >
          👍
        </button>
        <button
          className={`feedback-btn feedback-btn--down ${rating === 1 ? 'feedback-btn--selected' : ''}`}
          onClick={() => handleThumb(1)}
          disabled={submitted || loading}
          aria-label="没有帮助"
          title="没有帮助"
        >
          👎
        </button>
        {submitted && <span className="feedback-buttons__thanks">已记录</span>}
      </div>

      {showComment && !submitted && (
        <div className="feedback-comment">
          <textarea
            className="feedback-comment__textarea"
            placeholder="可选：补充说明（Enter 提交，Esc 跳过）"
            value={comment}
            onChange={e => setComment(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitFeedback(rating, comment) }
              if (e.key === 'Escape') submitFeedback(rating, '')
            }}
            rows={2}
            autoFocus
          />
          <div className="feedback-comment__actions">
            <button className="feedback-comment__submit" onClick={() => submitFeedback(rating, comment)} disabled={loading}>
              {loading ? '提交中…' : '提交'}
            </button>
            <button className="feedback-comment__skip" onClick={() => submitFeedback(rating, '')} disabled={loading}>
              跳过
            </button>
          </div>
        </div>
      )}

      {toast && (
        <div className={`feedback-toast feedback-toast--${toast.type}`}>{toast.msg}</div>
      )}
    </div>
  )
}
