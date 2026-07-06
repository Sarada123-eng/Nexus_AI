import asyncio
import streamlit as st
import uuid
import os
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_groq import ChatGroq
from rag_backend import init_embedding, init_vectorstore, upsert_document
from backend import initialize_chatbot, retrieve_thread_messages
from backend import (
    get_all_thread_metas,
    upsert_thread_meta,
    delete_all_chats_data,
)


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


async def _ainvoke_chatbot(chatbot, messages, config):
    return await chatbot.ainvoke({"messages": messages}, config=config)


def _extract_final_text(result) -> str:
    if isinstance(result, dict):
        messages = result.get("messages", [])
        for message in reversed(messages):
            content = getattr(message, "content", None)
            if content:
                return content
        return ""

    content = getattr(result, "content", None)
    if content:
        return content

    return str(result)


def normalize_message(message):
    """Convert restored LangChain messages or stored dicts into a consistent UI dict."""
    if isinstance(message, dict):
        if message.get("role") == "tool":
            return None

        content = message.get("content", "")
        if content is None or (isinstance(content, str) and not content.strip()):
            return None

        return {
            "role": message.get("role", "ai"),
            "content": content,
            "timestamp": message.get("timestamp", ""),
            "sources": message.get("sources", []),
        }

    if isinstance(message, ToolMessage) or message.__class__.__name__.lower().startswith("toolmessage"):
        return None

    role = "human" if message.__class__.__name__.lower().startswith("human") else "ai"
    content = getattr(message, "content", str(message))
    if content is None or (isinstance(content, str) and not content.strip()):
        return None

    return {
        "role": role,
        "content": content,
        "timestamp": "",
        "sources": [],
    }

st.set_page_config(
    page_title="LangGraph Chatbot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
    }

    .chat-message {
        padding: 12px 16px;
        border-radius: 18px;
        margin-bottom: 8px;
        max-width: 85%;
        word-wrap: break-word;
        animation: slideIn 0.3s ease-out;
    }
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateY(10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    .human-message {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        margin-left: auto;
        margin-right: 0;
        text-align: right;
        border-bottom-right-radius: 4px;
    }
    .ai-message {
        background: #f0f0f0;
        color: #333;
        margin-left: 0;
        margin-right: auto;
        text-align: left;
        border-bottom-left-radius: 4px;
        border-left: 4px solid #667eea;
    }
    .message-time {
        font-size: 0.7rem;
        opacity: 0.6;
        margin-top: 4px;
    }

    .chat-container {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        height: 600px;
        overflow-y: auto;
        margin-bottom: 20px;
    }
    .sidebar-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 15px;
        text-align: center;
        font-weight: bold;
    }
    .new-chat-btn {
        width: 100%;
        margin-bottom: 15px;
    }

    .thread-item {
        padding: 10px;
        margin: 8px 0;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.3s ease;
        background: #f5f5f5;
        border-left: 4px solid #667eea;
    }
    .thread-item:hover {
        background: #e8e8f5;
        transform: translateX(5px);
    }

    .thread-item.active {
        background: #667eea;
        color: white;
        border-left: 4px solid #764ba2;
    }

    .input-section {
        display: flex;
        gap: 10px;
        margin-top: 15px;
    }

    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    .status-active {
        background: #4caf50;
        color: white;
    }

    .status-inactive {
        background: #9e9e9e;
        color: white;
    }

    h1 {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 30px;
    }
    </style>
""", unsafe_allow_html=True)

if "chatbot" not in st.session_state:
    st.session_state.chatbot = initialize_chatbot()

if "rag_embedding_model" not in st.session_state:
    st.session_state.rag_embedding_model = init_embedding()

if "rag_collection" not in st.session_state:
    st.session_state.rag_collection = init_vectorstore()

if "thread_docs" not in st.session_state:
    st.session_state.thread_docs = {}

if "thread_rag_mode" not in st.session_state:
    st.session_state.thread_rag_mode = {}

def load_threads_from_storage():
    """Rebuild the sidebar thread list from persisted metadata and checkpoint messages."""
    previous_threads = st.session_state.get("threads", {})
    active_thread_id = st.session_state.get("current_thread")
    threads = {}
    persisted = get_all_thread_metas()

    for thread_id, meta in persisted.items():
        name = meta.get("name") or f"Chat {thread_id[:8]}"
        title = meta.get("title") or name
        title_generated = meta.get("title_generated", False)
        created_at = meta.get("created_at") or datetime.now()
        messages = [
            normalized
            for normalized in (normalize_message(msg) for msg in retrieve_thread_messages(thread_id))
            if normalized
        ]
        if not messages:
            # Keep the currently active in-progress thread even before it has
            # checkpointed messages, otherwise the first send can disappear on rerun.
            if thread_id != active_thread_id:
                continue
            messages = previous_threads.get(thread_id, {}).get("messages", [])
        threads[thread_id] = {
            "name": name,
            "title": title,
            "title_generated": title_generated,
            "created_at": created_at,
            "messages": messages,
        }

    if not threads:
        first_thread_id = str(uuid.uuid4())
        created_at = datetime.now()
        threads[first_thread_id] = {
            "name": "Chat 1",
            "title": "Chat 1",
            "title_generated": False,
            "created_at": created_at,
            "messages": [],
        }
        try:
            upsert_thread_meta(first_thread_id, "Chat 1", "Chat 1", False, created_at)
        except Exception:
            pass

    if active_thread_id and active_thread_id in previous_threads:
        previous_active = previous_threads[active_thread_id]
        if active_thread_id not in threads:
            threads[active_thread_id] = previous_active
        elif not threads[active_thread_id].get("messages") and previous_active.get("messages"):
            threads[active_thread_id]["messages"] = previous_active["messages"]

    return threads


st.session_state.threads = load_threads_from_storage()

first_thread_id = list(st.session_state.threads.keys())[0]
st.session_state.thread_docs.setdefault(first_thread_id, {})
st.session_state.thread_rag_mode.setdefault(first_thread_id, False)

if "current_thread" not in st.session_state:
    st.session_state.current_thread = list(st.session_state.threads.keys())[0]

if st.session_state.current_thread not in st.session_state.threads:
    st.session_state.current_thread = list(st.session_state.threads.keys())[0]

if st.session_state.current_thread not in st.session_state.thread_docs:
    st.session_state.thread_docs[st.session_state.current_thread] = {}

if st.session_state.current_thread not in st.session_state.thread_rag_mode:
    st.session_state.thread_rag_mode[st.session_state.current_thread] = False

if "loading" not in st.session_state:
    st.session_state.loading = False
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "pending_message" not in st.session_state:
    st.session_state.pending_message = None


def generate_chat_title(first_user_message: str) -> str:
    """Generate a short, meaningful title for a chat thread."""
    try:
        title_prompt = [
            SystemMessage(
                content=(
                    "You generate concise chat titles. "
                    "Return only the title text, no quotes, no punctuation, no explanation. "
                    "Keep it to 3 to 6 words and make it meaningful."
                )
            ),
            HumanMessage(
                content=(
                    f"Create a short title for this chat based on the first user message:\n{first_user_message}"
                )
            ),
        ]

        # Use the direct model client so title generation does not create its own
        # LangGraph checkpoint/thread.
        response = ChatGroq(model="openai/gpt-oss-120b", api_key=os.getenv("GROQ_API_KEY")).invoke(title_prompt)
        title = getattr(response, "content", "") or str(response)

        title = title.strip().strip('"').strip("'")
        title = " ".join(title.split())
        return title[:60] if title else "New Chat"

    except Exception:
        fallback_words = first_user_message.strip().split()
        fallback = " ".join(fallback_words[:5]).strip()
        return fallback[:60] if fallback else "New Chat"

with st.sidebar:
    st.markdown('<div class="sidebar-header">💬 Chat Sessions</div>', unsafe_allow_html=True)

    if st.button("➕ New Chat", key="new_chat_btn", use_container_width=True):
        new_thread_id = str(uuid.uuid4())
        chat_number = len(st.session_state.threads) + 1
        st.session_state.threads[new_thread_id] = {
            "name": f"Chat {chat_number}",
            "title": f"Chat {chat_number}",
            "title_generated": False,
            "created_at": datetime.now(),
            "messages": []
        }
        # Persist the metadata immediately so title survives refresh
        try:
            upsert_thread_meta(
                new_thread_id,
                st.session_state.threads[new_thread_id]["name"],
                st.session_state.threads[new_thread_id]["title"],
                False,
                st.session_state.threads[new_thread_id]["created_at"],
            )
        except Exception:
            # non-fatal: persist best-effort
            pass
        st.session_state.thread_docs[new_thread_id] = {}
        st.session_state.thread_rag_mode[new_thread_id] = False
        st.session_state.current_thread = new_thread_id
        st.rerun()
    st.divider()

    st.subheader("Recent Chats", divider="violet")

    for thread_id, thread_data in st.session_state.threads.items():
        is_active = thread_id == st.session_state.current_thread

        col1, col2 = st.columns([4, 1])

        with col1:
            if st.button(
                f"📝 {thread_data.get('title', thread_data['name'])}\n_{thread_data['created_at'].strftime('%m/%d %H:%M')}_",
                key=f"thread_{thread_id}",
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                st.session_state.current_thread = thread_id
                st.rerun()
        with col2:
            badge = '<span class="status-badge status-active">Active</span>' if is_active else '<span class="status-badge status-inactive">Old</span>'
            st.markdown(badge, unsafe_allow_html=True)

    st.divider()

    if st.button("🗑️ Clear All Chats", key="clear_all"):
        if st.session_state.threads:
            st.session_state.threads = {
                str(uuid.uuid4()): {
                    "name": "Chat 1",
                    "title": "Chat 1",
                    "title_generated": False,
                    "created_at": datetime.now(),
                    "messages": []
                }
            }
            st.session_state.thread_docs = {}
            st.session_state.thread_rag_mode = {}
            first_thread_id = list(st.session_state.threads.keys())[0]
            st.session_state.thread_docs[first_thread_id] = {}
            st.session_state.thread_rag_mode[first_thread_id] = False
            st.session_state.current_thread = first_thread_id
            # Clear persisted metadata and checkpointed conversations as well
            try:
                delete_all_chats_data()
            except Exception:
                pass
            st.rerun()
    
    st.divider()
    st.subheader("📄 Document Upload", divider="violet")
    
    uploaded_files = st.file_uploader(
        "Upload documents (PDF, DOCX, TXT)",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        key="doc_uploader"
    )
    
    if uploaded_files:
        for uploaded_file in uploaded_files:
            if st.button(f"Index: {uploaded_file.name}", key=f"index_{uploaded_file.name}", use_container_width=True):                
                doc_id = upsert_document(
                    uploaded_file,
                    st.session_state.rag_collection,
                    st.session_state.rag_embedding_model
                )
                
                if doc_id:
                    tid = st.session_state.current_thread
                    if tid not in st.session_state.thread_docs:
                        st.session_state.thread_docs[tid] = {}
                    st.session_state.thread_docs[tid][doc_id] = uploaded_file.name
                    st.rerun()
        
        docs_count = len(st.session_state.thread_docs.get(st.session_state.current_thread, {}))
        st.write(f"**{docs_count} documents indexed**")
st.markdown("<h1>🤖 LangGraph Chatbot</h1>", unsafe_allow_html=True)

current_thread_id = st.session_state.current_thread
current_thread_data = st.session_state.threads[current_thread_id]

is_rag_enabled_for_thread = st.session_state.thread_rag_mode.get(current_thread_id, False)
rag_badge_html = (
    "<div style='text-align:center; margin-top:-18px; margin-bottom:14px;'>"
    "<span style='display:inline-block; padding:6px 12px; border-radius:999px; font-size:0.8rem;"
    " font-weight:600; background:#e8f5e9; color:#2e7d32; border:1px solid #c8e6c9;'>RAG: ON</span>"
    "</div>"
    if is_rag_enabled_for_thread
    else "<div style='text-align:center; margin-top:-18px; margin-bottom:14px;'>"
         "<span style='display:inline-block; padding:6px 12px; border-radius:999px; font-size:0.8rem;"
         " font-weight:600; background:#f5f5f5; color:#616161; border:1px solid #e0e0e0;'>RAG: OFF</span>"
         "</div>"
)
st.markdown(rag_badge_html, unsafe_allow_html=True)

# Show any persisted error from previous runs
if st.session_state.get("last_error"):
    st.error(f"Last error: {st.session_state.get('last_error')}")

with st.container():
    st.markdown(f"<div class='chat-container' id='chat-container'>", unsafe_allow_html=True)

    if not current_thread_data["messages"]:
        st.markdown(
            """
            <div style="text-align: center; padding: 40px; color: #999;">
                <h3>👋 Start a new conversation!</h3>
                <p>Type your message below and I'll respond with AI-generated insights.</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        for msg in current_thread_data["messages"]:
            if msg.get("role") == "human":
                st.markdown(
                    f"""
                    <div class='chat-message human-message'>
                        <div>{msg.get('content', '')}</div>
                        <div class='message-time'>{msg.get('timestamp', '')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            else:
                # AI message: content is a finalized string (we stream into UI while generating)
                st.markdown(
                    f"""
                    <div class='chat-message ai-message'>
                        <div>{msg.get('content', '')}</div>
                        <div class='message-time'>{msg.get('timestamp', '')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                sources = msg.get("sources", [])
                if sources:
                    with st.expander("📚 Sources", expanded=False):
                        for idx, source in enumerate(sources, start=1):
                            metadata = source.get("metadata", {})
                            source_name = metadata.get("source", "Unknown")
                            chunk_index = metadata.get("chunk_index", "?")
                            distance = source.get("distance")
                            if distance is None:
                                st.caption(f"{idx}. `{source_name}` — chunk {chunk_index}")
                            else:
                                st.caption(f"{idx}. `{source_name}` — chunk {chunk_index} (distance: {distance:.4f})")

    st.markdown("</div>", unsafe_allow_html=True)

if current_thread_id not in st.session_state.thread_rag_mode:
    st.session_state.thread_rag_mode[current_thread_id] = False

use_rag = st.checkbox(
    "🔍 Use RAG (search indexed documents)",
    value=st.session_state.thread_rag_mode[current_thread_id],
    key=f"rag_toggle_{current_thread_id}"
)
st.session_state.thread_rag_mode[current_thread_id] = use_rag

if use_rag and len(st.session_state.thread_docs.get(current_thread_id, {})) == 0:
    st.warning("⚠️ No documents indexed yet. Please upload and index documents first.")
    use_rag = False
    st.session_state.thread_rag_mode[current_thread_id] = False
st.divider()

with st.form(key=f"chat_form_{current_thread_id}", clear_on_submit=True):
    col1, col2 = st.columns([5, 1])

    with col1:
        user_input = st.text_input(
            "Type your message...",
            placeholder="Ask me anything!",
            key=f"user_input_{current_thread_id}",
            label_visibility="collapsed"
        )

    with col2:
        send_button = st.form_submit_button("Send ➤", use_container_width=True, type="primary")

if send_button and user_input.strip():
    timestamp = datetime.now().strftime("%I:%M %p")
    st.session_state.pending_message = {
        "thread_id": current_thread_id,
        "content": user_input,
        "timestamp": timestamp,
    }
    current_thread_data["messages"].append({
        "role": "human",
        "content": user_input,
        "timestamp": timestamp
    })

    # Generate a title only once, using the first user message in the thread
    if not current_thread_data.get("title_generated", False) and len(current_thread_data["messages"]) == 1:
        generated_title = generate_chat_title(user_input)
        current_thread_data["title"] = generated_title
        current_thread_data["name"] = generated_title
        current_thread_data["title_generated"] = True
        # persist generated title
        try:
            upsert_thread_meta(
                current_thread_id,
                current_thread_data["name"],
                current_thread_data["title"],
                True,
                current_thread_data["created_at"],
            )
        except Exception:
            pass

    st.session_state.loading = True
    st.rerun()

if st.session_state.loading:
    with st.spinner("🤔 Thinking..."):
        try:
            pending_message = st.session_state.pop("pending_message", None)
            if pending_message and pending_message.get("thread_id") == current_thread_id:
                user_query = pending_message.get("content", "")
                if user_query:
                    if not current_thread_data["messages"] or current_thread_data["messages"][-1].get("content") != user_query:
                        current_thread_data["messages"].append({
                            "role": "human",
                            "content": user_query,
                            "timestamp": pending_message.get("timestamp", datetime.now().strftime("%I:%M %p")),
                        })
            else:
                user_query = current_thread_data["messages"][-1]["content"]

            config = {'configurable': {'thread_id': current_thread_id}}
            retrieved_chunks = []
            thread_doc_ids = list(st.session_state.thread_docs.get(current_thread_id, {}).keys())

            if use_rag and thread_doc_ids:
                from rag_backend import retrieve_similar_chunks

                all_chunks = []
                for doc_id in thread_doc_ids:
                    chunks = retrieve_similar_chunks(
                        user_query,
                        st.session_state.rag_collection,
                        st.session_state.rag_embedding_model,
                        top_k=3,
                        doc_id=doc_id
                    )
                    all_chunks.extend(chunks)

                all_chunks = sorted(all_chunks, key=lambda x: x.get("distance", float("inf")))
                retrieved_chunks = all_chunks[:5]

                context = "\n\n".join(
                    [
                        f"[Source: {chunk['metadata']['source']} - Chunk {chunk['metadata']['chunk_index']}]\n{chunk['text']}"
                        for chunk in retrieved_chunks
                    ]
                )
                system_prompt = (
                    "You are a helpful assistant that answers questions based ONLY on the provided document excerpts. "
                    "If the answer is not in the documents, say you don't know."
                )
                messages_for_chatbot = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Document excerpts:\n\n{context}\n\nUser question: {user_query}"),
                ]
            else:
                messages_for_chatbot = [HumanMessage(content=user_query)]
            placeholder = st.empty()
            final_result = _run_async_call(_ainvoke_chatbot, st.session_state.chatbot, messages_for_chatbot, config)
            final_text = _extract_final_text(final_result)
            if not final_text:
                final_text = "I’m sorry — I couldn’t generate a response this time."

            placeholder.markdown(
                f"<div class='chat-message ai-message'><div>{final_text}</div></div>",
                unsafe_allow_html=True,
            )

            ai_timestamp = datetime.now().strftime("%I:%M %p")
            # Store the finalized string (not generator) in session state
            current_thread_data["messages"].append({
                "role": "ai",
                "content": final_text,
                "timestamp": ai_timestamp,
                "sources": retrieved_chunks if (use_rag and thread_doc_ids) else []
            })
            # clear last_error on success
            st.session_state.last_error = None
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")

    st.session_state.loading = False
    st.rerun()

st.markdown(
    """
    <div style="text-align: center; padding: 20px; color: #999; font-size: 0.9rem;">
        <p>Powered by LangGraph & Groq API | Built with Streamlit 🎈</p>
    </div>
    """,
    unsafe_allow_html=True
)
