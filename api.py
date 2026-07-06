import asyncio
from contextlib import asynccontextmanager
from fastapi.responses import StreamingResponse
import os
from typing import AsyncIterator
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from pydantic import BaseModel, Field
import uuid
import json
from langchain_groq import ChatGroq
from chatbot_db import (
    async_get_all_thread_metas,
    async_get_single_thread_meta,
    async_upsert_thread_meta,
    async_delete_all_chats_data,
    async_add_thread_document,
    async_get_thread_documents,
    async_delete_thread_document,
    async_retrieve_thread_messages,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend import initialize_chatbot_async
from memory_store import system_prompt_factory
from rag_backend import init_embedding, init_vectorstore, upsert_document, retrieve_similar_chunks
from rag_workflow import retrieve_refined_context
from fastapi.staticfiles import StaticFiles
from research_api import router as research_router


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    use_rag: bool = False


class ChatResponse(BaseModel):
    message: str
    thread_id: str
    role: str
    sources: list[dict] | None = None

class ThreadResponse(BaseModel):
    thread_id: str
    title: str
    created_at: datetime | None

title_llm = ChatGroq(model="openai/gpt-oss-120b", api_key=os.getenv("GROQ_API_KEY"))


def extract_final_text(result: dict) -> str:
    for message in reversed(result.get("messages", [])):
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content

    raise RuntimeError("The chatbot returned no assistant message.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.chatbot = None
    app.state.chatbot_error = None
    app.state.embedding_model = None
    app.state.rag_collection = None

    try:
        app.state.embedding_model = init_embedding()
        app.state.rag_collection = init_vectorstore()
    except Exception as exc:
        print("Failed to initialize RAG components:", exc)

    async with AsyncSqliteSaver.from_conn_string("chatbot.db") as checkpointer:
        try:
            app.state.chatbot = await initialize_chatbot_async(checkpointer)
            if app.state.chatbot is None:
                app.state.chatbot_error = "Chatbot initialization returned no graph."
        except Exception as exc:
            app.state.chatbot_error = str(exc)
        yield


app = FastAPI(title="LangGraph Chatbot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(research_router)
os.makedirs("images", exist_ok=True)
app.mount("/images", StaticFiles(directory="images"), name="images")



@app.get("/health")
async def health_check() -> dict[str, str | bool | None]:
    chatbot_ready = app.state.chatbot is not None
    return {
        "status": "ok" if chatbot_ready else "degraded",
        "chatbot_ready": chatbot_ready,
        "chatbot_error": app.state.chatbot_error,
    }

@app.get("/threads", response_model=list[ThreadResponse])
async def get_threads() -> list[ThreadResponse]:
    try:
        thread_metas = await async_get_all_thread_metas()
        threads = [
            ThreadResponse(
                thread_id=thread_id,
                title=meta.get("title") or meta.get("name") or "New Chat",
                created_at=meta.get("created_at"),
            )
            for thread_id, meta in thread_metas.items()
        ]
        return sorted(
            threads,
            key=lambda thread: thread.created_at or datetime.min,
            reverse=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/threads", response_model=ThreadResponse)
async def create_threads() -> ThreadResponse:
    try:
        thread_id = str(uuid.uuid4())
        await async_upsert_thread_meta(thread_id,
         title="New Chat", name="New Chat", title_generated=False)
        return ThreadResponse(thread_id=thread_id, title="New Chat", created_at=datetime.utcnow())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.delete("/threads")
async def delete_threads():
    try:
        await async_delete_all_chats_data()
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class DocumentResponse(BaseModel):
    doc_id: str
    filename: str


class FastAPIUploadedFile:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self.content = content

    def getvalue(self) -> bytes:
        return self.content


@app.post("/threads/{thread_id}/documents", response_model=DocumentResponse)
async def upload_document(thread_id: str, file: UploadFile = File(...), request: Request = None):
    try:
        content = await file.read()
        wrapped_file = FastAPIUploadedFile(file.filename, content)
        
        embedding_model = request.app.state.embedding_model
        collection = request.app.state.rag_collection
        
        loop = asyncio.get_running_loop()
        doc_id = await loop.run_in_executor(
            None,
            upsert_document,
            wrapped_file,
            collection,
            embedding_model
        )
        
        await async_add_thread_document(thread_id, doc_id, file.filename)
        return DocumentResponse(doc_id=doc_id, filename=file.filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/documents", response_model=list[DocumentResponse])
async def get_documents(thread_id: str):
    try:
        docs = await async_get_thread_documents(thread_id)
        return [DocumentResponse(doc_id=d["doc_id"], filename=d["filename"]) for d in docs]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/threads/{thread_id}/documents/{doc_id}")
async def delete_document(thread_id: str, doc_id: str, request: Request):
    try:
        collection = request.app.state.rag_collection
        collection.delete(where={"doc_id": doc_id})
        await async_delete_thread_document(thread_id, doc_id)
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    chatbot = request.app.state.chatbot
    if chatbot is None:
        async def _err():
            yield f"event: error\ndata: {json.dumps({'message': request.app.state.chatbot_error or 'Chatbot is not ready.'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    async def event_generator() -> AsyncIterator[str]:
        try:
            config = {"configurable": {"thread_id": payload.thread_id, "user_id": payload.user_id}}

            # Load existing conversation history from the checkpointer
            checkpoint_tuple = await chatbot.checkpointer.aget_tuple(config)
            history = []
            if checkpoint_tuple:
                history = checkpoint_tuple.checkpoint["channel_values"].get("messages", [])

            # Retrieve user memory and prepend system message
            user_id = payload.user_id
            user_details = ("user", user_id, "details")
            items = chatbot.store.search(user_details) if (chatbot and hasattr(chatbot, "store") and chatbot.store) else []
            if items:
                user_detail_context = "\n".join(f"- {it.value.get('data', '')}" for it in items)
            else:
                user_detail_context = "No user-specific memory available."

            system_prompt_template = system_prompt_factory(user_detail_context)
            system_prompt = system_prompt_template.format(user_detail_context=user_detail_context)
            system_msg = SystemMessage(content=system_prompt)

            # Retrieve similar chunks if using RAG
            retrieved_chunks = []
            if payload.use_rag:
                from chatbot_db import get_thread_documents
                thread_docs = await asyncio.to_thread(get_thread_documents, payload.thread_id)
                thread_doc_ids = [d["doc_id"] for d in thread_docs]
                
                if thread_doc_ids:
                    embedding_model = request.app.state.embedding_model
                    collection = request.app.state.rag_collection
                    
                    all_chunks = []
                    loop = asyncio.get_running_loop()
                    for doc_id in thread_doc_ids:
                        chunks = await loop.run_in_executor(
                            None,
                            retrieve_similar_chunks,
                            payload.message,
                            collection,
                            embedding_model,
                            3,
                            doc_id
                        )
                        all_chunks.extend(chunks)
                    
                    all_chunks = sorted(all_chunks, key=lambda x: x.get("distance", float("inf")))
                    retrieved_chunks = all_chunks[:5]

            if payload.use_rag and retrieved_chunks:
                context = "\n\n".join([
                    f"[Source: {chunk['metadata']['source']} - Chunk {chunk['metadata']['chunk_index']}]\n{chunk['text']}"
                    for chunk in retrieved_chunks
                ])
                system_prompt = (
                    "You are a helpful assistant that answers questions based ONLY on the provided document excerpts. "
                    "If the answer is not in the documents, say you don't know."
                )
                system_msg = SystemMessage(content=system_prompt)
                messages_to_send = [
                    system_msg,
                    HumanMessage(content=f"Document excerpts:\n\n{context}\n\nUser question: {payload.message}")
                ]
            else:
                messages_to_send = [system_msg] + list(history) + [HumanMessage(content=payload.message)]

            # If we retrieved chunks, yield them as sources first
            if payload.use_rag and retrieved_chunks:
                yield f"event: sources\ndata: {json.dumps({'sources': retrieved_chunks})}\n\n"

            # First: probe whether the model wants to call a tool (non-streaming)
            probe = await chatbot._bound_model.ainvoke(messages_to_send)
            has_tool_calls = bool(getattr(probe, "tool_calls", None))

            if has_tool_calls:
                # Stream events from the full graph so we get real-time
                # tokens even when the graph routes through tool nodes.
                full_response = ""
                async for event in chatbot.astream_events(
                    {"messages": [HumanMessage(content=payload.message)]},
                    config=config,
                    version="v2",
                ):
                    kind = event.get("event", "")

                    # Notify the client which tool is running.
                    if kind == "on_tool_start":
                        tool_name = event.get("name", "unknown")
                        yield f"event: tool_start\ndata: {json.dumps({'tool': tool_name})}\n\n"

                    # Stream tokens from the chat model.  After tool
                    # execution the graph re-enters chat_node and the
                    # model produces the final answer — those chunks
                    # arrive here in real time.
                    elif kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk is not None:
                            content = getattr(chunk, "content", None)
                            # Only stream plain text, not tool-call chunks
                            if content and isinstance(content, str):
                                full_response += content
                                yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"

                # Fallback: if no text tokens were streamed (the graph
                # ended right after tools without a second LLM call),
                # pull the final answer from the persisted checkpoint.
                if not full_response:
                    cp = await chatbot.checkpointer.aget_tuple(config)
                    if cp:
                        try:
                            fallback = extract_final_text(
                                cp.checkpoint.get("channel_values", {})
                            )
                        except RuntimeError:
                            fallback = ""
                        if fallback:
                            chunk_size = 8
                            for i in range(0, len(fallback), chunk_size):
                                piece = fallback[i : i + chunk_size]
                                yield f"event: token\ndata: {json.dumps({'content': piece})}\n\n"
                            full_response = fallback

            else:
                # No tool calls — stream directly from the bound model
                full_response = ""
                async for chunk in chatbot._bound_model.astream(messages_to_send):
                    content = getattr(chunk, "content", None)
                    if content and isinstance(content, str):
                        full_response += content
                        yield f"event: token\ndata: {json.dumps({'content': content})}\n\n"

                # Persist the streamed turn to the checkpointer
                if full_response:
                    if payload.use_rag and retrieved_chunks:
                        # For RAG, bypass graph invocation and write direct checkpoint state.
                        await chatbot.aupdate_state(
                            config,
                            {
                                "messages": [
                                    HumanMessage(content=payload.message),
                                    AIMessage(content=full_response, response_metadata={"sources": retrieved_chunks})
                                ]
                            }
                        )
                    else:
                        await chatbot.ainvoke(
                            {"messages": [HumanMessage(content=payload.message)]},
                            config=config,
                        )

            # Generate title if needed
            thread_meta = await async_get_single_thread_meta(payload.thread_id)
            if not thread_meta.get("title_generated", False):
                try:
                    cp = await chatbot.checkpointer.aget_tuple(config)
                    msgs = cp.checkpoint["channel_values"].get("messages", []) if cp else []
                    first_message = msgs[0].content if msgs else payload.message
                except Exception:
                    first_message = payload.message

                prompt = f"""
Generate a short conversation title for "{first_message}".
Maximum 5 words.
No quotes.

Example:
first_message: How do I implement LFU Cache,
title: LFU Cache Implementation
"""
                title_response = await title_llm.ainvoke(prompt)
                title = title_response.content.strip()
                await async_upsert_thread_meta(
                    payload.thread_id,
                    title=title,
                    name=title,
                    title_generated=True,
                    created_at=thread_meta.get("created_at"),
                )

            yield f"event: complete\ndata: {json.dumps({'thread_id': payload.thread_id})}\n\n"

        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    chatbot = request.app.state.chatbot
    if chatbot is None:
        raise HTTPException(
            status_code=503,
            detail=request.app.state.chatbot_error or "Chatbot is not ready.",
        )

    try:
        config = {"configurable": {"thread_id": payload.thread_id, "user_id": payload.user_id}}

        retrieved_chunks = []
        refined_context = ""
        if payload.use_rag:
            from chatbot_db import get_thread_documents
            thread_docs = await asyncio.to_thread(get_thread_documents, payload.thread_id)
            thread_doc_ids = [d["doc_id"] for d in thread_docs]

            if thread_doc_ids:
                embedding_model = request.app.state.embedding_model
                collection = request.app.state.rag_collection
                loop = asyncio.get_running_loop()

                # 1) Run the full Corrective-RAG pipeline (score -> triage ->
                #    refine, with Tavily fallback if everything's incorrect).
                #    This produces the context string we hand to the answer LLM.
                refined_context = await loop.run_in_executor(
                    None,
                    retrieve_refined_context,
                    payload.message,
                    collection,
                    embedding_model,
                    5,        # top_k
                    None,     # doc_id: search whole corpus, let triage filter
                )

                # 2) Also fetch raw chunks for the sources panel (cheap;
                #    single embedding + query). Kept on a per-thread-doc basis
                #    so each uploaded document gets represented.
                all_chunks = []
                for doc_id in thread_doc_ids:
                    chunks = await loop.run_in_executor(
                        None,
                        retrieve_similar_chunks,
                        payload.message,
                        collection,
                        embedding_model,
                        3,
                        doc_id,
                    )
                    all_chunks.extend(chunks)
                all_chunks = sorted(all_chunks, key=lambda x: x.get("distance", float("inf")))
                retrieved_chunks = all_chunks[:5]

        # Fallback string from the refine pipeline means "no useful info found".
        rag_have_context = bool(
            payload.use_rag
            and refined_context
            and not refined_context.startswith("No relevant information found")
        )

        if rag_have_context:
            system_prompt = (
                "You are a helpful assistant that answers questions based ONLY on the provided document excerpts. "
                "If the answer is not in the documents, say you don't know."
            )
            system_msg = SystemMessage(content=system_prompt)
            messages_to_send = [
                system_msg,
                HumanMessage(content=f"Document excerpts:\n\n{refined_context}\n\nUser question: {payload.message}")
            ]

            response = await chatbot._bound_model.ainvoke(messages_to_send)
            final_text = getattr(response, "content", "")

            await chatbot.aupdate_state(
                config,
                {
                    "messages": [
                        HumanMessage(content=payload.message),
                        AIMessage(content=final_text, response_metadata={"sources": retrieved_chunks})
                    ]
                },
            )
        else:
            result = await chatbot.ainvoke(
                {"messages": [HumanMessage(content=payload.message)]},
                config=config,
            )
            final_text = extract_final_text(result)

        thread_meta = await async_get_single_thread_meta(payload.thread_id)

        if(thread_meta["title_generated"] == False):
            try:
                checkpoint_tuple = await chatbot.checkpointer.aget_tuple({"configurable": {"thread_id": payload.thread_id}})
                messages = checkpoint_tuple.checkpoint["channel_values"].get("messages", [])
                first_message = messages[0].content if messages else payload.message
            except Exception:
                first_message = payload.message
            
            prompt = f"""
Generate a short conversation title for "{first_message}".
Maximum 5 words.
No quotes.

Example:
first_message: How do I implement LFU Cache,
title: LFU Cache Implementation
"""
            response = await title_llm.ainvoke(prompt)
            print(response.content)
            title = response.content.strip()
            await async_upsert_thread_meta(payload.thread_id, title=title, name=title, title_generated=True,created_at=thread_meta["created_at"])
        return ChatResponse(
            message=final_text,
            thread_id=payload.thread_id,
            role="assistant",
            sources=retrieved_chunks if (payload.use_rag and retrieved_chunks) else None
        )
    except HTTPException:
        raise
    except Exception as exc:
        import traceback as _tb
        import sys as _sys
        print("\n=== /chat error ===", file=_sys.stderr, flush=True)
        _tb.print_exc(file=_sys.stderr)
        print("=== end ===\n", file=_sys.stderr, flush=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/messages", response_model=list[ChatResponse])
async def get_thread_messages(thread_id: str, request: Request) -> list[ChatResponse]:
    try:
        messages = await async_retrieve_thread_messages(thread_id)
        return [
            ChatResponse(
                message=msg.content,
                thread_id=thread_id,
                role="user" if isinstance(msg, HumanMessage) else "assistant",
                sources=getattr(msg, "response_metadata", {}).get("sources") if isinstance(msg, AIMessage) else None,
            )
            for msg in messages
            if isinstance(msg, (HumanMessage, AIMessage))
            and isinstance(msg.content, str)
            and msg.content.strip()
        ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
