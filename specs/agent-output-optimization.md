# Financial Agent Output Optimization Plan

## Context

The current financial dialogue agent produces plain text responses without transparency into the reasoning process, no visual data representations, and no user feedback mechanism. This plan outlines optimizations to enhance response quality through:

1. **Chain of Thought + Tool Call Visualization** - Display agent thinking process in collapsible sections
2. **Chart Rendering** - Render financial charts (price trends, valuations, etc.) using ECharts
3. **User Feedback** - Add thumbs up/down buttons with Supabase persistence

These improvements will make the agent more transparent, informative, and interactive for financial analysis tasks.

---

## Implementation Overview

### Architecture Decisions

- **Chart Library**: ECharts (excellent financial chart support including candlestick/K-line)
- **Thinking Display**: Collapsible accordion above final answer
- **Feedback Storage**: Supabase database for persistence across sessions
- **Data Flow**: Backend captures reasoning during execution → streams via SSE/WebSocket → frontend renders components

---

## Phase 1: Backend Changes

### 1.1 Extend State Definition

**File**: `graph/state.py`

Add two new fields to `FinancialAgentState`:

```python
reasoning_trace: Annotated[list[dict[str, Any]], _append_list]
visualization_data: Annotated[list[dict[str, Any]], _append_list]
```

**Data Structures**:

```python
# Reasoning step format:
{
    "step_id": "step_001",
    "timestamp": float,
    "type": "intent_detection" | "tool_call" | "data_analysis" | "synthesis",
    "description": str,
    "details": dict  # tool_name, args, result_summary, duration_ms
}

# Visualization data format:
{
    "chart_id": "chart_price_trend_001",
    "type": "line" | "bar" | "candlestick" | "pie",
    "title": str,
    "data": dict,  # ECharts option object
    "metadata": dict  # stock_code, data_source, generated_at
}
```

---

### 1.2 Enhance Agent Return Format

**Files**: All agents in `agents/` directory

Extend return format from:
```python
{"response": str, "tool_calls": list[dict], "error": str|None}
```

To:
```python
{
    "response": str,
    "tool_calls": list[dict],
    "error": str|None,
    "reasoning_steps": list[dict],  # NEW
    "charts": list[dict]            # NEW
}
```

**Implementation Pattern** (example: `agents/stock_diagnosis_agent.py`):

1. Initialize `reasoning_steps = []` at start of `run()` method
2. Before each tool call loop iteration:
   ```python
   reasoning_steps.append({
       "step_id": f"step_{len(reasoning_steps)+1:03d}",
       "timestamp": time.time(),
       "type": "tool_call",
       "description": f"Fetching {tool_name} for {stock_code}",
       "details": {"tool_name": tool_name, "args": tool_args}
   })
   ```
3. After tool execution, append result summary:
   ```python
   reasoning_steps[-1]["details"]["result_summary"] = summarize_result(tool_result)
   reasoning_steps[-1]["details"]["duration_ms"] = duration
   ```
4. Detect chart opportunities when data patterns suggest visualization:
   - Price history → line chart
   - Financial metrics comparison → bar chart
   - Valuation ratios → gauge/pie chart

**Chart Data Generation Example**:
```python
if price_history:
    charts.append({
        "chart_id": f"price_{stock_code}_{int(time.time())}",
        "type": "line",
        "title": f"{stock_name}价格走势",
        "data": {
            "xAxis": {"type": "category", "data": dates},
            "yAxis": {"type": "value"},
            "series": [{
                "name": "收盘价",
                "type": "line",
                "data": prices,
                "smooth": True
            }]
        },
        "metadata": {
            "stock_code": stock_code,
            "data_source": "get_stock_quote"
        }
    })
```

---

### 1.3 Update Workflow Nodes

**File**: `graph/workflow.py`

Modify agent nodes (`stock_diagnosis_node`, `stock_selection_node`, `customer_service_node`) to pass through structured data:

```python
return {
    "agent_responses": {"stock_diagnosis": result.get("response", "")},
    "tool_call_log": tool_log,
    "reasoning_trace": [
        {**step, "agent": "stock_diagnosis"}
        for step in result.get("reasoning_steps", [])
    ],
    "visualization_data": [
        {**chart, "agent": "stock_diagnosis"}
        for chart in result.get("charts", [])
    ],
}
```

Update `merge_node` to preserve structured data:

```python
def merge_node(state: FinancialAgentState) -> dict[str, Any]:
    # Existing text merging logic...
    
    return {
        "final_response": raw,
        "reasoning_trace": state.get("reasoning_trace", []),
        "visualization_data": state.get("visualization_data", []),
    }
```

---

### 1.4 Extend API Schemas

**File**: `api/schemas.py`

Add new Pydantic models:

```python
class ReasoningStep(BaseModel):
    step_id: str
    timestamp: float
    type: str
    description: str
    details: dict

class ChartData(BaseModel):
    chart_id: str
    type: str
    title: str
    data: dict
    metadata: dict | None = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    scene: str
    latency_ms: float
    degraded: bool = False
    error: str | None = None
    # NEW FIELDS:
    reasoning_trace: list[ReasoningStep] = []
    visualization_data: list[ChartData] = []
    tool_call_log: list[dict] = []

class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int  # 1 = thumbs down, 2 = thumbs up
    comment: str | None = None
    timestamp: float | None = None
```

---

### 1.5 Enhance SSE Streaming

**File**: `api/routes/chat.py`

Extend `chat_stream` endpoint's `event_generator()` to emit new event types:

```python
async for event in graph.astream_events(state, version="v2"):
    event_type = event.get("event", "")
    
    # NEW: Capture tool call events
    if event_type == "on_tool_start":
        yield f"data: {json.dumps({'event': 'tool_call', 'tool_name': event.get('name'), 'status': 'started'})}\n\n"
    
    elif event_type == "on_tool_end":
        yield f"data: {json.dumps({'event': 'tool_call', 'tool_name': event.get('name'), 'status': 'completed'})}\n\n"
    
    # Graph finished
    elif event_type == "on_chain_end" and event.get("name") == "LangGraph":
        output = event.get("data", {}).get("output", {})
        
        # Send reasoning steps
        for step in output.get("reasoning_trace", []):
            yield f"data: {json.dumps({'event': 'reasoning_step', 'step': step})}\n\n"
        
        # Send chart data
        for chart in output.get("visualization_data", []):
            yield f"data: {json.dumps({'event': 'chart_data', 'chart': chart})}\n\n"
        
        # Extended done payload
        done_payload = json.dumps({
            "done": True,
            "session_id": session_id,
            "scene": scene,
            "reasoning_trace": output.get("reasoning_trace", []),
            "visualization_data": output.get("visualization_data", []),
            "tool_call_log": output.get("tool_call_log", []),
        })
        yield f"data: {done_payload}\n\n"
```

Update REST endpoint similarly to include new fields in `ChatResponse`.

---

### 1.6 Create Feedback Endpoint

**File**: `api/routes/feedback.py` (NEW)

```python
from fastapi import APIRouter, HTTPException
from api.schemas import FeedbackRequest
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict:
    """Submit user feedback for a message."""
    try:
        from services.feedback_service import store_feedback
        
        feedback_id = await store_feedback(
            message_id=request.message_id,
            session_id=request.session_id,
            rating=request.rating,
            comment=request.comment,
        )
        
        return {"success": True, "feedback_id": feedback_id}
    
    except Exception as exc:
        logger.exception("Failed to store feedback")
        raise HTTPException(status_code=500, detail=str(exc))
```

Register in `api/main.py`:
```python
from api.routes.feedback import router as feedback_router
app.include_router(feedback_router, prefix="/api")
```

---

### 1.7 Implement Feedback Service with Supabase

**File**: `services/feedback_service.py` (NEW)

```python
"""Service layer for feedback persistence via Supabase."""
import os
import logging
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_supabase: Optional[Client] = None

def get_supabase_client() -> Client:
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("Supabase credentials not configured")
        _supabase = create_client(url, key)
    return _supabase

async def store_feedback(
    message_id: str,
    session_id: str,
    rating: int,
    comment: Optional[str] = None,
) -> str:
    """Store feedback in Supabase and return the feedback ID."""
    client = get_supabase_client()
    
    data = {
        "message_id": message_id,
        "session_id": session_id,
        "rating": rating,
        "comment": comment,
    }
    
    response = client.table("user_feedback").insert(data).execute()
    
    if not response.data:
        raise RuntimeError("Failed to insert feedback")
    
    feedback_id = response.data[0]["id"]
    logger.info("Feedback stored: %s (rating=%d)", feedback_id, rating)
    return feedback_id
```

**Database Schema** (run in Supabase SQL editor):

```sql
CREATE TABLE IF NOT EXISTS user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous',
    rating SMALLINT NOT NULL CHECK (rating IN (1, 2)),
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_feedback_session ON user_feedback(session_id);
CREATE INDEX idx_feedback_message ON user_feedback(message_id);
CREATE INDEX idx_feedback_created ON user_feedback(created_at DESC);
```

**Environment Variables** (add to `.env`):
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

---

## Phase 2: Frontend Changes

### 2.1 Install Dependencies

```bash
cd frontend
npm install echarts-for-react echarts
```

---

### 2.2 Create New Components

#### 2.2.1 CollapsibleThinking Component

**File**: `frontend/src/components/CollapsibleThinking.jsx` (NEW)

Props:
- `reasoningTrace`: Array of reasoning step objects
- `toolCallLog`: Array of tool call records
- `defaultExpanded`: Boolean (default: false)

Features:
- Accordion header showing "Show thinking process (N steps)"
- Expandable body with timeline layout
- Color-coded step types (blue=intent, orange=tool, green=analysis, purple=synthesis)
- Icons for each step type
- Expandable details for tool calls showing args/results

---

#### 2.2.2 ChartRenderer Component

**File**: `frontend/src/components/ChartRenderer.jsx` (NEW)

Props:
- `chartData`: ECharts option object
- `title`: Chart title string
- `chartId`: Unique identifier
- `height`: Number (default: 300)

Features:
- Wraps `echarts-for-react` ReactECharts component
- Dark theme configuration matching app design
- Responsive resize handling
- Error boundary for malformed data
- Loading skeleton during initialization

---

#### 2.2.3 FeedbackButtons Component

**File**: `frontend/src/components/FeedbackButtons.jsx` (NEW)

Props:
- `messageId`: String
- `sessionId`: String
- `onFeedbackSubmitted`: Callback function

Features:
- Two buttons: 👍 thumbs up, 👎 thumbs down
- Optimistic UI update (show selection immediately)
- API call to `POST /api/feedback`
- Optional comment textarea after clicking
- Success/error toast notifications
- Disable after submission to prevent duplicates
- ARIA labels for accessibility

---

### 2.3 Modify Existing Components

#### 2.3.1 MessageBubble Enhancement

**File**: `frontend/src/components/MessageBubble.jsx`

Extended message structure:
```javascript
{
  role: 'assistant',
  content: '...',
  degraded: false,
  scene: 'stock_diagnosis',
  id: 'msg_123',
  // NEW FIELDS:
  reasoning_trace: [...],
  visualization_data: [...],
  tool_call_log: [...],
}
```

Integration points:
1. After scene tag → Insert `CollapsibleThinking` if reasoning/tool data exists
2. After content → Render `ChartRenderer` for each chart in `visualization_data`
3. At bottom → Add `FeedbackButtons` for assistant messages

Props update: Accept `sessionId` from parent for feedback functionality.

---

#### 2.3.2 useChat Hook Enhancement

**File**: `frontend/src/hooks/useChat.js`

Changes:
1. Generate stable message IDs (use counter-based approach or UUID)
2. Extend `addMessage` to accept new fields
3. Handle new SSE event types in `_streamSSE`:
   - `reasoning_step`: Append to last assistant message's `reasoning_trace`
   - `chart_data`: Append to `visualization_data`
   - Extended `done` event with complete structured data
4. Add `sendFeedback` function:
   ```javascript
   const sendFeedback = useCallback(async (messageId, rating, comment = null) => {
     const response = await fetch(`${API_BASE}/feedback`, {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({
         message_id: messageId,
         session_id: sessionId,
         rating,
         comment,
       }),
     })
     if (!response.ok) throw new Error(`HTTP ${response.status}`)
     return await response.json()
   }, [sessionId])
   ```
5. Return `sendFeedback` from hook

---

#### 2.3.3 ChatInterface Minor Update

**File**: `frontend/src/components/ChatInterface.jsx`

Pass `sessionId` to `MessageBubble`:
```jsx
{messages.map(msg => (
  <MessageBubble 
    key={msg.id} 
    message={msg} 
    sessionId={sessionId}
  />
))}
```

---

### 2.4 CSS Updates

**File**: `frontend/src/styles/main.css`

Add three new style sections:

1. **Collapsible Thinking Styles** (~80 lines)
   - `.thinking-section`, `.thinking-header`, `.thinking-body`
   - `.thinking-timeline`, `.thinking-step` with color-coded borders
   - Smooth expand/collapse transitions

2. **Chart Container Styles** (~30 lines)
   - `.bubble__charts` for vertical stacking
   - `.chart-container` with dark theme background
   - Loading and error states

3. **Feedback Button Styles** (~60 lines)
   - `.feedback-buttons` container
   - `.feedback-btn` with hover/selected states
   - `.feedback-comment__textarea` for optional comments
   - Follow existing design system patterns (colors, border-radius, transitions)

Total CSS additions: ~170 lines

---

## Phase 3: Integration & Testing

### 3.1 End-to-End Validation

**Test Scenarios**:

1. **Basic Chat**: Verify reasoning trace appears in collapsible section
2. **Stock Diagnosis with Charts**: Query "分析贵州茅台的走势" → verify line chart renders
3. **Multi-Intent Parallel**: Combine diagnosis + selection → verify merged reasoning traces
4. **Feedback Submission**: Click thumbs up → verify API call succeeds → check Supabase

---

### 3.2 Chart Rendering Testing

**Validation Checklist**:
- Charts respect dark theme colors
- Tooltips display correctly on hover
- Responsive resizing works on window resize
- No JavaScript errors in browser console
- Multiple charts stack vertically without overlap
- Chart data matches backend source

---

### 3.3 Feedback System Testing

**Database Verification**:
```python
# Test script
import asyncio
from services.feedback_service import store_feedback, get_feedback_stats

async def test():
    fb_id = await store_feedback("test_msg_001", "test_sess_001", 2, "Great!")
    print(f"Feedback ID: {fb_id}")
    
    stats = await get_feedback_stats("test_sess_001")
    print(f"Stats: {stats}")
```

**Edge Cases**:
- Network failure → Show error toast, allow retry
- Invalid message ID → Graceful error handling
- Supabase downtime → Show "temporarily unavailable" message

---

### 3.4 Error Handling

**Backend**:
- Validate chart structure before sending → skip invalid charts
- Limit reasoning trace size (max 50 steps) → truncate oldest if exceeded
- Catch Supabase exceptions → return 503 with retry-after header

**Frontend**:
- Wrap ECharts in ErrorBoundary → show "Chart unavailable" fallback
- Detect incomplete SSE stream → show partial data received
- Virtualize long reasoning traces (>100 steps) for performance

---

## Potential Pitfalls & Mitigations

### Pitfall 1: State Bloat
**Problem**: Long conversations accumulate large reasoning traces, slowing LangGraph.

**Mitigation**: Keep only last N steps per agent, compress old steps to summaries, add config flag to disable tracing in production.

---

### Pitfall 2: Chart Data Size
**Problem**: Large datasets (1000+ points) bloat SSE payloads.

**Mitigation**: Downsample on backend (daily vs minute-level), implement pagination, consider binary encoding (MessagePack) if needed.

---

### Pitfall 3: Race Conditions
**Problem**: Parallel agent execution causes interleaved reasoning traces.

**Mitigation**: Tag each step with agent name + sequence number, sort by timestamp+sequence, use separate arrays per agent.

---

### Pitfall 4: Supabase Rate Limiting
**Problem**: High traffic hits rate limits.

**Mitigation**: Client-side debouncing (prevent double-clicks), batch submissions, add Redis caching layer.

---

### Pitfall 5: ECharts Memory Leaks
**Problem**: Component unmounts without disposing chart instances.

**Mitigation**: Use `echarts-for-react` which handles disposal automatically, monitor browser memory usage.

---

## Critical Files Summary

### Backend (Python)
- `graph/state.py` - Extend state with reasoning_trace and visualization_data
- `agents/stock_diagnosis_agent.py` - Primary agent to modify (pattern for others)
- `graph/workflow.py` - Update nodes to pass through structured data
- `api/schemas.py` - Add new Pydantic models
- `api/routes/chat.py` - Extend SSE streaming with new event types
- `api/routes/feedback.py` - NEW feedback endpoint
- `services/feedback_service.py` - NEW Supabase integration

### Frontend (React)
- `frontend/src/components/CollapsibleThinking.jsx` - NEW accordion component
- `frontend/src/components/ChartRenderer.jsx` - NEW ECharts wrapper
- `frontend/src/components/FeedbackButtons.jsx` - NEW thumbs up/down
- `frontend/src/components/MessageBubble.jsx` - Integrate new components
- `frontend/src/hooks/useChat.js` - Handle new events, add sendFeedback
- `frontend/src/styles/main.css` - Add ~170 lines of new styles

### Infrastructure
- Supabase table: `user_feedback` (SQL schema provided)
- Environment variables: `SUPABASE_URL`, `SUPABASE_KEY`
- npm packages: `echarts-for-react`, `echarts`

---

## Verification Steps

After implementation, verify end-to-end:

1. **Start backend**: `python main.py`
2. **Start frontend**: `cd frontend && npm run dev`
3. **Open browser**: Navigate to localhost
4. **Test query**: "分析贵州茅台的走势"
5. **Verify**:
   - Collapsible "Show thinking process" section appears
   - Expand to see intent detection → tool calls → analysis steps
   - Line chart renders below text with price trend
   - Thumbs up/down buttons appear at bottom
   - Click thumbs up → verify optimistic UI update
   - Check Supabase dashboard → confirm feedback row inserted
6. **Check browser console**: No errors
7. **Test edge cases**: Network disconnect, invalid stock code, rapid clicks

---

## Success Criteria

- ✅ Thinking process visible in collapsible accordion for all non-trivial queries
- ✅ Financial charts render correctly with real data from tools
- ✅ User feedback submits successfully to Supabase
- ✅ No regressions in existing chat functionality
- ✅ Performance acceptable (<2s response time for typical queries)
- ✅ No memory leaks or crashes during extended use
