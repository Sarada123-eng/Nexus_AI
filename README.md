# LangGraph AI Workspace

A full-stack AI assistant built with **LangGraph**, **FastAPI**, **Next.js**, and **ChromaDB**. The application supports conversational chat with persistent threads, tool calling, long-term user memory, document-grounded RAG, and an asynchronous research workflow that can produce illustrated Markdown articles.

## What it does

- Streams assistant responses over Server-Sent Events (SSE).
- Persists conversations and thread metadata in SQLite through LangGraph checkpoints.
- Stores long-term user-specific memory with the LangGraph store.
- Accepts TXT, PDF, and DOCX uploads and indexes them in a local ChromaDB collection.
- Answers document questions with corrective RAG and source metadata.
- Runs a multi-step research graph for planning, evidence collection, writing, and image placement.
- Provides a Next.js web client in [`chat_`](chat_/).
- Supports optional MCP tools, including the separate Manim MCP service in [`manim-mcp-server/`](manim-mcp-server/).

## Architecture

```text
Next.js client (chat_)
        │ HTTP / SSE
        ▼
FastAPI application (api.py)
        ├── LangGraph chatbot and tool calling (backend.py)
        ├── SQLite checkpoints and thread metadata (chatbot_db.py)
        ├── LangGraph user memory (memory_store.py)
        ├── ChromaDB + sentence-transformers RAG (rag_backend.py)
        ├── Corrective RAG workflow (rag_workflow.py)
        └── Research router and pipeline (research_api.py, blog/research_image.py)

External providers: Groq, OpenAI, Google, Tavily, and optional MCP servers
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `api.py` | FastAPI application and HTTP/SSE endpoints |
| `backend.py` | LangGraph chatbot, tools, memory, and MCP integration |
| `chatbot_db.py` | SQLite persistence and checkpoint helpers |
| `memory_store.py` | Long-term memory configuration and prompts |
| `rag_backend.py` | File extraction, chunking, embeddings, and ChromaDB access |
| `rag_workflow.py` | Corrective RAG retrieval and refinement |
| `research_api.py` | Research job API exposed under `/research` |
| `blog/research_image.py` | LangGraph research and illustrated-article pipeline |
| `images/` | Static images served by the API |
| `chat_/` | Next.js frontend application |
| `manim-mcp-server/` | Optional MCP server for Manim animation rendering |
| `practice/`, `*.ipynb`, and scratch scripts | Local learning material; intentionally ignored by Git |

## Prerequisites

- Python 3.11 or newer recommended.
- Node.js 20 or newer and npm.
- A model provider API key. Groq is the default chat provider in the current implementation.
- Optional: Tavily for web research, Google/OpenAI providers for workflow features, and a configured MCP chatbot server.
- Optional: Manim and its system dependencies if animation generation is enabled.

The repository currently does not include a Python lockfile or dependency manifest. Install the Python packages used by the modules in your environment, or create a project-specific `requirements.txt`/`pyproject.toml` before deploying.

## Local setup

### 1. Configure the backend

Create a local `.env` from [`.env.example`](.env.example) and fill in only the provider keys required by your workflow:

- `GROQ_API_KEY` — chat model and title generation.
- `TAVILY_API_KEY` — web research and retrieval fallback.
- `OPENAI_API_KEY`, `GOOGLE_API_KEY`, and `OPENROUTER_API_KEY` — provider-specific workflow integrations.
- `SERVER_ACTIVATE` and `SERVER_MAIN` — optional absolute paths to the local MCP chatbot server.

Never commit `.env`, OAuth credentials, `token.json`, or provider keys. Rotate any key that has ever been committed or embedded in source code.

### 2. Install and run the API

From the repository root, create and activate a virtual environment, install the required Python dependencies, then start FastAPI with Uvicorn:

```text
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

The first startup may download the `sentence-transformers/all-MiniLM-L6-v2` embedding model. Local runtime data is written to ignored files such as `chatbot.db` and `chroma_db/`.

### 3. Install and run the web client

```text
cd chat_
npm install
npm run dev
```

Open <http://localhost:3000>. The frontend expects the API at its configured backend URL; inspect `chat_/src/` for the current client configuration before changing ports or deploying.

For a production frontend build:

```text
npm run build
npm run start
```

## API overview

The API is served at <http://127.0.0.1:8000>. Interactive OpenAPI documentation is available at `/docs` while the development server is running.

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | Reports chatbot readiness and initialization errors |
| `GET` | `/threads` | Lists conversation threads |
| `POST` | `/threads` | Creates a thread |
| `DELETE` | `/threads` | Deletes local chat data |
| `GET` | `/threads/{thread_id}/messages` | Reads persisted messages |
| `POST` | `/threads/{thread_id}/documents` | Uploads a TXT, PDF, or DOCX document |
| `GET` | `/threads/{thread_id}/documents` | Lists documents attached to a thread |
| `DELETE` | `/threads/{thread_id}/documents/{doc_id}` | Removes an indexed document |
| `POST` | `/chat` | Synchronous chat response; set `use_rag` for document grounding |
| `POST` | `/chat/stream` | SSE chat stream with token, tool, source, and completion events |
| `POST` | `/research/start` | Starts an asynchronous research job |
| `GET` | `/research/{job_id}/status` | Reads research progress and logs |
| `GET` | `/research/{job_id}/state` | Reads the current research artefacts |
| `GET` | `/images/{filename}` | Serves generated/static images |

A chat request requires `message`, `thread_id`, and `user_id`; `use_rag` is optional and defaults to `false`.

## Data and persistence

Local application state is deliberately excluded from version control:

- `chatbot.db` — SQLite checkpointer and thread data.
- `chroma_db/` — persisted vector embeddings and document chunks.
- `media/` — generated media output.
- `.env`, `credentials.json`, and `token.json` — local secrets and OAuth state.

Deleting these files resets local state. Do not use the development SQLite/Chroma layout as a multi-worker production data store without introducing shared, durable services and migrations.

## Optional MCP integration

The repository contains the MCP client configuration, but it does **not** contain the separate chatbot MCP server referenced by `SERVER_ACTIVATE` and `SERVER_MAIN`. A person forking this repository does not need to write that server from scratch: they can either:

1. Clone/install their own compatible chatbot MCP server and set both variables to local absolute paths; or
2. Leave both variables empty and run with the built-in tools only.

When both variables are configured, `backend.py` launches that server over stdio. If it cannot connect, the application falls back to built-in tools and logs the failure. The paths must be changed for every developer machine; the old machine-specific paths are intentionally not part of the project.

The Manim service is maintained separately in [`manim-mcp-server/README.md`](manim-mcp-server/README.md). Configure its executable path and run it independently; do not commit generated videos or temporary render directories.

## What a forked setup owns

Each local installation needs its own provider API keys, OAuth credentials if Google Calendar is enabled, and local runtime data. No database dump is required in the repository:

- `chatbot.db` is created automatically by `chatbot_db.py` when the backend starts and stores local threads, messages, and document mappings.
- `chroma_db/` is created automatically on first RAG initialization and stores local document embeddings.
- Uploading documents through the API populates that user's local Chroma collection; another developer does not receive your indexed documents.
- Deleting these ignored files resets the local installation.

For production or multiple API workers, replace these local stores with shared managed persistence and add migrations, backups, authentication, and data-retention policies.

## Development checks

Before opening a pull request:

1. Verify `GET /health` and the core chat flow.
2. Test a new thread, message history, document upload, RAG query, and research job.
3. Run the frontend lint and production build from `chat_/`.
4. Add automated tests as behavior becomes stable; the current workspace does not yet provide a complete test suite.
5. Confirm `git status` does not contain secrets, databases, model caches, or generated media.

## Production hardening checklist

This project should be hardened before production use:

- Add authentication and authorization for users, threads, documents, and research jobs.
- Replace the in-memory research job registry with a durable queue and shared status store such as Redis plus a worker system.
- Move SQLite and local ChromaDB to managed/shared persistence for multi-instance deployments.
- Add request limits, upload-size/type validation, timeouts, retry policies, and structured logging.
- Restrict CORS to the deployed frontend origin and configure HTTPS.
- Add secret management, key rotation, dependency pinning, vulnerability scanning, and CI.
- Add metrics, tracing, error reporting, health/readiness probes, and backup/retention policies.
- Review prompt-injection and untrusted-document defenses before enabling external research or tool execution.

## Contributing

Create a focused branch, keep generated and practice material out of commits, document configuration changes, and include tests or a reproducible verification procedure with each feature. Keep secrets and user data out of issues and pull requests.

## License

 The optional Manim MCP service has its own license information in [`manim-mcp-server/LICENSE.txt`](manim-mcp-server/LICENSE.txt).
