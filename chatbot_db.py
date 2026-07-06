import sqlite3
import asyncio
from datetime import datetime

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect(database="chatbot.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

class _AsyncFallback:
    """Expose sync saver reads through asyncio threads."""

    def __init__(self, sync_obj):
        self._sync = sync_obj

    def __getattr__(self, name):
        if name.startswith("a"):
            sync_name = name[1:]
            if hasattr(self._sync, sync_name):
                async def _wrapper(*args, **kwargs):
                    return await asyncio.to_thread(
                        getattr(self._sync, sync_name), *args, **kwargs
                    )

                return _wrapper

        return getattr(self._sync, name)


async_checkpointer = _AsyncFallback(checkpointer)


def ensure_threads_table():
    """Create a simple threads metadata table to persist titles and minimal info."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            name TEXT,
            title TEXT,
            title_generated INTEGER,
            created_at TEXT
        )
        """
    )
    conn.commit()



def upsert_thread_meta(thread_id: str, name: str, title: str, title_generated: bool = False, created_at: str | datetime | None = None):
    """Insert or update a thread's metadata in the local SQLite store."""
    ensure_threads_table()
    if created_at is None:
        created_at_iso = datetime.now().isoformat()
    elif isinstance(created_at, datetime):
        created_at_iso = created_at.isoformat()
    else:
        created_at_iso = str(created_at)

    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO threads (thread_id, name, title, title_generated, created_at) VALUES (?, ?, ?, ?, ?)",
        (thread_id, name, title, 1 if title_generated else 0, created_at_iso),
    )
    conn.commit()


async def async_upsert_thread_meta(thread_id: str, name: str, title: str, title_generated: bool = False, created_at: str | datetime | None = None):
    """Async wrapper for upsert_thread_meta that runs the sync implementation in a thread."""
    await asyncio.to_thread(upsert_thread_meta, thread_id, name, title, title_generated, created_at)



def get_all_thread_metas() -> dict:
    """Return a mapping of thread_id -> metadata dict for persisted threads."""
    ensure_threads_table()
    cur = conn.cursor()
    cur.execute("SELECT thread_id, name, title, title_generated, created_at FROM threads")
    rows = cur.fetchall()
    result: dict = {}
    for thread_id, name, title, title_generated, created_at in rows:
        created = None
        try:
            created = datetime.fromisoformat(created_at) if created_at else None
        except Exception:
            created = None

        result[thread_id] = {
            "name": name,
            "title": title,
            "title_generated": bool(title_generated),
            "created_at": created,
        }

    return result

def get_single_thread_meta(thread_id: str) -> dict | None:
    """Return metadata dict for a single thread_id, or None if not found."""
    ensure_threads_table()
    cur = conn.cursor()
    cur.execute("SELECT thread_id, name, title, title_generated, created_at FROM threads WHERE thread_id = ?", (thread_id,))
    row = cur.fetchone()
    if row is None:
        return None

    thread_id, name, title, title_generated, created_at = row
    created = None
    try:
        created = datetime.fromisoformat(created_at) if created_at else None
    except Exception:
        created = None

    return {
        "name": name,
        "title": title,
        "title_generated": bool(title_generated),
        "created_at": created,
    }

async def async_get_single_thread_meta(thread_id: str) -> dict | None:
    """Async wrapper for get_single_thread_meta that runs the sync implementation in a thread."""
    return await asyncio.to_thread(get_single_thread_meta, thread_id)


async def async_get_all_thread_metas() -> dict:
    """Async wrapper returning the same mapping as `get_all_thread_metas`."""
    return await asyncio.to_thread(get_all_thread_metas)



def delete_all_thread_metas():
    """Remove all saved thread metadata (used by Clear All Chats UI action)."""
    ensure_threads_table()
    cur = conn.cursor()
    cur.execute("DELETE FROM threads")
    conn.commit()


async def async_delete_all_thread_metas():
    await asyncio.to_thread(delete_all_thread_metas)



def delete_all_chats_data():
    """Remove all saved chat metadata, checkpointed message history, and documents."""
    ensure_threads_table()
    ensure_thread_documents_table()
    cur = conn.cursor()
    cur.execute("DELETE FROM threads")
    cur.execute("DELETE FROM checkpoints")
    cur.execute("DELETE FROM thread_documents")
    conn.commit()


async def async_delete_all_chats_data():
    await asyncio.to_thread(delete_all_chats_data)


def ensure_thread_documents_table():
    """Create a table to map threads to document vector IDs and filenames."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS thread_documents (
            thread_id TEXT,
            doc_id TEXT PRIMARY KEY,
            filename TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()


def add_thread_document(thread_id: str, doc_id: str, filename: str):
    ensure_thread_documents_table()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO thread_documents (thread_id, doc_id, filename, created_at) VALUES (?, ?, ?, ?)",
        (thread_id, doc_id, filename, datetime.now().isoformat()),
    )
    conn.commit()


async def async_add_thread_document(thread_id: str, doc_id: str, filename: str):
    await asyncio.to_thread(add_thread_document, thread_id, doc_id, filename)


def get_thread_documents(thread_id: str) -> list[dict]:
    ensure_thread_documents_table()
    cur = conn.cursor()
    cur.execute("SELECT doc_id, filename FROM thread_documents WHERE thread_id = ?", (thread_id,))
    rows = cur.fetchall()
    return [{"doc_id": row[0], "filename": row[1]} for row in rows]


async def async_get_thread_documents(thread_id: str) -> list[dict]:
    return await asyncio.to_thread(get_thread_documents, thread_id)


def delete_thread_document(thread_id: str, doc_id: str):
    ensure_thread_documents_table()
    cur = conn.cursor()
    cur.execute("DELETE FROM thread_documents WHERE thread_id = ? AND doc_id = ?", (thread_id, doc_id))
    conn.commit()


async def async_delete_thread_document(thread_id: str, doc_id: str):
    await asyncio.to_thread(delete_thread_document, thread_id, doc_id)



def retrieve_thread_messages(thread_id: str) -> list[BaseMessage]:
    checkpoint_tuple = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    if checkpoint_tuple:
        return checkpoint_tuple.checkpoint["channel_values"].get("messages", [])

    return []


async def async_retrieve_thread_messages(thread_id: str) -> list[BaseMessage]:
    # Use async_checkpointer.aget_tuple when available for efficient async access.
    try:
        checkpoint_tuple = await async_checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    except Exception:
        # Fallback to running the sync getter in a thread
        checkpoint_tuple = await asyncio.to_thread(checkpointer.get_tuple, {"configurable": {"thread_id": thread_id}})

    if checkpoint_tuple:
        return checkpoint_tuple.checkpoint["channel_values"].get("messages", [])

    return []
