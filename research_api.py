"""
Research Agent API – FastAPI router
------------------------------------
Exposes three endpoints consumed by the Next.js frontend:

  POST  /research/start           → kick off a research job
  GET   /research/{job_id}/status → poll pipeline progress
  GET   /research/{job_id}/state  → fetch accumulated artefacts
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# ── Import the compiled LangGraph pipeline ──────────────
from blog.research_image import app as research_graph, State, Plan, EvidenceItem

# ── Router ──────────────────────────────────────────────
router = APIRouter(prefix="/research", tags=["research"])

# ── In-memory job store ─────────────────────────────────
# Maps job_id → job metadata.  Good enough for single-server dev;
# swap for Redis / DB in production.

class JobRecord(BaseModel):
    job_id: str
    topic: str
    status: str = "queued"           # queued | running | complete | failed
    current_node: str = ""
    progress: float = 0.0
    logs: list[dict] = Field(default_factory=list)
    error: str | None = None

    # Accumulated state artefacts
    plan: dict | None = None
    evidence: list[dict] = Field(default_factory=list)
    markdown: str = ""
    images: list[dict] = Field(default_factory=list)


_jobs: dict[str, JobRecord] = {}


# ── Request / response schemas ──────────────────────────

class StartRequest(BaseModel):
    topic: str = Field(min_length=1)
    as_of: str | None = None         # ISO date string, e.g. "2026-06-20"


class StartResponse(BaseModel):
    job_id: str


# ── Background runner ───────────────────────────────────

def _add_log(job: JobRecord, node: str, message: str):
    """Append a log entry and update current_node."""
    from datetime import datetime
    job.logs.append({
        "node": node,
        "message": message,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    job.current_node = node


async def _run_pipeline(job_id: str, topic: str, as_of: str):
    """Execute the LangGraph research pipeline and stream progress updates node-by-node."""
    job = _jobs[job_id]
    job.status = "running"
    completed_tasks = set()

    try:
        _add_log(job, "router", f"Starting pipeline for topic: {topic}")
        job.progress = 5

        async for event in research_graph.astream(
            {
                "topic": topic,
                "mode": "",
                "needs_research": False,
                "queries": [],
                "evidence": [],
                "plan": None,
                "sections": [],
                "merged_md": "",
                "image_specs": [],
                "final": "",
            }
        ):
            # Process node-by-node completion events
            for node_name, state_update in event.items():
                if node_name == "router":
                    needs_research = state_update.get("needs_research", False)
                    mode = state_update.get("mode", "closed_book")
                    queries = state_update.get("queries", [])
                    _add_log(job, "router", f"Router finished. Needs research: {needs_research} ({mode} mode)")
                    if queries:
                        _add_log(job, "router", f"Formulated queries: {', '.join(queries)}")
                    job.progress = 15

                elif node_name == "research":
                    evidence = state_update.get("evidence", [])
                    job.evidence = [
                        (e.model_dump() if hasattr(e, "model_dump") else e)
                        for e in evidence
                    ]
                    _add_log(job, "research", f"Research finished. Gathered {len(evidence)} evidence sources.")
                    job.progress = 30

                elif node_name == "orchestrator":
                    plan = state_update.get("plan")
                    if plan:
                        job.plan = plan.model_dump() if hasattr(plan, "model_dump") else plan
                        _add_log(job, "orchestrator", f"Orchestrator generated outline plan: '{plan.blog_title}' with {len(plan.tasks)} sections.")
                    job.progress = 50

                elif node_name == "worker":
                    sections = state_update.get("sections", [])
                    for s in sections:
                        if isinstance(s, tuple) and len(s) > 0:
                            completed_tasks.add(s[0])
                    total_sections = len(job.plan.get("tasks", [])) if job.plan else 1
                    completed_count = len(completed_tasks)
                    _add_log(job, "worker", f"Completed section {completed_count} of {total_sections}.")
                    job.progress = 50 + int((completed_count / total_sections) * 35)

                elif node_name in ("reducer", "merge_content", "decide_images", "generate_and_place_images"):
                    final = state_update.get("final", "")
                    merged = state_update.get("merged_md", "")
                    image_specs = state_update.get("image_specs", [])

                    if final or merged:
                        job.markdown = final or merged
                    if image_specs:
                        job.images = image_specs

                    if node_name == "merge_content":
                        _add_log(job, "reducer", "Merging draft sections...")
                        job.progress = 85
                    elif node_name == "decide_images":
                        _add_log(job, "images", "Planning image generation placements...")
                        job.progress = 90
                    elif node_name == "generate_and_place_images":
                        _add_log(job, "images", "Generating images and creating final blog post...")
                        job.progress = 95
                    else:  # parent "reducer" finished
                        _add_log(job, "reducer", "Completed rendering and formatting.")
                        job.progress = 98

        # Mark job as fully complete once stream finishes
        job.status = "complete"
        job.current_node = "complete"
        job.progress = 100
        _add_log(job, "complete", "Pipeline finished successfully")

    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.progress = 0
        _add_log(job, "error", str(exc))


# ── Endpoints ───────────────────────────────────────────

@router.post("/start", response_model=StartResponse)
async def start_research(body: StartRequest):
    job_id = uuid.uuid4().hex[:12]
    as_of = body.as_of or date.today().isoformat()

    job = JobRecord(job_id=job_id, topic=body.topic)
    _jobs[job_id] = job

    # Fire and forget – the pipeline runs in the background
    asyncio.create_task(_run_pipeline(job_id, body.topic, as_of))

    return StartResponse(job_id=job_id)


@router.get("/{job_id}/status")
async def get_status(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "node": job.current_node,
        "progress": job.progress,
        "logs": job.logs,
    }


@router.get("/{job_id}/state")
async def get_state(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "plan": job.plan,
        "evidence": job.evidence,
        "markdown": job.markdown,
        "images": job.images,
    }
