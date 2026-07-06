"""
LangGraph version of rag_backend.py.

This module reproduces the behavior of rag_backend.py as a LangGraph workflow,
without modifying the original file.

Functions mirrored from rag_backend.py:
    - extract_text(uploaded_file)                    -> extract_node
    - chunk_text(text, ...)                          -> chunk_node
    - init_embedding()                               -> init_embedding_node  (cached)
    - init_vectorstore(persist_dir)                  -> init_vectorstore_node (cached)
    - upsert_document(uploaded_file, ...)            -> upsert_graph (extract -> chunk -> embed -> upsert)
    - retrieve_similar_chunks(query, ...)            -> retrieve_graph (embed_query -> query -> format)
    - answer_with_context(query, retrieved, chatbot) -> answer_node (streams via chatbot.stream)

Public surface (parity with rag_backend.py):
    init_embedding()
    init_vectorstore(persist_dir="./chroma_db")
    upsert_document(uploaded_file, collection, embedding_model, doc_id=None) -> str
    retrieve_similar_chunks(query, collection, embedding_model, top_k=5, doc_id=None) -> list[dict]
    answer_with_context(query, retrieved_chunks, chatbot)

Corrective-RAG additions:
    score_docs_node          - batched per-chunk relevance scoring
    triage_docs_node         - routes chunks into correct / ambiguous / incorrect
    refine_context_node      - sentence-level refinement over the correct bucket
    wrong_docs_node          - entry stub shared by ambiguous + incorrect
    rewrite_query_node       - rewrites the user query for web search
    tavily_search_node       - runs Tavily + normalizes results to Chroma shape
    merge_node               - merges local ambiguous + Tavily (deduped) for refine
    ambiguous_docs_node      - placeholder (no longer in the active path)
    retrieve_refined_context(query, collection, embedding_model, ...)  -> refined str
    answer_with_refined_context(query, collection, embedding_model, chatbot, ...) -> stream

Triage thresholds (env-overridable):
    RAG_SCORE_MIN_THRESHOLD   (default 0.40)  - below this = incorrect
    RAG_SCORE_MAX_THRESHOLD   (default 0.75)  - at/above this = correct
    RAG_QUERY_REWRITE_ENABLED (default true) - bypass query rewriting if false
    RAG_QUERY_REWRITE_MODEL   (default openai/gpt-oss-120b)
    RAG_TAVILY_MAX_RESULTS    (default 5)
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


# Reuse the exact helpers from rag_backend.py so behavior stays identical.
# We import lazily inside helpers where useful, but for the LangGraph nodes we
# delegate to rag_backend.extract_text / rag_backend.chunk_text to keep parity.
import rag_backend as _rag


# ---------------------------------------------------------------------------
# Protocol (kept identical to rag_backend.UploadedFile)
# ---------------------------------------------------------------------------
class UploadedFile(Protocol):
    name: str

    def getvalue(self) -> bytes:
        ...


# ---------------------------------------------------------------------------
# State definitions for the LangGraph subgraphs
# ---------------------------------------------------------------------------
class UpsertState(TypedDict, total=False):
    """State for the upsert pipeline: extract -> chunk -> embed -> upsert."""
    uploaded_file: UploadedFile
    collection: Any
    embedding_model: Any
    doc_id: str
    text: str
    chunks: list[str]


class RetrieveState(TypedDict, total=False):
    """State for the retrieval pipeline:
       embed_query -> query_chroma -> format_results -> score_docs
       -> triage_docs -> (correct -> refine_context) | (ambiguous | incorrect: placeholder)
    """
    query: str
    collection: Any
    embedding_model: Any
    top_k: int
    doc_id: str | None
    query_embedding: list[float]
    raw_results: dict
    retrieved_chunks: list[dict]
    # CRAG triage fields (Corrective RAG — Correct / Ambiguous / Incorrect)
    doc_scores: list[dict]          # [{doc_id, chunk_index, score, reason}]
    correct_chunks: list[dict]      # chunks routed to refine_context
    ambiguous_chunks: list[dict]    # placeholder bucket (not yet routed)
    incorrect_chunks: list[dict]    # placeholder bucket (not yet routed)
    # Refine-step fields (Corrective RAG)
    sentences: list[dict]           # [{text, source, chunk_index, distance}]
    verdicts: list[dict]            # [{text, keep, reason}]
    refined_context: str            # final refined context string (CRAG-corrected)
    # Web-search branch fields (rewrite + tavily)
    rewritten_query: str            # output of rewrite_query_node, fed to Tavily
    rewritten_query_rationale: str  # debug log only
    tavily_raw_count: int           # number of results Tavily returned (raw)
    # Merge-step counters (debug / observability)
    merge_local_count: int          # # of local ambiguous chunks input
    merge_web_count: int            # # of Tavily chunks input
    merge_dropped_count: int        # # dropped as duplicates


# ---------------------------------------------------------------------------
# Corrective RAG — sentence-level relevance filter
# ---------------------------------------------------------------------------
class RelevanceItem(BaseModel):
    """Per-sentence relevance verdict returned by the LLM."""
    sentence: str = Field(description="The exact sentence being judged (verbatim).")
    keep: bool = Field(description="True if the sentence helps answer the question; False otherwise.")
    reason: str = Field(default="", description="One short sentence explaining the decision.")


class RelevanceVerdict(BaseModel):
    """Batched verdict over all candidate sentences in one LLM call."""
    verdicts: list[RelevanceItem] = Field(
        description="One verdict per input sentence, in the same order."
    )


# ---------------------------------------------------------------------------
# Corrective RAG — per-document triage (Correct / Ambiguous / Incorrect)
# ---------------------------------------------------------------------------
class DocScore(BaseModel):
    """Per-document relevance score returned by the LLM.

    `score` is a float in [0.0, 1.0] where 1.0 means the document fully answers
    the question and 0.0 means it is completely off-topic.
    """
    doc_id: str = Field(description="The doc_id from the chunk metadata.")
    chunk_index: int = Field(description="The chunk index within the document.")
    score: float = Field(description="Relevance score between 0.0 and 1.0 (inclusive).")
    reason: str = Field(default="", description="One short sentence explaining the score.")


class DocScores(BaseModel):
    """Batched per-document scores over all retrieved chunks in one LLM call."""
    scores: list[DocScore] = Field(
        description="One score per input document, in the same order."
    )


# ---------------------------------------------------------------------------
# Corrective RAG — web-search query rewriter
# ---------------------------------------------------------------------------
class RewrittenQuery(BaseModel):
    """Structured output of the query rewriter.

    `query` is the rewritten keyword-style query, optimized for an open-web
    search engine (Tavily). `rationale` is a short note explaining the
    rewrite (logged for debugging, never sent to Tavily).
    """
    query: str = Field(
        description=(
            "A focused, keyword-rich query suitable for a web search engine. "
            "Strip conversational filler, expand acronyms, surface named entities, "
            "and prefer noun-phrase structure. Keep it under ~20 words."
        )
    )
    rationale: str = Field(
        default="",
        description="One short sentence explaining why this rewrite is better for web search.",
    )


# Triage thresholds — env-overridable.
RAG_SCORE_MIN_THRESHOLD: float = float(os.getenv("RAG_SCORE_MIN_THRESHOLD", "0.40"))
RAG_SCORE_MAX_THRESHOLD: float = float(os.getenv("RAG_SCORE_MAX_THRESHOLD", "0.75"))


# Cap on sentences sent to the relevance-check LLM. Beyond this the cost /
# context gets silly and the final-answer LLM wouldn't use it anyway.
MAX_SENTENCES_FOR_REFINEMENT = 30

# Cheap/fast model for the relevance + doc-score checks. Configurable via env.
_RELEVANCE_MODEL_NAME = os.getenv("RAG_RELEVANCE_MODEL", "openai/gpt-oss-120b")
_SCORE_MODEL_NAME = os.getenv("RAG_SCORE_MODEL", "openai/gpt-oss-120b")


# Lazy singletons for the structured-output LLM bindings.
@lru_cache(maxsize=1)
def _get_relevance_checker():
    """Returns an LLM bound to RelevanceVerdict via .with_structured_output(...)."""
    from langchain_groq import ChatGroq
    llm = ChatGroq(model=_RELEVANCE_MODEL_NAME, api_key=os.getenv("GROQ_API_KEY"))
    return llm.with_structured_output(RelevanceVerdict)


@lru_cache(maxsize=1)
def _get_doc_scorer():
    """Returns an LLM bound to DocScores via .with_structured_output(...)."""
    from langchain_groq import ChatGroq
    llm = ChatGroq(model=_SCORE_MODEL_NAME, api_key=os.getenv("GROQ_API_KEY"))
    return llm.with_structured_output(DocScores)


# Model used for query rewriting (cheap, fast).
_QUERY_REWRITE_MODEL_NAME = os.getenv("RAG_QUERY_REWRITE_MODEL", "openai/gpt-oss-120b")


@lru_cache(maxsize=1)
def _get_query_rewriter():
    """Returns an LLM bound to RewrittenQuery via .with_structured_output(...)."""
    from langchain_groq import ChatGroq
    llm = ChatGroq(model=_QUERY_REWRITE_MODEL_NAME, api_key=os.getenv("GROQ_API_KEY"))
    return llm.with_structured_output(RewrittenQuery)


# Regex-based sentence splitter. We deliberately avoid NLTK/spaCy to keep
# this file dependency-light and deterministic across environments.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences. Falls back to [text] when splitter yields nothing."""
    text = (text or "").strip()
    if not text:
        return []
    parts = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s and s.strip()]
    return parts if parts else ([text] if text else [])


# ---------------------------------------------------------------------------
# Cached initializers — same semantics as rag_backend.init_* helpers.
# LangGraph nodes below call these; caching here mirrors @lru_cache on the
# original module-level helpers so we don't re-load the model / collection.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def init_embedding():
    return _rag.init_embedding()


@lru_cache(maxsize=None)
def init_vectorstore(persist_dir: str = "./chroma_db"):
    return _rag.init_vectorstore(persist_dir)


# ---------------------------------------------------------------------------
# Upsert graph nodes
# ---------------------------------------------------------------------------
def extract_node(state: UpsertState) -> UpsertState:
    """Node: extract_text. Delegates to rag_backend.extract_text."""
    return {"text": _rag.extract_text(state["uploaded_file"])}


def chunk_node(state: UpsertState) -> UpsertState:
    """Node: chunk_text. Delegates to rag_backend.chunk_text."""
    return {"chunks": _rag.chunk_text(state["text"])}


def embed_and_upsert_node(state: UpsertState) -> UpsertState:
    """Node: embed each chunk + upsert into Chroma.

    Mirrors the loop inside rag_backend.upsert_document:
        for i, chunk in enumerate(chunks):
            embedding = embedding_model.encode(chunk)
            collection.upsert(ids=[f"{doc_id}_{i}"], ...)
    """
    doc_id = state["doc_id"]
    collection = state["collection"]
    embedding_model = state["embedding_model"]
    chunks = state["chunks"]
    source_name = state["uploaded_file"].name

    if not chunks:
        raise ValueError(f"Document '{source_name}' contains no indexable text.")

    for i, chunk in enumerate(chunks):
        embedding = embedding_model.encode(chunk)
        collection.upsert(
            ids=[f"{doc_id}_{i}"],
            embeddings=[embedding],
            metadatas=[{
                "source": source_name,
                "chunk_index": i,
                "doc_id": doc_id,
            }],
            documents=[chunk],
        )

    return {}


# ---------------------------------------------------------------------------
# Build the upsert graph: extract -> chunk -> embed_and_upsert
# ---------------------------------------------------------------------------
def _build_upsert_graph():
    g = StateGraph(UpsertState)
    g.add_node("extract", extract_node)
    g.add_node("chunk", chunk_node)
    g.add_node("embed_and_upsert", embed_and_upsert_node)
    g.add_edge(START, "extract")
    g.add_edge("extract", "chunk")
    g.add_edge("chunk", "embed_and_upsert")
    g.add_edge("embed_and_upsert", END)
    return g.compile()


# Module-level compiled upsert graph (one per process).
_UPSERT_GRAPH = _build_upsert_graph()


# ---------------------------------------------------------------------------
# Public upsert API — same signature as rag_backend.upsert_document
# ---------------------------------------------------------------------------
def upsert_document(
    uploaded_file: UploadedFile,
    collection,
    embedding_model,
    doc_id: str | None = None,
) -> str:
    """Run the upsert LangGraph. Returns the doc_id used (new UUID if none given)."""
    import uuid as _uuid

    if doc_id is None:
        doc_id = str(_uuid.uuid4())

    _UPSERT_GRAPH.invoke({
        "uploaded_file": uploaded_file,
        "collection": collection,
        "embedding_model": embedding_model,
        "doc_id": doc_id,
    })
    return doc_id


# ---------------------------------------------------------------------------
# Retrieval graph nodes
# ---------------------------------------------------------------------------
def embed_query_node(state: RetrieveState) -> RetrieveState:
    """Node: encode the query with the same embedding model used at index time."""
    embedding = state["embedding_model"].encode(state["query"])
    # sentence-transformers returns ndarray; coerce to plain list for state.
    return {"query_embedding": embedding.tolist() if hasattr(embedding, "tolist") else embedding}


def query_chroma_node(state: RetrieveState) -> RetrieveState:
    """Node: query Chroma. Mirrors rag_backend.retrieve_similar_chunks' Chroma call."""
    where_filter = {"doc_id": state["doc_id"]} if state.get("doc_id") else None
    results = state["collection"].query(
        query_embeddings=[state["query_embedding"]],
        n_results=state["top_k"],
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )
    return {"raw_results": results}


def format_results_node(state: RetrieveState) -> RetrieveState:
    """Node: flatten Chroma output into the same dict shape as rag_backend."""
    results = state["raw_results"]
    retrieved_chunks: list[dict] = []
    if results.get("documents"):
        for doc, metadata, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            retrieved_chunks.append({
                "text": doc,
                "metadata": metadata,
                "distance": distance,
            })
    return {"retrieved_chunks": retrieved_chunks}


# ---------------------------------------------------------------------------
# CRAG triage: per-document scoring + correct / ambiguous / incorrect routing
# ---------------------------------------------------------------------------
def score_docs_node(state: RetrieveState) -> RetrieveState:
    """Batched per-document relevance scoring.

    For every retrieved chunk, ask the LLM to assign a score in [0.0, 1.0]
    indicating how well that chunk answers the user's question.

    One batched `llm.with_structured_output(DocScores).invoke(...)` call is
    used (cheaper and more consistent than N per-chunk calls).

    On any structural failure, every chunk defaults to a neutral score of
    `RAG_SCORE_MAX_THRESHOLD` (so it lands in the "correct" bucket) — this
    matches the safer "ambiguous -> keep" CRAG policy.
    """
    query = state["query"]
    retrieved_chunks = state.get("retrieved_chunks") or []

    if not retrieved_chunks:
        return {"doc_scores": []}

    from langchain_core.messages import SystemMessage, HumanMessage

    system_prompt = (
        "You are a document-relevance grader for a retrieval-augmented generation "
        "system. For each candidate document excerpt, assign a relevance score in "
        "[0.0, 1.0] indicating how well it helps answer the user's question. "
        "1.0 = fully answers the question. "
        "0.5 = tangentially related. "
        "0.0 = completely off-topic. "
        "Return one entry per document in the same order they were provided."
    )

    numbered = []
    for i, chunk in enumerate(retrieved_chunks):
        meta = chunk.get("metadata") or {}
        header = f"[doc_id={meta.get('doc_id', '?')}, chunk_index={meta.get('chunk_index', '?')}]"
        numbered.append(f"{i}. {header}\n{chunk.get('text', '')}")
    user_prompt = (
        f"User question:\n{query}\n\n"
        f"Document excerpts (return one score per excerpt, in the same order):\n\n"
        + "\n\n".join(numbered)
    )

    try:
        scorer = _get_doc_scorer()
        verdict: DocScores = scorer.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        raw_scores = [s.model_dump() for s in verdict.scores]
    except Exception:
        # Safer fallback: mark everything as "correct" so refine still runs.
        raw_scores = [
            {
                "doc_id": (c.get("metadata") or {}).get("doc_id", ""),
                "chunk_index": (c.get("metadata") or {}).get("chunk_index", -1),
                "score": RAG_SCORE_MAX_THRESHOLD,
                "reason": "fallback",
            }
            for c in retrieved_chunks
        ]

    # Align by index; clamp score to [0, 1] and fill missing entries.
    aligned: list[dict] = []
    for i, chunk in enumerate(retrieved_chunks):
        meta = chunk.get("metadata") or {}
        s = raw_scores[i] if i < len(raw_scores) and isinstance(raw_scores[i], dict) else None
        try:
            score = float(s["score"]) if s and "score" in s else RAG_SCORE_MAX_THRESHOLD
        except (TypeError, ValueError):
            score = RAG_SCORE_MAX_THRESHOLD
        score = max(0.0, min(1.0, score))
        aligned.append({
            "doc_id": (s.get("doc_id") if s else None) or meta.get("doc_id", ""),
            "chunk_index": (s.get("chunk_index") if s else None) if s and s.get("chunk_index") is not None else meta.get("chunk_index", -1),
            "score": score,
            "reason": (s.get("reason", "") if s else "") or "",
            # Carry the chunk itself so triage can route it without re-fetching.
            "_chunk": chunk,
        })

    return {"doc_scores": aligned}


def triage_docs_node(state: RetrieveState) -> RetrieveState:
    """Route chunks into Correct / Ambiguous / Incorrect buckets by score.

    Buckets:
      - correct:    score >= RAG_SCORE_MAX_THRESHOLD  -> refine
      - ambiguous:  RAG_SCORE_MIN_THRESHOLD <= score < RAG_SCORE_MAX_THRESHOLD
      - incorrect:  score < RAG_SCORE_MIN_THRESHOLD

    For this iteration only the `correct` bucket is wired into the refine
    path. The other two are stashed in state for the placeholder nodes to
    consume later (see `ambiguous_docs_node` / `wrong_docs_node`).
    """
    scores = state.get("doc_scores") or []
    correct: list[dict] = []
    ambiguous: list[dict] = []
    incorrect: list[dict] = []

    for entry in scores:
        chunk = entry.get("_chunk")
        if chunk is None:
            continue
        s = entry.get("score", 0.0)
        # Strip the private carrier key before placing in buckets.
        clean = {
            "text": chunk.get("text", ""),
            "metadata": chunk.get("metadata") or {},
            "distance": chunk.get("distance", 0.0),
            "score": s,
            "reason": entry.get("reason", ""),
        }
        if s >= RAG_SCORE_MAX_THRESHOLD:
            correct.append(clean)
        elif s >= RAG_SCORE_MIN_THRESHOLD:
            ambiguous.append(clean)
        else:
            incorrect.append(clean)

    return {
        "correct_chunks": correct,
        "ambiguous_chunks": ambiguous,
        "incorrect_chunks": incorrect,
    }


def ambiguous_docs_node(state: RetrieveState) -> RetrieveState:
    """Placeholder for the 'ambiguous' branch.

    Will be implemented later — likely a web-search fallback (Tavily) plus
    merge with `correct_chunks` before refinement. For now it just records
    what it received so we can observe behavior in tests / logs.
    """
    return {
        "ambiguous_chunks": state.get("ambiguous_chunks", []),
    }


def wrong_docs_node(state: RetrieveState) -> RetrieveState:
    """Incorrect-branch entry stub.

    The actual work for the wrong branch is split across the three nodes
    that follow this one in the graph:
        wrong_docs -> rewrite_query -> tavily_search -> merge_docs
                                                       -> refine_context

    This stub exists so the conditional router (`_route_after_triage`) has
    a single named destination for the incorrect/ambiguous branch. It
    carries the original `incorrect_chunks` through untouched for
    observability / debugging, and seeds empty slots that downstream nodes
    will populate.
    """
    return {
        "incorrect_chunks": state.get("incorrect_chunks", []),
        "rewritten_query": "",
        "rewritten_query_rationale": "",
    }


def rewrite_query_node(state: RetrieveState) -> RetrieveState:
    """Rewrite the user query into a web-search-friendly keyword query.

    The original `query` is conversational (may have pronouns, filler, or
    rely on chat history); web search engines (Tavily) reward short,
    keyword-rich, entity-rich queries. This node bridges the two.

    Strategy:
      - One `llm.with_structured_output(RewrittenQuery).invoke(...)` call.
      - Falls back to the original `query` if the structured call fails.
      - Writes `state["rewritten_query"]` for `tavily_search_node` to consume.
      - Optionally bypassed via `RAG_QUERY_REWRITE_ENABLED=false` env var.
    """
    original = state.get("query", "") or ""
    if not original:
        return {"rewritten_query": "", "rewritten_query_rationale": ""}

    # Optional kill-switch for A/B testing.
    if os.getenv("RAG_QUERY_REWRITE_ENABLED", "true").lower() in ("0", "false", "no"):
        return {"rewritten_query": original, "rewritten_query_rationale": "rewrite disabled"}

    from langchain_core.messages import SystemMessage, HumanMessage

    system_prompt = (
        "You rewrite user questions into effective web-search queries. "
        "Strip conversational filler, expand acronyms on first use, surface "
        "named entities, prefer noun-phrase structure, and keep the result "
        "under ~20 words. Do NOT answer the question — only rewrite it."
    )
    user_prompt = f"Original question:\n{original}\n\nRewritten web search query:"

    try:
        rewriter = _get_query_rewriter()
        result: RewrittenQuery = rewriter.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        rewritten = (result.query or "").strip() or original
        rationale = (result.rationale or "").strip()
    except Exception as exc:
        # Safer fallback: just use the original query rather than dropping
        # the wrong branch entirely. Surface the exception type in the
        # rationale so failures are visible in state for debugging.
        rewritten = original
        rationale = f"rewrite failed ({type(exc).__name__}); using original"

    return {
        "rewritten_query": rewritten,
        "rewritten_query_rationale": rationale,
    }


def tavily_search_node(state: RetrieveState) -> RetrieveState:
    """Run Tavily on the rewritten query and normalize results to Chroma shape.

    Writes the normalized chunks into `state["correct_chunks"]` so the
    existing `refine_context_node` (after `merge_docs`) can re-use its
    sentence-level filtering unchanged.

    Failure modes are fail-soft:
      - Missing/blank rewritten_query  -> empty web_chunks
      - Tavily exception               -> empty web_chunks
      - Tavily returns no usable text  -> empty web_chunks

    In all three cases, the empty `correct_chunks` flows downstream and
    `refine_context_node` emits the standard fallback string.
    """
    query = state.get("rewritten_query") or state.get("query") or ""
    if not query:
        return {"correct_chunks": [], "tavily_raw_count": 0}

    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        tool = TavilySearchResults(max_results=int(os.getenv("RAG_TAVILY_MAX_RESULTS", "5")))
        raw = tool.invoke({"query": query}) or []
    except Exception:
        raw = []

    web_chunks: list[dict] = []
    for i, r in enumerate(raw):
        text = (r.get("content") or r.get("snippet") or "") if isinstance(r, dict) else ""
        url = (r.get("url") or "") if isinstance(r, dict) else ""
        if not text:
            continue
        web_chunks.append({
            "text": text,
            "metadata": {
                "source": f"tavily: {url}" if url else f"tavily: result {i}",
                "chunk_index": i,
                "doc_id": f"tavily-{url}" if url else f"tavily-{i}",
            },
            "distance": 0.0,
        })

    return {
        "correct_chunks": web_chunks,
        "retrieved_chunks": web_chunks,  # belt-and-braces in case refine falls back
        "tavily_raw_count": len(raw),
    }


def merge_node(state: RetrieveState) -> RetrieveState:
    """Merge local ambiguous chunks with Tavily chunks for the web-fallback path.

    Runs between `tavily_search_node` and `refine_context_node` in the
    incorrect/ambiguous branch. Decides the final input to refinement:

      - If `ambiguous_chunks` is non-empty  -> local ambiguous + Tavily
        (deduped by normalized text hash), so the answer LLM sees both
        possibly-useful local context and fresh web results.
      - Else (only incorrect_chunks present) -> Tavily only.

    Defensive: if `correct_chunks` is non-empty AND no Tavily has run, it
    is preserved untouched (correct branch never augments with web).

    Dedup is hash-based on `text.lower().strip()` plus a length floor to
    avoid spurious matches on very short strings. The first occurrence
    wins, so local ambiguous chunks take precedence over Tavily.
    """
    # Defensive: never augment the correct branch.
    if state.get("correct_chunks") and not state.get("tavily_raw_count"):
        return {
            "correct_chunks": state["correct_chunks"],
            "merge_dropped_count": 0,
            "merge_local_count": len(state["correct_chunks"]),
            "merge_web_count": 0,
        }

    # Web-fallback path. Tavily has populated `correct_chunks` (we re-used
    # the slot so refine_context_node picks it up unchanged). Local
    # ambiguous chunks (if any) live in `ambiguous_chunks`.
    tavily_chunks = state.get("correct_chunks") or []
    ambiguous_chunks = state.get("ambiguous_chunks") or []

    if not ambiguous_chunks:
        # All-incorrect path: Tavily-only.
        return {
            "correct_chunks": tavily_chunks,
            "retrieved_chunks": tavily_chunks,
            "merge_local_count": 0,
            "merge_web_count": len(tavily_chunks),
            "merge_dropped_count": 0,
        }

    # Ambiguous path: merge local ambiguous + Tavily, deduped by text hash.
    _MIN_DEDUP_LEN = 20
    seen_hashes: set[str] = set()
    merged: list[dict] = []
    dropped = 0

    def _hash(text: str) -> str:
        return (text or "").lower().strip()

    # Local ambiguous first (higher embedding-model confidence).
    for chunk in ambiguous_chunks:
        text = (chunk.get("text") or "") if isinstance(chunk, dict) else ""
        h = _hash(text)
        if len(text.strip()) >= _MIN_DEDUP_LEN:
            if h in seen_hashes:
                dropped += 1
                continue
            seen_hashes.add(h)
        merged.append(chunk)

    for chunk in tavily_chunks:
        text = (chunk.get("text") or "") if isinstance(chunk, dict) else ""
        h = _hash(text)
        if len(text.strip()) >= _MIN_DEDUP_LEN:
            if h in seen_hashes:
                dropped += 1
                continue
            seen_hashes.add(h)
        merged.append(chunk)

    return {
        "correct_chunks": merged,
        "retrieved_chunks": merged,
        "merge_local_count": len(ambiguous_chunks),
        "merge_web_count": len(tavily_chunks),
        "merge_dropped_count": dropped,
    }


def _route_after_triage(state: RetrieveState) -> str:
    """Decide which branch to take after triage.

    Routing rules (this iteration):
      - If `correct_chunks` is non-empty  -> refine_context
      - Else (no correct local docs)       -> wrong_docs (Tavily web fallback)

    The `ambiguous` branch is registered as a node but not yet routed-to
    from this function; flip it on when ambiguous_docs_node is fleshed out.
    When the local index returns nothing usable, the wrong_docs branch
    still gives Tavily a chance to surface something useful — better than
    going straight to the empty-context fallback.
    """
    if state.get("correct_chunks"):
        return "refine_context"
    return "wrong_docs"


def _build_sentences(chunks: list[dict]) -> list[dict]:
    """Flatten retrieved chunks into per-sentence records.

    Each record: {text, source, chunk_index, distance}.
    Chunks are processed in retrieval order (already sorted by relevance).
    """
    sentences: list[dict] = []
    for chunk in chunks or []:
        meta = chunk.get("metadata") or {}
        source = meta.get("source", "unknown")
        chunk_index = meta.get("chunk_index", -1)
        distance = chunk.get("distance", 0.0)
        for sent in _split_sentences(chunk.get("text", "")):
            sentences.append({
                "text": sent,
                "source": source,
                "chunk_index": chunk_index,
                "distance": distance,
            })
    return sentences


def refine_context_node(state: RetrieveState) -> RetrieveState:
    """Corrective-RAG refine step.

    Splits retrieved chunks into sentences, asks the LLM (batched, structured
    output) which sentences are relevant to the user's question, then rejoins
    the kept sentences into a refined context string.

    Strategy:
      - One batched `llm.with_structured_output(RelevanceVerdict).invoke(...)`
        over all candidate sentences (faster, cheaper, and more consistent
        than N per-sentence calls).
      - Cap at MAX_SENTENCES_FOR_REFINEMENT. If exceeded, keep the
        highest-relevance tail (smallest distance).
      - Default `keep=True` on parse / lookup failure (safer fallback —
        matches CRAG's "ambiguous -> keep" policy).
      - Drop a chunk entirely if zero of its sentences survived.
      - If no sentences survive, return the empty-context fallback string
        so downstream answer-node behavior is identical to the no-RAG path.
    """
    query = state["query"]
    # Post-triage, refine only sees the `correct` bucket. The
    # ambiguous / incorrect branches are placeholders for now.
    retrieved_chunks = state.get("correct_chunks") or state.get("retrieved_chunks") or []

    if not retrieved_chunks:
        return {
            "sentences": [],
            "verdicts": [],
            "refined_context": "No relevant information found in the indexed documents.",
        }

    # 1) Flatten to sentences (preserving source / chunk_index / distance).
    sentences = _build_sentences(retrieved_chunks)

    if not sentences:
        return {
            "sentences": [],
            "verdicts": [],
            "refined_context": "No relevant information found in the indexed documents.",
        }

    # 2) If too many, trim by smallest distance (most relevant first).
    if len(sentences) > MAX_SENTENCES_FOR_REFINEMENT:
        sentences = sorted(sentences, key=lambda s: s["distance"])[:MAX_SENTENCES_FOR_REFINEMENT]

    # 3) One batched structured LLM call.
    from langchain_core.messages import SystemMessage, HumanMessage

    system_prompt = (
        "You are a relevance filter for a retrieval-augmented generation system. "
        "For each candidate sentence, decide whether it is needed to answer the "
        "user's question. A sentence is KEEP-worthy if it directly helps answer "
        "the question or contains a key fact the answer needs. A sentence is "
        "DROP-worthy if it is off-topic, generic, redundant, or unrelated boilerplate. "
        "When in doubt, prefer KEEP."
    )
    numbered = "\n".join(f"{i}. {s['text']}" for i, s in enumerate(sentences))
    user_prompt = (
        f"User question:\n{query}\n\n"
        f"Candidate sentences (return one verdict per sentence, in the same order):\n{numbered}"
    )

    try:
        checker = _get_relevance_checker()
        verdict: RelevanceVerdict = checker.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        raw_verdicts = [v.model_dump() for v in verdict.verdicts]
    except Exception:
        # Graceful fallback: if structured parsing fails entirely, keep all.
        raw_verdicts = [{"sentence": s["text"], "keep": True, "reason": "fallback"} for s in sentences]

    # 4) Align verdicts with our sentences by index; default keep=True on missing.
    aligned_verdicts: list[dict] = []
    for i, sent in enumerate(sentences):
        v = raw_verdicts[i] if i < len(raw_verdicts) else None
        aligned_verdicts.append({
            "text": sent["text"],
            "source": sent["source"],
            "chunk_index": sent["chunk_index"],
            "keep": bool(v["keep"]) if isinstance(v, dict) and "keep" in v else True,
            "reason": v.get("reason", "") if isinstance(v, dict) else "",
        })

    # 5) Drop chunks where every sentence was rejected, then rejoin.
    kept_by_chunk: dict[tuple, list[dict]] = {}
    for v in aligned_verdicts:
        if not v["keep"]:
            continue
        key = (v["source"], v["chunk_index"])
        kept_by_chunk.setdefault(key, []).append(v)

    refined_parts: list[str] = []
    # Iterate in original chunk order so the final context reads coherently.
    seen_keys: set = set()
    for chunk in retrieved_chunks:
        meta = chunk.get("metadata") or {}
        key = (meta.get("source", "unknown"), meta.get("chunk_index", -1))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if key not in kept_by_chunk:
            continue  # whole chunk dropped
        body = " ".join(v["text"] for v in kept_by_chunk[key])
        if not body.strip():
            continue
        refined_parts.append(
            f"[Source: {key[0]} - Chunk {key[1]}]\n{body}"
        )

    refined_context = "\n\n".join(refined_parts) if refined_parts else "No relevant information found in the indexed documents."

    return {
        "sentences": sentences,
        "verdicts": aligned_verdicts,
        "refined_context": refined_context,
    }


# ---------------------------------------------------------------------------
# Build the retrieval graph:
#   embed_query -> query_chroma -> format_results -> score_docs -> triage_docs
#      triage_docs -> (correct -> refine_context -> END)
#                  | (ambiguous -> ambiguous_docs_node -> END)        [placeholder]
#                  | (incorrect -> wrong_docs_node     -> END)        [placeholder]
#
# For this iteration only the `correct` branch is live (the other two are
# registered as nodes so the wiring is ready, but _route_after_triage always
# returns "refine_context" today). Flipping on the other branches later is a
# one-line change in _route_after_triage plus the implementations of
# `ambiguous_docs_node` / `wrong_docs_node`.
# ---------------------------------------------------------------------------
def _build_retrieve_graph():
    g = StateGraph(RetrieveState)
    g.add_node("embed_query", embed_query_node)
    g.add_node("query_chroma", query_chroma_node)
    g.add_node("format_results", format_results_node)
    g.add_node("score_docs", score_docs_node)
    g.add_node("triage_docs", triage_docs_node)
    g.add_node("refine_context", refine_context_node)
    g.add_node("ambiguous_docs", ambiguous_docs_node)
    g.add_node("wrong_docs", wrong_docs_node)
    g.add_node("rewrite_query", rewrite_query_node)
    g.add_node("tavily_search", tavily_search_node)
    g.add_node("merge_docs", merge_node)

    g.add_edge(START, "embed_query")
    g.add_edge("embed_query", "query_chroma")
    g.add_edge("query_chroma", "format_results")
    g.add_edge("format_results", "score_docs")
    g.add_edge("score_docs", "triage_docs")

    # Conditional routing after triage.
    g.add_conditional_edges(
        "triage_docs",
        _route_after_triage,
        {
            "refine_context": "refine_context",
            "ambiguous_docs": "ambiguous_docs",
            "wrong_docs": "wrong_docs",
        },
    )

    # Correct branch: refine directly off the local correct chunks.
    g.add_edge("refine_context", END)

    # Incorrect / Ambiguous branch (shared):
    #   wrong_docs -> rewrite_query -> tavily_search -> merge_docs
    #              -> refine_context -> END
    g.add_edge("wrong_docs", "rewrite_query")
    g.add_edge("rewrite_query", "tavily_search")
    g.add_edge("tavily_search", "merge_docs")
    g.add_edge("merge_docs", "refine_context")

    # Ambiguous placeholder still goes straight to END if ever routed-to.
    g.add_edge("ambiguous_docs", END)

    return g.compile()


_RETRIEVE_GRAPH = _build_retrieve_graph()


# ---------------------------------------------------------------------------
# Public retrieve API — same signature as rag_backend.retrieve_similar_chunks
# ---------------------------------------------------------------------------
def retrieve_similar_chunks(
    query: str,
    collection,
    embedding_model,
    top_k: int = 5,
    doc_id: str | None = None,
) -> list[dict]:
    """Run the retrieve LangGraph. Returns the raw list of
    {text, metadata, distance} chunks from Chroma (pre-refinement).

    This signature is preserved for backward compatibility — existing callers
    (e.g. api.py) keep working unchanged. For the Corrective-RAG-corrected
    version, use `retrieve_refined_context` or `answer_with_refined_context`.
    """
    result = _RETRIEVE_GRAPH.invoke({
        "query": query,
        "collection": collection,
        "embedding_model": embedding_model,
        "top_k": top_k,
        "doc_id": doc_id,
    })
    return result["retrieved_chunks"]


def retrieve_refined_context(
    query: str,
    collection,
    embedding_model,
    top_k: int = 5,
    doc_id: str | None = None,
) -> str:
    """Run the full retrieve + refine pipeline. Returns the refined context
    string with only the sentences judged relevant to `query` (Corrective RAG).

    Returned string is ready to drop into a prompt as the "context" block.
    If no sentences are kept, returns the standard fallback:
        "No relevant information found in the indexed documents."
    """
    result = _RETRIEVE_GRAPH.invoke({
        "query": query,
        "collection": collection,
        "embedding_model": embedding_model,
        "top_k": top_k,
        "doc_id": doc_id,
    })
    return result["refined_context"]


# ---------------------------------------------------------------------------
# Answer (streaming) — same signature as rag_backend.answer_with_context.
# We keep the exact behavior: build context + system prompt and call
# chatbot.stream(..., stream_mode="messages").
#
# `retrieved_chunks` can be either:
#   - list[dict] of {text, metadata, distance} (raw Chroma output), or
#   - str (an already-refined context — output of retrieve_refined_context).
# ---------------------------------------------------------------------------
def answer_with_context(query: str, retrieved_chunks, chatbot):
    # If the caller hands us a refined-context string, use it as-is.
    if isinstance(retrieved_chunks, str):
        context = retrieved_chunks
        if not context or context.startswith("No relevant information found"):
            return "No relevant information found in the indexed documents."
    else:
        if not retrieved_chunks:
            return "No relevant information found in the indexed documents."
        context = "\n\n".join([
            f"[Source: {chunk['metadata']['source']} - Chunk {chunk['metadata']['chunk_index']}]\n{chunk['text']}"
            for chunk in retrieved_chunks
        ])

    system_prompt = (
        "You are a helpful assistant that answers questions based ONLY on the provided document excerpts. "
        "If the answer is not in the documents, say you don't know."
    )

    from langchain_core.messages import SystemMessage, HumanMessage

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Document excerpts:\n\n{context}\n\nUser question: {query}"),
    ]

    return chatbot.stream({"messages": messages}, config={'configurable': {'thread_id': 'rag'}}, stream_mode="messages")


def answer_with_refined_context(
    query: str,
    collection,
    embedding_model,
    chatbot,
    top_k: int = 5,
    doc_id: str | None = None,
):
    """End-to-end Corrective-RAG: retrieve -> refine -> stream the final answer.

    Returns the same streaming iterator as answer_with_context.
    """
    refined = retrieve_refined_context(
        query=query,
        collection=collection,
        embedding_model=embedding_model,
        top_k=top_k,
        doc_id=doc_id,
    )
    return answer_with_context(query, refined, chatbot)


__all__ = [
    "init_embedding",
    "init_vectorstore",
    "upsert_document",
    "retrieve_similar_chunks",
    "retrieve_refined_context",
    "answer_with_context",
    "answer_with_refined_context",
    "RelevanceItem",
    "RelevanceVerdict",
    "DocScore",
    "DocScores",
    "RewrittenQuery",
    "RAG_SCORE_MIN_THRESHOLD",
    "RAG_SCORE_MAX_THRESHOLD",
    "UploadedFile",
]