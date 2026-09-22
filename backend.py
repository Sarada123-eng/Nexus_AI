import asyncio
import os
from functools import lru_cache
from typing import Annotated, TypedDict, Any

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return None

load_dotenv()
from langchain_core.messages import BaseMessage
from uuid import uuid4
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from langgraph.store.base import BaseStore
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import add_messages
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.prebuilt import ToolNode
from chatbot_db import (
    checkpointer,
    async_checkpointer,
    delete_all_chats_data,
    ensure_threads_table,
    get_all_thread_metas,
    upsert_thread_meta,
    retrieve_thread_messages,
    async_retrieve_thread_messages,
    async_get_all_thread_metas,
    async_upsert_thread_meta,
)
from chatbot_tools import search_tool as local_search_tool
from memory_store import memory_store_factory, system_prompt_factory

class ChatState(TypedDict):
    messages: Annotated[
        list[BaseMessage],
        "The conversation history, including the latest user message.",
        add_messages,
    ]

class MemoryItem(BaseModel):
    text: str = Field(description="The content of the memory item.")
    is_new: bool = Field(description="True if this memory is NEW and should be stored. False if duplicate/already known .")

class MemoryDecision(BaseModel):
    should_write: bool = Field(description="Whether the assistant should write to memory based on the current conversation context.")
    memories_to_write: list[MemoryItem] = Field(
        default_factory=list,
        description="A list of memory entries to write."
    )

model = ChatGroq(model="openai/gpt-oss-120b", api_key=os.getenv("GROQ_API_KEY"))

MEMORY_PROMPT = """You are responsible for updating and maintaining accurate user memory.

CURRENT USER DETAILS (existing memories):
{user_details_content}

TASK:
- Review the user's latest message.
- Extract user-specific info worth storing long-term (identity, stable preferences, ongoing projects/goals).
- For each extracted item, set is_new=true ONLY if it adds NEW information compared to CURRENT USER DETAILS.
- If it is basically the same meaning as something already present, set is_new=false.
- Keep each memory as a short atomic sentence.
- No speculation; only facts stated by the user.
- If there is nothing memory-worthy, return an empty list.
"""


def _run_async_call(async_fn, *args, **kwargs):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args, **kwargs))

    result_box: list[object] = []
    error_box: list[BaseException] = []

    def _runner():
        try:
            result_box.append(asyncio.run(async_fn(*args, **kwargs)))
        except BaseException as exc:
            error_box.append(exc)

    import threading

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if error_box:
        raise error_box[0]
    return result_box[0]


async def initialize_chatbot_async(graph_checkpointer):
    server_activate = os.getenv("SERVER_ACTIVATE")
    server_main = os.getenv("SERVER_MAIN")
    tools = []

    if server_activate and server_main:
        # PowerShell command: & 'activate.ps1'; python 'main.py'
        pw_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"& '{server_activate}'; python '{server_main}'",
        ]
        # Start only the optional chatbot MCP server via stdio here. The Manim
        # MCP server is launched separately and is not auto-spawned by the API.
        client = MultiServerMCPClient({
            "chatbot-server": {
                "transport": "stdio",
                "command": "powershell.exe",
                "args": pw_args,
            }
        })

        try:
            tools = await client.get_tools()
        except Exception as exc:
            print("Failed to start the configured chatbot MCP server; continuing with built-in tools only")
            print("Check SERVER_ACTIVATE and SERVER_MAIN if MCP tools are required")
            print("Error:", exc)
    else:
        print("Optional chatbot MCP server is not configured; using built-in tools only")

    try:
        existing_names = [getattr(t, "name", "").lower() for t in tools]
    except Exception:
        existing_names = []

    if not any("search" in n or "duck" in n or "ddg" in n for n in existing_names):
        tools.append(local_search_tool)

    model_with_tool = model.bind_tools(tools)
    tool_node = ToolNode(tools)

    async def chat_node(state: ChatState, config: RunnableConfig, store: BaseStore) -> ChatState:
        user_id = config.get("configurable", {}).get("user_id", "u1")
        user_details = ("user", user_id, "details")
        items = store.search(user_details)

        if items:
            user_detail_context = "\n".join(f"- {it.value.get('data', '')}" for it in items)
        else:
            user_detail_context = "No user-specific memory available."
        
        SYSTEM_PROMPT_TEMPLATE = system_prompt_factory(user_detail_context)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(user_detail_context=user_detail_context)

        system_msg = SystemMessage(content=system_prompt)

        response = await model_with_tool.ainvoke([system_msg] + state["messages"])
        return {"messages": [response]}
    
    async def remember_messages(state: ChatState, config: RunnableConfig, store: BaseStore) -> ChatState:
        extractor_llm = model.with_structured_output(MemoryDecision)
        user_id = config.get("configurable", {}).get("user_id", "u1")
        namespace = ("user", user_id, "details")
        existing_items = store.search(namespace)
        existing_text = [it.value.get("data", "") for it in existing_items if it.value.get("data")]
        user_details_content = "\n".join(f"- {text}" for text in existing_text) if existing_text else "No user-specific memory available."
        last_user_msg = next(
            (msg for msg in reversed(state["messages"]) if isinstance(msg, HumanMessage)),
            None,
        )
        if not last_user_msg:
            return {}
        
        decision = await extractor_llm.ainvoke(
            [
            SystemMessage(
content=MEMORY_PROMPT.format(user_details_content=user_details_content)

                ),
                {"role": "user", "content": last_user_msg.content}
            ]
        )
        if decision.should_write:
            for mem in decision.memories_to_write:
                if mem.is_new:
                    store.put(namespace, str(uuid4()), {"data": mem.text})
        return {}

    def route_after_chat(state: ChatState) -> str:
        last_msg = state["messages"][-1] if state["messages"] else None
        if getattr(last_msg, "tool_calls", None):
            return "tools"
        return "remember"

    graph = StateGraph(ChatState)
    graph.add_node("chat_node", chat_node)
    graph.add_node("tools", tool_node)
    graph.add_node("remember", remember_messages)
    graph.add_edge(START, "chat_node")
    graph.add_conditional_edges(
        "chat_node",
        route_after_chat,
        {"tools": "tools", "remember": "remember"},
    )
    graph.add_edge("tools", "chat_node")
    graph.add_edge("remember", END)

    store = memory_store_factory()
    compiled = graph.compile(checkpointer=graph_checkpointer, store=store)
    compiled._bound_model = model_with_tool  # expose for streaming
    return compiled


@lru_cache(maxsize=1)
def initialize_chatbot():
    # Synchronous compatibility entry point used by the current Streamlit app.
    return _run_async_call(initialize_chatbot_async, checkpointer)


async def retrieve_thread_messages_async(thread_id: str) -> list[BaseMessage]:
    # Delegate to the implementation in chatbot_db which prefers the real
    # AsyncSqliteSaver when available and falls back to a threaded wrapper.
    return await async_retrieve_thread_messages(thread_id)


def retrieve_thread_messages(thread_id: str) -> list[BaseMessage]:
    checkpoint_tuple = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    if checkpoint_tuple:
        return checkpoint_tuple.checkpoint["channel_values"].get("messages", [])

    return []




if __name__ == "__main__":
    ensure_threads_table()
    for thread_id, meta in get_all_thread_metas().items():
        print(f"Thread: {thread_id} | Title: {meta.get('title')}")
        print(f"Messages: {retrieve_thread_messages(thread_id)}")
