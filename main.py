#!/usr/bin/env python3
"""
金融多Agent对话系统 — 交互式入口
用法：python main.py          # 交互模式
      python main.py --demo  # 自动演示模式（运行预设5个问题）
"""
from __future__ import annotations

import sys
import uuid
import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)  # suppress verbose lib logs

from langchain_core.messages import HumanMessage

from graph.workflow import build_graph
from graph.state import FinancialAgentState
from observability.metrics import metrics

# ── Banner ─────────────────────────────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════╗
║      金融智能对话系统  v1.0  (对标问财 / 妙想)        ║
║  架构：路由Agent + 诊股/选股/客服/闲聊 Sub-Agent      ║
║  编排：LangGraph  |  防幻觉：强工具锁  |  双轨风控    ║
║  输入 /quit 退出  |  /metrics 查看指标                ║
╚══════════════════════════════════════════════════════╝
"""

DEMO_QUESTIONS = [
    "你好，你能做什么？",
    "帮我分析一下贵州茅台（600519）的基本面",
    "白酒板块今天表现怎么样？",
    "开户需要什么条件？佣金怎么收？",
    "茅台和白酒行业整体对比如何？",  # multi-intent: triggers parallel agents
]


def run_turn(
    graph,
    session_id: str,
    user_id: str,
    user_input: str,
    current_state: dict,
) -> tuple[str, dict]:
    """Execute one conversation turn and return (response, updated_state)."""

    # Build state for this turn
    state: FinancialAgentState = {
        "session_id": session_id,
        "user_id": user_id,
        "messages": current_state.get("messages", []) + [HumanMessage(content=user_input)],
        "current_scene": current_state.get("current_scene", "unknown"),
        "scene_history": current_state.get("scene_history", []),
        "detected_intents": [],
        "temp_params": {},
        "user_context": current_state.get("user_context", {}),
        "tool_call_log": [],
        "risk_check_result": {},
        "error_flag": False,
        "error_message": "",
        "agent_responses": {},
        "final_response": "",
    }

    result = graph.invoke(state)

    # Persist messages for next turn (keep last 10 pairs to avoid context bloat)
    updated_messages = list(result.get("messages", []))[-20:]

    updated_state = {
        "messages": updated_messages,
        "current_scene": result.get("current_scene", "unknown"),
        "scene_history": list(result.get("scene_history", [])),
        "user_context": result.get("user_context", {}),
    }

    return result.get("final_response", ""), updated_state


def main() -> None:
    print(BANNER)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("⚠️  未检测到 ANTHROPIC_API_KEY 环境变量。")
        print("    请先执行: export ANTHROPIC_API_KEY=sk-ant-...\n")
        sys.exit(1)

    print("正在初始化 LangGraph 工作流...", end=" ", flush=True)
    graph = build_graph()
    print("完成\n")

    session_id = str(uuid.uuid4())
    user_id = "user_demo"
    current_state: dict = {}

    # ── Demo mode ──────────────────────────────────────────────────────────────
    demo_arg = "--demo" in sys.argv
    if demo_arg:
        print("=== 自动演示模式（预设问题） ===\n")
        for q in DEMO_QUESTIONS:
            print(f"👤 用户: {q}")
            response, current_state = run_turn(graph, session_id, user_id, q, current_state)
            print(f"🤖 助手:\n{response}\n")
            print("-" * 60)
        print("\n=== 演示完成，进入交互模式 ===\n")

    # ── Interactive loop ───────────────────────────────────────────────────────
    print("请输入您的问题（/quit 退出，/metrics 指标，/demo 演示问题）：\n")
    while True:
        try:
            user_input = input("👤 您: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("再见！")
            break

        if user_input == "/metrics":
            import json
            print(json.dumps(metrics.report(), ensure_ascii=False, indent=2))
            continue

        if user_input == "/demo":
            for q in DEMO_QUESTIONS:
                print(f"\n👤 用户: {q}")
                response, current_state = run_turn(graph, session_id, user_id, q, current_state)
                print(f"🤖 助手:\n{response}")
                print("-" * 60)
            continue

        if user_input.startswith("/scene"):
            scene = current_state.get("current_scene", "unknown")
            print(f"当前场景: {scene}")
            continue

        response, current_state = run_turn(graph, session_id, user_id, user_input, current_state)
        print(f"\n🤖 助手:\n{response}\n")


if __name__ == "__main__":
    main()
