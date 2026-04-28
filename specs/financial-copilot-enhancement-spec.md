# Financial Copilot Enhancement Specification

## Context

This enhancement addresses three critical improvements to the financial dialogue agent system:

1. **Web Frontend Addition**: Transform the CLI-only interface into a production-ready web application with real-time chat capabilities
2. **Multi-Provider LLM Support**: Add OpenAI and Qwen model support alongside existing Anthropic Claude, with intelligent fallback strategy
3. **Unified Exception Handling**: Implement a decorator-based exception capture system with three-tier degradation (complete failure → partial functionality → fallback answer)

These changes will significantly improve user experience, system reliability, and operational flexibility while maintaining the existing LangGraph architecture and risk control mechanisms.

---

## Requirements

### 1. Web Frontend Module

**Goal**: Build a FastAPI backend with modern frontend that allows users to interact with the agent through a web-based question input interface.

**Functional Requirements**:
- REST API endpoint for single-turn queries (`POST /api/chat`)
- Server-Sent Events (SSE) streaming endpoint for real-time responses (`POST /api/chat/stream`)
- WebSocket support for bidirectional real-time chat (`WS /ws/chat`)
- Session management with UUID-based session tracking
- Conversation history display in UI
- Metrics dashboard accessible via `/api/metrics`
- CORS support for cross-origin requests
- Input validation and sanitization

**Technical Stack**:
- Backend: FastAPI + Uvicorn
- Frontend: React or Vue.js (modern SPA)
- Real-time: WebSocket + SSE
- State Management: Maintain existing LangGraph state machine
- Session Storage: Leverage existing `storage/session.py` abstraction

**UI Components**:
- Chat interface with message bubbles (user/assistant)
- Question input bar with send button
- Loading indicator during agent processing
- Error state display with retry option
- Session ID display
- Metrics panel (optional, collapsible)

### 2. Multi-Provider LLM Support

**Goal**: Enable seamless switching between Anthropic Claude, OpenAI GPT, and Alibaba Qwen models with automatic fallback when primary provider fails.

**Functional Requirements**:
- Configuration-driven provider selection via environment variables
- Per-agent model configuration (router, analysis, chat tiers)
- Automatic fallback: Claude → OpenAI → Qwen on failure
- Provider-specific API key management
- Model parameter mapping (temperature, max_tokens, etc.)
- Backward compatibility with existing Claude-only deployment

**Supported Providers**:
- **Anthropic Claude** (existing): claude-haiku, claude-sonnet
- **OpenAI GPT** (new): gpt-4o-mini, gpt-4o, gpt-3.5-turbo
- **Alibaba Qwen** (new): qwen-turbo, qwen-max, qwen-plus

**Implementation Approach**:
- Create centralized LLM factory (`config/llm_factory.py`)
- Abstract provider selection logic from agents
- Update all 5 agents to use factory pattern
- Add provider health checks and fallback routing

### 3. Unified Exception Capture Decorator

**Goal**: Implement a decorator-based exception handling system applied across all agent nodes with three-tier degradation strategy.

**Degradation Tiers**:

**Tier 1 - Complete Failure** (error_flag=True, safe fallback):
- Triggers: LLM API unavailable, critical data pipeline failure, security violation
- Action: Set `error_flag=True`, return generic fallback message, log with `logger.error()`, increment `metrics.error()`
- Response: "抱歉，系统暂时无法处理您的请求，请稍后再试。如需帮助，请联系客服热线。"

**Tier 2 - Partial Functionality** (degraded mode):
- Triggers: Some tools fail but others succeed, circuit breaker open for specific tools, rate limit exceeded
- Action: Continue with available data, mark response as "degraded", log with `logger.warning()`, return partial results with disclaimer
- Response: Include note like "（部分数据暂时不可用，基于可用信息回答）"

**Tier 3 - Fallback Answer** (graceful degradation):
- Triggers: Non-critical tool failures, timeout on secondary data sources, JSON parse errors in optional fields
- Action: Use cached/default values, log with `logger.info()`, continue execution normally
- Response: Transparent to user, uses default values silently

**Decorator Features**:
- Automatic error_flag setting in workflow state
- Integration with existing circuit breaker (`tools/gateway.py`)
- Metrics integration (`metrics.error()`, `metrics.tool_called()`)
- Tracer span annotation for failed operations
- Optional retry logic with exponential backoff
- Timeout enforcement
- Context-aware fallback selection based on scene type
- Preserve original exception for debugging

**Application Scope**:
- All 5 agent `.run()` methods
- All 5 workflow node functions in `graph/workflow.py`
- LLM invoke calls within agents
- Tool execution methods (replace manual try-except blocks)

---

## Implementation Plan

### Phase 1: Web Frontend Module

#### Step 1.1: Backend API Setup

**Files to Create**:
- `api/main.py` - FastAPI application entry point
- `api/routes/chat.py` - Chat endpoints (single-turn, streaming)
- `api/routes/metrics.py` - Metrics endpoint
- `api/websocket.py` - WebSocket handler for real-time chat
- `api/schemas.py` - Pydantic request/response models
- `api/middleware.py` - CORS, authentication middleware

**Files to Modify**:
- `requirements.txt` - Add FastAPI, uvicorn, websockets dependencies
- `.env.example` - Add CORS_ORIGINS, API_KEY configuration

**Key Implementation Details**:
```python
# api/schemas.py
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "anonymous"

class ChatResponse(BaseModel):
    response: str
    session_id: str
    scene: str
    latency_ms: float

# api/routes/chat.py
@router.post("/chat")
async def chat(request: ChatRequest):
    # Convert to FinancialAgentState
    # Invoke graph.ainvoke() (async version)
    # Return structured response
```

#### Step 1.2: Async Graph Conversion

**Files to Modify**:
- `graph/workflow.py` - Ensure all nodes support async execution
- `agents/*.py` - Convert agent `.run()` methods to async where needed
- `main.py` - Keep synchronous version for CLI, add async wrapper for API

**Key Changes**:
- Replace `graph.invoke()` with `graph.ainvoke()` in API layer
- Use LangGraph's `.astream_events()` for SSE streaming
- Ensure thread safety for shared singletons (_router, _stock_diagnosis, etc.)

#### Step 1.3: Streaming Implementation

**Endpoint**: `POST /api/chat/stream`

**Implementation**:
```python
from fastapi.responses import StreamingResponse

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def event_generator():
        async for event in graph.astream_events(state, version="v2"):
            if event["event"] == "on_chat_model_stream":
                yield f"data: {json.dumps({'token': event['data']['chunk'].content})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

#### Step 1.4: Frontend Development

**Files to Create**:
- `frontend/package.json` - Node.js dependencies
- `frontend/src/App.jsx` (or `.vue`) - Main application component
- `frontend/src/components/ChatInterface.jsx` - Chat UI component
- `frontend/src/components/MessageBubble.jsx` - Individual message display
- `frontend/src/components/InputBar.jsx` - Question input with send button
- `frontend/src/hooks/useChat.js` - Custom hook for API communication
- `frontend/src/styles/main.css` - Styling
- `frontend/public/index.html` - HTML template

**Tech Stack Options**:
- **React**: Vite + React 18 + Axios + TailwindCSS
- **Vue**: Vite + Vue 3 + Pinia + Element Plus

**Key Features**:
- Real-time message updates via WebSocket or polling
- Auto-scroll to latest message
- Typing indicator during processing
- Error handling with retry button
- Session persistence in localStorage
- Responsive design (mobile-friendly)

#### Step 1.5: Integration & Testing

**Testing Checklist**:
- [ ] Single-turn query works via REST API
- [ ] Streaming responses render progressively in UI
- [ ] WebSocket maintains connection across multiple messages
- [ ] Session ID persists across page refreshes
- [ ] Error states display correctly
- [ ] Metrics endpoint returns valid JSON
- [ ] CORS allows frontend-backend communication
- [ ] Concurrent sessions work independently

---

### Phase 2: Multi-Provider LLM Support

#### Step 2.1: Configuration Updates

**Files to Modify**:
- `config/settings.py` - Add provider configuration
- `.env` - Add new API keys and model names
- `.env.example` - Document new configuration options

**Configuration Schema**:
```python
# config/settings.py
class Settings(BaseSettings):
    # Provider selection
    llm_provider_primary: str = "anthropic"  # anthropic | openai | qwen
    llm_fallback_enabled: bool = True
    
    # API Keys
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    
    # Model tiers per provider
    router_model_anthropic: str = "claude-haiku-4-5-20251001"
    router_model_openai: str = "gpt-4o-mini"
    router_model_qwen: str = "qwen-turbo"
    
    analysis_model_anthropic: str = "claude-sonnet-4-6"
    analysis_model_openai: str = "gpt-4o"
    analysis_model_qwen: str = "qwen-max"
    
    chat_model_anthropic: str = "claude-haiku-4-5-20251001"
    chat_model_openai: str = "gpt-4o-mini"
    chat_model_qwen: str = "qwen-turbo"
```

#### Step 2.2: LLM Factory Implementation

**File to Create**: `config/llm_factory.py`

**Implementation**:
```python
from typing import Literal
from langchain_core.language_models import BaseChatModel
from config.settings import settings

ProviderType = Literal["anthropic", "openai", "qwen"]
ModelTier = Literal["router", "analysis", "chat"]

def create_llm(
    tier: ModelTier = "analysis",
    provider: ProviderType | None = None,
    temperature: float | None = None,
    bind_tools: list | None = None,
) -> BaseChatModel:
    """
    Factory to create LLM instances with automatic fallback.
    
    Args:
        tier: Model complexity tier (router/analysis/chat)
        provider: Specific provider to use (None = use primary)
        temperature: Override default temperature
        bind_tools: Optional list of tools to bind
    
    Returns:
        Configured LangChain chat model instance
    """
    # Determine provider (primary or fallback chain)
    providers_to_try = [provider] if provider else _get_provider_chain()
    
    last_exception = None
    for prov in providers_to_try:
        try:
            llm = _create_llm_for_provider(prov, tier, temperature)
            
            # Bind tools if requested
            if bind_tools:
                llm = llm.bind_tools(bind_tools)
            
            return llm
        
        except Exception as exc:
            logger.warning(f"Failed to create LLM with {prov}: {exc}")
            last_exception = exc
            continue
    
    # All providers failed
    raise RuntimeError(f"All LLM providers failed. Last error: {last_exception}")


def _get_provider_chain() -> list[ProviderType]:
    """Get ordered list of providers to try."""
    primary = settings.llm_provider_primary
    if not settings.llm_fallback_enabled:
        return [primary]
    
    all_providers = ["anthropic", "openai", "qwen"]
    chain = [primary]
    chain.extend([p for p in all_providers if p != primary])
    return chain


def _create_llm_for_provider(
    provider: ProviderType,
    tier: ModelTier,
    temperature: float | None,
) -> BaseChatModel:
    """Create LLM instance for specific provider."""
    model_name = _get_model_name(provider, tier)
    temp = temperature if temperature is not None else _get_temperature(tier)
    
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            temperature=temp,
            api_key=settings.anthropic_api_key,
        )
    
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temp,
            api_key=settings.openai_api_key,
        )
    
    elif provider == "qwen":
        from langchain_community.chat_models import ChatTongyi
        return ChatTongyi(
            model=model_name,
            temperature=temp,
            dashscope_api_key=settings.qwen_api_key,
        )
    
    else:
        raise ValueError(f"Unsupported provider: {provider}")
```

#### Step 2.3: Agent Refactoring

**Files to Modify**:
- `agents/router_agent.py`
- `agents/stock_diagnosis_agent.py`
- `agents/stock_selection_agent.py`
- `agents/customer_service_agent.py`
- `agents/chat_agent.py`

**Refactoring Pattern** (example for stock_diagnosis_agent):
```python
# Before:
from langchain_anthropic import ChatAnthropic

class StockDiagnosisAgent:
    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.analysis_model,
            temperature=settings.analysis_temperature,
            api_key=settings.anthropic_api_key,
        ).bind_tools(FINANCIAL_TOOLS)

# After:
from config.llm_factory import create_llm

class StockDiagnosisAgent:
    def __init__(self) -> None:
        self._llm = create_llm(
            tier="analysis",
            bind_tools=FINANCIAL_TOOLS,
        )
```

**Changes per Agent**:
- Remove direct `ChatAnthropic` import and instantiation
- Import `create_llm` from factory
- Replace `__init__` LLM creation with factory call
- Pass appropriate tier ("router", "analysis", or "chat")
- Keep `.bind_tools()` for tool-using agents

#### Step 2.4: Dependency Updates

**File to Modify**: `requirements.txt`

**Additions**:
```txt
langchain-openai>=0.1.1          # Already installed, verify version
langchain-community>=0.0.36      # For Qwen/DashScope
dashscope>=1.14.0                # Qwen SDK
```

#### Step 2.5: Testing & Validation

**Testing Checklist**:
- [ ] Claude models work with existing API key
- [ ] OpenAI models work with test API key
- [ ] Qwen models work with DashScope API key
- [ ] Primary provider failure triggers fallback
- [ ] All 5 agents function with each provider
- [ ] Tool binding works across providers
- [ ] Temperature settings apply correctly
- [ ] Model tier selection works (router vs analysis vs chat)

---

### Phase 3: Unified Exception Capture Decorator

#### Step 3.1: Decorator Implementation

**File to Create**: `utils/exception_handler.py`

**Implementation**:
```python
import functools
import time
import logging
from typing import Any, Callable
from observability.metrics import metrics
from observability.tracer import tracer

logger = logging.getLogger(__name__)

DegradationTier = Literal["complete", "partial", "fallback"]

def handle_exceptions(
    tier: DegradationTier = "partial",
    fallback_value: Any = None,
    log_level: str = "warning",
    metrics_key: str | None = None,
    retry_count: int = 0,
    timeout_seconds: int | None = None,
    scene_context: str | None = None,
):
    """
    Unified exception handler with three-tier degradation strategy.
    
    Args:
        tier: Degradation level (complete/partial/fallback)
        fallback_value: Value to return on complete failure
        log_level: Logging level for exceptions
        metrics_key: Key for metrics tracking
        retry_count: Number of retries before giving up
        timeout_seconds: Execution timeout in seconds
        scene_context: Current scene for context-aware fallbacks
    
    Usage:
        @handle_exceptions(
            tier="complete",
            fallback_value={"response": "...", "error": "..."},
            metrics_key="agent.stock_diagnosis"
        )
        def stock_diagnosis_node(state):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Extract state if present (for workflow nodes)
            state = kwargs.get("state") or (args[0] if args else None)
            session_id = state.get("session_id") if isinstance(state, dict) else None
            
            start_time = time.time()
            attempts = 0
            last_exception = None
            
            while attempts <= retry_count:
                try:
                    # Execute with optional timeout
                    if timeout_seconds:
                        result = _execute_with_timeout(func, args, kwargs, timeout_seconds)
                    else:
                        result = func(*args, **kwargs)
                    
                    # Record success metrics
                    latency_ms = (time.time() - start_time) * 1000
                    if metrics_key:
                        metrics.record_latency(metrics_key, latency_ms)
                    
                    # Log success after retries
                    if attempts > 0:
                        logger.info(f"{func.__name__} succeeded after {attempts} retries")
                    
                    return result
                
                except Exception as exc:
                    attempts += 1
                    last_exception = exc
                    
                    # Log exception
                    log_func = getattr(logger, log_level, logger.warning)
                    log_func(f"{func.__name__} failed (attempt {attempts}): {exc}", exc_info=True)
                    
                    # Record error metrics
                    if metrics_key:
                        metrics.error(metrics_key)
                    
                    # Trace error event
                    if session_id:
                        tracer.log_error_event(session_id, func.__name__, str(exc))
                    
                    # Don't retry if tier is "complete" (immediate fallback)
                    if tier == "complete" or attempts > retry_count:
                        break
            
            # All attempts exhausted - apply degradation strategy
            return _apply_degradation(
                func, exc=last_exception, tier=tier,
                fallback_value=fallback_value, state=state,
                scene_context=scene_context
            )
        
        return wrapper
    return decorator


def _execute_with_timeout(func, args, kwargs, timeout_seconds):
    """Execute function with timeout using signal alarm."""
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Function {func.__name__} timed out after {timeout_seconds}s")
    
    # Set timeout
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        result = func(*args, **kwargs)
    finally:
        signal.alarm(0)  # Cancel alarm
        signal.signal(signal.SIGALRM, old_handler)
    
    return result


def _apply_degradation(func, exc, tier, fallback_value, state, scene_context):
    """Apply tiered degradation strategy."""
    
    if tier == "complete":
        # Tier 1: Complete failure - set error_flag and return safe fallback
        logger.error(f"Complete failure in {func.__name__}: {exc}")
        
        fallback_response = fallback_value or _get_scene_fallback(scene_context)
        
        # Update state if available
        if isinstance(state, dict):
            state["error_flag"] = True
            state["error_message"] = str(exc)
            if "final_response" in state:
                state["final_response"] = fallback_response.get("response", "")
        
        return fallback_response
    
    elif tier == "partial":
        # Tier 2: Partial functionality - continue with degraded mode
        logger.warning(f"Partial degradation in {func.__name__}: {exc}")
        
        # Try to extract partial results or use degraded defaults
        degraded_result = {
            "response": _get_degraded_response(scene_context, exc),
            "degraded": True,
            "error": str(exc),
        }
        
        # Merge with fallback_value if provided
        if fallback_value and isinstance(fallback_value, dict):
            degraded_result.update(fallback_value)
        
        return degraded_result
    
    else:  # tier == "fallback"
        # Tier 3: Graceful fallback - use cached/default values
        logger.info(f"Fallback mode in {func.__name__}: {exc}")
        
        # Return silent fallback (transparent to user)
        return fallback_value or {"response": "", "error": None}


def _get_scene_fallback(scene: str | None) -> dict:
    """Get scene-specific fallback response."""
    fallbacks = {
        "stock_diagnosis": {
            "response": "抱歉，个股分析服务暂时不可用。请稍后重试或联系客服。",
            "error": "stock_diagnosis_unavailable",
        },
        "stock_selection": {
            "response": "抱歉，选股服务暂时不可用。请稍后重试或联系客服。",
            "error": "stock_selection_unavailable",
        },
        "customer_service": {
            "response": "抱歉，客服系统暂时无法响应。请拨打客服热线：400-XXX-XXXX",
            "error": "customer_service_unavailable",
        },
        "chat": {
            "response": "抱歉，我暂时无法回答您的问题，请稍后重试。",
            "error": "chat_unavailable",
        },
    }
    return fallbacks.get(scene, fallbacks["chat"])


def _get_degraded_response(scene: str | None, exc: Exception) -> str:
    """Generate degraded mode response with disclaimer."""
    base_responses = {
        "stock_diagnosis": "（部分数据暂时不可用，基于可用信息提供分析）\n\n",
        "stock_selection": "（部分板块数据缺失，仅供参考）\n\n",
        "customer_service": "（知识库检索受限，以下为通用回答）\n\n",
    }
    
    prefix = base_responses.get(scene, "（系统降级运行中）\n\n")
    return prefix + "由于技术问题，以下回答可能不完整..."
```

#### Step 3.2: Apply to Workflow Nodes

**File to Modify**: `graph/workflow.py`

**Application Pattern**:
```python
from utils.exception_handler import handle_exceptions

@handle_exceptions(
    tier="complete",
    fallback_value={"final_response": "抱歉，系统暂时无法处理您的请求，请稍后再试。"},
    metrics_key="workflow.pre_risk",
)
def pre_risk_node(state: FinancialAgentState) -> dict[str, Any]:
    # Existing implementation unchanged
    ...

@handle_exceptions(
    tier="complete",
    fallback_value={},
    metrics_key="workflow.router",
)
def router_node(state: FinancialAgentState) -> dict[str, Any]:
    # Existing implementation unchanged
    ...

@handle_exceptions(
    tier="partial",
    fallback_value={"agent_responses": {}, "tool_call_log": []},
    metrics_key="workflow.stock_diagnosis",
    scene_context="stock_diagnosis",
)
def stock_diagnosis_node(state: FinancialAgentState) -> dict[str, Any]:
    # Existing implementation unchanged
    ...

# Apply to all other nodes similarly
```

**Node-by-Node Strategy**:
- `preprocess_node`: No decorator needed (simple state initialization)
- `pre_risk_node`: Tier "complete" (security critical)
- `router_node`: Tier "complete" (routing failure blocks entire flow)
- `dispatch_node`: No decorator (Send logic rarely fails)
- `stock_diagnosis_node`: Tier "partial" (can work with some tools failing)
- `stock_selection_node`: Tier "partial"
- `customer_service_node`: Tier "partial"
- `chat_node`: Tier "fallback" (casual chat can gracefully degrade)
- `merge_node`: Tier "fallback" (can merge partial responses)
- `post_risk_node`: Tier "complete" (compliance critical)
- `persist_node`: Tier "fallback" (persistence failure shouldn't block response)
- `error_handler_node`: No decorator (already handles errors)

#### Step 3.3: Apply to Agent Methods

**Files to Modify**: All 5 agent files

**Application Pattern** (stock_diagnosis_agent example):
```python
from utils.exception_handler import handle_exceptions

class StockDiagnosisAgent:
    @handle_exceptions(
        tier="partial",
        fallback_value={"response": "", "tool_calls": [], "error": "LLM invocation failed"},
        metrics_key="agent.stock_diagnosis.run",
        retry_count=2,
        timeout_seconds=30,
    )
    def run(
        self,
        user_text: str,
        stock_codes: list[str],
        dialog_history: list[dict],
        tool_call_log: list[dict],
    ) -> dict[str, Any]:
        # Existing implementation unchanged
        ...
    
    @handle_exceptions(
        tier="fallback",
        fallback_value={"error": "Tool execution failed"},
        metrics_key="agent.stock_diagnosis.tool",
        retry_count=1,
        timeout_seconds=10,
    )
    def _call_tool(self, name: str, args: dict) -> dict:
        # Can remove existing try-except, decorator handles it
        fn = _map.get(name)
        if fn is None:
            return {"error": f"未知工具: {name}"}
        return fn.invoke(args)  # Decorator wraps this
```

**Agent-by-Agent Strategy**:
- **Router Agent**: 
  - `route()`: Tier "complete"
  - `_llm_classify()`: Tier "partial" (already has try-except, replace with decorator)
  
- **Stock Diagnosis Agent**:
  - `run()`: Tier "partial"
  - `_call_tool()`: Tier "fallback" (replace existing try-except)

- **Stock Selection Agent**: Same as diagnosis

- **Customer Service Agent**:
  - `run()`: Tier "partial"
  - `_call_rag_tool()`: Tier "fallback"

- **Chat Agent**:
  - `run()`: Tier "fallback" (replace existing try-except)

#### Step 3.4: Integration with Circuit Breaker

**Enhancement to `utils/exception_handler.py`**:
```python
from tools.gateway import gateway

def _check_circuit_breaker(tool_name: str) -> bool:
    """Check if circuit breaker is open for a tool."""
    if tool_name in gateway.circuit_breakers:
        cb = gateway.circuit_breakers[tool_name]
        return cb.state == "OPEN"
    return False

# In decorator, before executing:
if _check_circuit_breaker(metrics_key):
    logger.warning(f"Circuit breaker open for {metrics_key}, skipping execution")
    return _apply_degradation(..., tier="partial", ...)
```

#### Step 3.5: Testing & Validation

**Testing Checklist**:
- [ ] Decorator catches exceptions in all decorated functions
- [ ] Three tiers produce correct degradation behavior
- [ ] Retry logic works with exponential backoff
- [ ] Timeout enforcement prevents hanging
- [ ] Metrics are recorded for successes and failures
- [ ] Tracer logs error events with session context
- [ ] Circuit breaker integration prevents calls to failed tools
- [ ] State error_flag is set correctly on complete failures
- [ ] Original exceptions are logged for debugging
- [ ] Performance overhead is acceptable (<5% latency increase)

---

## Critical Files to Modify

### Backend (Core Logic)
1. `config/settings.py` - Multi-provider configuration
2. `config/llm_factory.py` - NEW: LLM factory with fallback
3. `utils/exception_handler.py` - NEW: Exception decorator
4. `agents/router_agent.py` - Refactor to use factory + decorator
5. `agents/stock_diagnosis_agent.py` - Refactor to use factory + decorator
6. `agents/stock_selection_agent.py` - Refactor to use factory + decorator
7. `agents/customer_service_agent.py` - Refactor to use factory + decorator
8. `agents/chat_agent.py` - Refactor to use factory + decorator
9. `graph/workflow.py` - Apply decorators to nodes, ensure async support

### API Layer (NEW)
10. `api/main.py` - FastAPI application
11. `api/routes/chat.py` - Chat endpoints
12. `api/routes/metrics.py` - Metrics endpoint
13. `api/websocket.py` - WebSocket handler
14. `api/schemas.py` - Request/response models
15. `api/middleware.py` - CORS and auth middleware

### Frontend (NEW)
16. `frontend/package.json` - Dependencies
17. `frontend/src/App.jsx` - Main app component
18. `frontend/src/components/ChatInterface.jsx` - Chat UI
19. `frontend/src/components/MessageBubble.jsx` - Message display
20. `frontend/src/components/InputBar.jsx` - Input component
21. `frontend/src/hooks/useChat.js` - API communication hook
22. `frontend/src/styles/main.css` - Styling

### Configuration
23. `requirements.txt` - Add FastAPI, langchain-openai, dashscope
24. `.env` - Add new API keys and settings
25. `.env.example` - Document new configuration

---

## Verification & Testing

### End-to-End Testing Scenarios

**Scenario 1: Normal Operation (Claude)**
1. Start FastAPI server: `uvicorn api.main:app --reload`
2. Start frontend dev server: `cd frontend && npm run dev`
3. Open browser to `http://localhost:5173`
4. Type question: "帮我分析一下贵州茅台（600519）的基本面"
5. Verify: Response appears in chat UI with proper formatting
6. Check: Session ID displayed and persists on refresh
7. Verify: Metrics show successful stock_diagnosis scene hit

**Scenario 2: Streaming Response**
1. Use streaming endpoint: `POST /api/chat/stream`
2. Verify: Tokens appear progressively in UI (not all at once)
3. Check: Typing indicator disappears when streaming starts
4. Verify: Complete response matches non-streaming version

**Scenario 3: Claude Failure → OpenAI Fallback**
1. Temporarily invalidate ANTHROPIC_API_KEY in .env
2. Restart server
3. Send same question as Scenario 1
4. Verify: System automatically uses OpenAI (check logs)
5. Check: Response quality is comparable
6. Verify: Metrics show fallback was triggered

**Scenario 4: Partial Tool Failure (Degraded Mode)**
1. Mock one financial tool to raise exception
2. Send stock analysis question requiring that tool
3. Verify: Response includes degradation disclaimer
4. Check: Other tools still executed successfully
5. Verify: Logs show partial degradation warning

**Scenario 5: Complete LLM Failure (Fallback Answer)**
1. Invalidate all provider API keys
2. Send any question
3. Verify: Generic fallback message appears
4. Check: error_flag is set in state
5. Verify: Metrics show complete failure
6. Check: Tracer logs error event with stack trace

**Scenario 6: Concurrent Sessions**
1. Open two browser tabs
2. Send different questions in each
3. Verify: Responses don't mix between sessions
4. Check: Each tab has unique session_id
5. Verify: Both sessions tracked independently in metrics

**Scenario 7: Risk Control Integration**
1. Send question with blocked keyword (e.g., "内幕消息")
2. Verify: Pre-filter blocks request before LLM call
3. Check: Appropriate block message displayed
4. Verify: Metrics show pre_filter risk block

**Scenario 8: WebSocket Real-time Chat**
1. Connect via WebSocket: `ws://localhost:8000/ws/chat`
2. Send multiple messages rapidly
3. Verify: All messages receive responses in order
4. Check: Connection stays alive across idle periods
5. Verify: Reconnection works after network interruption

### Performance Benchmarks

**Metrics to Track**:
- Average response latency (target: <5s for Claude, <3s for OpenAI)
- P99 latency (target: <10s)
- Streaming time-to-first-token (target: <1s)
- Concurrent session capacity (target: 100+ simultaneous users)
- Fallback trigger rate (target: <5% under normal operation)
- Error rate by tier (target: complete <1%, partial <5%)

### Regression Testing

Ensure existing functionality remains intact:
- [ ] CLI mode still works (`python main.py`)
- [ ] Demo mode still works (`python main.py --demo`)
- [ ] All 5 scene types route correctly
- [ ] Risk filters still block违规 content
- [ ] Tool gateway circuit breaker still functions
- [ ] Session persistence works (Redis/MongoDB if configured)
- [ ] Metrics collection accurate
- [ ] Structured logging outputs correct format

---

## Risks & Mitigations

### Risk 1: Breaking Existing Deployments
**Mitigation**: 
- Keep backward compatibility with Claude-only configuration
- Default `llm_provider_primary` to "anthropic"
- Make new dependencies optional (use try-import patterns)

### Risk 2: Increased Complexity
**Mitigation**:
- Comprehensive documentation in code comments
- Clear separation between old and new code paths
- Gradual rollout: deploy decorator to non-critical agents first

### Risk 3: Performance Overhead from Decorator
**Mitigation**:
- Benchmark before/after decorator application
- Use lightweight checks (avoid heavy serialization in hot path)
- Make retry/timeout optional (disabled by default for low-latency paths)

### Risk 4: Frontend Maintenance Burden
**Mitigation**:
- Use established frameworks (React/Vue) with large communities
- Keep frontend minimal (chat interface only, no complex features)
- Provide Docker container for easy deployment

### Risk 5: API Key Security
**Mitigation**:
- Never commit .env to version control
- Use environment variable injection in production
- Consider secrets manager (AWS Secrets Manager, HashiCorp Vault) for production
- Add API key rotation mechanism

---

## Success Criteria

### Functional Success
- ✅ Web UI allows users to ask questions and receive agent responses
- ✅ System seamlessly switches between Claude/OpenAI/Qwen based on availability
- ✅ Exceptions are caught and handled according to three-tier strategy
- ✅ No unhandled exceptions crash the system in production

### Performance Success
- ✅ Web response latency within 20% of CLI latency
- ✅ Streaming reduces perceived wait time by >50%
- ✅ System handles 50+ concurrent users without degradation
- ✅ Fallback triggers add <500ms overhead

### Reliability Success
- ✅ Zero downtime during provider failures (automatic fallback)
- ✅ 99.9% uptime for web interface
- ✅ All errors logged with sufficient context for debugging
- ✅ User-facing error messages are helpful and actionable

### Code Quality Success
- ✅ All new code follows existing project patterns
- ✅ Type hints used throughout (mypy clean)
- ✅ Docstrings for all public functions
- ✅ No duplicate code (DRY principle maintained)
- ✅ Test coverage >80% for new modules

---

## Timeline Estimate

**Phase 1 (Web Frontend)**: 5-7 days
- Backend API: 2 days
- Async conversion: 1 day
- Streaming: 1 day
- Frontend UI: 2-3 days

**Phase 2 (Multi-Provider LLM)**: 3-4 days
- Configuration & factory: 1 day
- Agent refactoring: 1 day
- Testing & validation: 1-2 days

**Phase 3 (Exception Decorator)**: 3-4 days
- Decorator implementation: 1 day
- Application to nodes/agents: 1 day
- Circuit breaker integration: 0.5 days
- Testing & benchmarking: 1-1.5 days

**Total**: 11-15 days (sequential) or 8-10 days (parallel teams)

---

## Next Steps

1. **Review this spec** with stakeholders for approval
2. **Set up development environment** with all required dependencies
3. **Start with Phase 1** (web frontend) as it's most visible to users
4. **Implement incrementally** with feature flags for gradual rollout
5. **Deploy to staging** environment for integration testing
6. **Run full regression suite** before production deployment
7. **Monitor metrics** closely during first week of production
8. **Gather user feedback** and iterate on UI/UX improvements
