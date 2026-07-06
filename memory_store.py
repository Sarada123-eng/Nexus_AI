import os

from dotenv import load_dotenv
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore

load_dotenv()

DB_URI = os.getenv(
    "POSTGRESQL_CONNECTION_STRING",
    "postgresql://postgres:postgres@localhost:5442/postgres?sslmode=disable",
)
_store_context = None
_store: BaseStore | None = None


def _seed_default_memories(store: BaseStore) -> None:
    user_id = "u1"
    user_details = ("user", user_id, "details")

    store.put(user_details, "profile1", {"data": "Name: Sarada Prasanna Das, Age: 19, Occupation: Student at IIT Bhubaneswar"})
    store.put(user_details, "profile2", {"data": "Prefers answers with examples and code snippets, enjoys learning through hands-on projects, and values clear explanations."})
    store.put(user_details, "profile3", {"data": "Interested in AI, machine learning, and data science. Enjoys exploring new technologies and frameworks."})
    store.put(user_details, "profile4", {"data": "Likes example in python, JavaScript, and C++. Enjoys working on small projects and contributing to open-source."})
    store.put(user_details, "profile5", {"data": "Learning Langgraph to build intelligent applications that can understand and respond to user queries effectively."})


def memory_store_factory() -> BaseStore:
    global _store_context, _store

    if _store is not None:
        return _store

    try:
        _store_context = PostgresStore.from_conn_string(DB_URI)
        _store = _store_context.__enter__()
        _store.setup()
    except Exception as exc:
        print("Postgres memory store unavailable; using in-memory store:", exc)
        _store_context = None
        _store = InMemoryStore()

    _seed_default_memories(_store)
    return _store

def system_prompt_factory(user_detail_context: str) -> str:
    SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant with memory capabilities.
If user-specific memory is available, use it to personalize 
your responses based on what you know about the user.

Your goal is to provide relevant, friendly, and tailored 
assistance that reflects the user's preferences, context, and past interactions.

If the user's name or relevant personal context is available, always personalize your responses by:
- Always Address the user by name (e.g., "Sure, Nitish...") when appropriate
- Referencing known projects, tools, or preferences (e.g., "your MCP server python based project")
- Adjusting the tone to feel friendly, natural, and directly aimed at the user

Avoid generic phrasing when personalization is possible. For example, instead of "In [context]",
say "Since your project is built with TypeScript..."

Use personalization especially in:
- Greetings and transitions
- Help or guidance tailored to tools and frameworks the user uses
- Follow-up messages that continue from past context

Always ensure that personalization is based only on known user details and not assume

In the end suggest 3 relevant furthur question based on the user context and preferences and response.The questions should be relevant to the user context and preferences and should be in a friendly tone.
The user context and preferences are as follows:
{user_detail_context}
"""

    return SYSTEM_PROMPT_TEMPLATE
