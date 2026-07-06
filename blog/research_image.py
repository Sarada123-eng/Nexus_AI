
from __future__ import annotations

import operator
import uuid
import urllib.parse
import requests
import os
import re
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from typing import TypedDict, List, Optional, Literal, Annotated

from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.tools.tavily_search import TavilySearchResults

load_dotenv()

# %%
# -----------------------------
# 1) Schemas
# -----------------------------
class Task(BaseModel):
    id: int
    title: str

    goal: str = Field(
        ...,
        description="One sentence describing what the reader should be able to do/understand after this section.",
    )
    bullets: List[str] = Field(
        ...,
        min_length=3,
        max_length=6,
        description="3–6 concrete, non-overlapping subpoints to cover in this section.",
    )
    target_words: int = Field(..., description="Target word count for this section (120–550).")

    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal["explainer", "tutorial", "news_roundup", "comparison", "system_design"] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task]


class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None  # keep if Tavily provides; DO NOT rely on it
    snippet: Optional[str] = None
    source: Optional[str] = None


class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    queries: List[str] = Field(default_factory=list)


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


class ImageSpec(BaseModel):
    placeholder: str = Field(..., description="e.g. [[IMAGE_1]]")
    filename: str = Field(..., description="Save under images/, e.g. qkv_flow.png")
    alt: str
    caption: str
    prompt: str = Field(..., description="Prompt to send to the image model.")
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"


class ImagePlacement(BaseModel):
    """Which section gets an image and what that image should be."""
    section_title: str = Field(
        ...,
        description="Exact '## <Title>' heading text (without the ## prefix) of the section where the image should appear.",
    )
    image: ImageSpec


class GlobalImagePlan(BaseModel):
    """Placement-based image plan. The model returns ONLY placement decisions, never the blog content."""
    placements: List[ImagePlacement] = Field(default_factory=list)


class State(TypedDict):
    topic: str

    # routing / research
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]

    # workers
    sections: Annotated[List[tuple[int, str]], operator.add]  # (task_id, section_md)

    # reducer/image
    merged_md: str
    image_specs: List[dict]

    final: str


writer_llm = ChatOpenAI(
    model="nvidia/nemotron-3-super-120b-a12b:free",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

gemini_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
)

groq_llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY")
)

openai_llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY")
)

# -----------------------------
# 3) Router (decide upfront)
# -----------------------------
ROUTER_SYSTEM = """You are a routing module for a technical blog planner.

Decide whether web research is needed BEFORE planning.

Modes:
- closed_book (needs_research=false):
  Evergreen topics where correctness does not depend on recent facts (concepts, fundamentals).
- hybrid (needs_research=true):
  Mostly evergreen but needs up-to-date examples/tools/models to be useful.
- open_book (needs_research=true):
  Mostly volatile: weekly roundups, "this week", "latest", rankings, pricing, policy/regulation.

If needs_research=true:
- Output 4-6 high-signal queries.
- Queries should be scoped and specific (avoid generic queries like just "AI" or "LLM").
- If user asked for "last week/this week/latest", reflect that constraint IN THE QUERIES.
"""

def router_node(state: State) -> dict:
    
    topic = state["topic"]
    decider = openai_llm.with_structured_output(RouterDecision)
    decision = decider.invoke(
        [
            SystemMessage(content=ROUTER_SYSTEM),
            HumanMessage(content=f"Topic: {topic}"),
        ]
    )

    return {
        "needs_research": decision.needs_research,
        "mode": decision.mode,
        "queries": decision.queries,
    }

def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"

# -----------------------------
# 4) Research (Tavily)
# -----------------------------

def _tavily_search(query: str, max_results: int = 5) -> List[dict]:

    tool = TavilySearchResults(max_results=max_results)
    results = tool.invoke({"query": query})

    normalized: List[dict] = []

    for r in results or []:
        normalized.append(
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "snippet": r.get("content") or r.get("snippet") or "",
                "published_at": r.get("published_date") or r.get("published_at"),
                "source": r.get("source"),
            }
        )

    return normalized


RESEARCH_SYSTEM = """
You are a research synthesizer for technical writing.

Given research notes, produce a deduplicated list of EvidenceItem objects.

Rules:
- Only include items with a non-empty url.
- Prefer authoritative sources.
- Preserve URLs exactly.
- Keep snippets short.
- Deduplicate by URL.
- Return at most 10 evidence items.
- Prefer authoritative sources over blogs, podcasts, and social posts.
- If published date is unavailable, set published_at=null.
"""


RESEARCH_SUMMARY_SYSTEM = """
You are a research analyst.

Your job is to compress web search results into high-signal research notes.

Keep:
- important facts
- releases
- model names
- framework names
- companies
- organizations
- benchmarks
- dates

Remove:
- duplicated information
- marketing language
- filler
- repeated claims

IMPORTANT:
For every retained fact, preserve the source URL.

Output format:

- Fact or finding
  Source: https://...

Maximum:
- 8 bullets
- 100 words total

Do not invent facts.
Do not invent URLs.
"""


def research_node(state: State) -> dict:

    queries = state.get("queries", []) or []

    if not queries:
        return {"evidence": []}

    max_results = 6

    # --------------------------------------------------
    # STEP 1: Search once and cache results
    # --------------------------------------------------

    search_cache = {}
    raw_results = []

    for q in queries:

        results = _tavily_search(
            q,
            max_results=max_results,
        )

        search_cache[q] = results
        raw_results.extend(results)

    if not raw_results:
        return {"evidence": []}

    # --------------------------------------------------
    # STEP 2: Summarize each query independently
    #         (Nemotron)
    # --------------------------------------------------

    query_summaries = []

    for q in queries:

        query_results = search_cache[q]

        formatted_results = "\n\n".join(
            [
                f"""
Title: {r['title']}
URL: {r['url']}
Published: {r.get('published_at')}
Snippet: {r['snippet']}
                """.strip()
                for r in query_results
            ]
        )

        summary = openai_llm.invoke(
            [
                SystemMessage(
                    content=RESEARCH_SUMMARY_SYSTEM
                ),
                HumanMessage(
                    content=(
                        f"Query:\n{q}\n\n"
                        f"Search Results:\n\n"
                        f"{formatted_results}"
                    )
                ),
            ]
        ).content.strip()

        query_summaries.append(
            f"QUERY: {q}\n{summary}"
        )

    compressed_research = "\n\n".join(
        query_summaries
    )

    # --------------------------------------------------
    # DEBUG
    # --------------------------------------------------

    print("\n========== COMPRESSED RESEARCH ==========\n")
    print(compressed_research[:3000])
    print("\n=========================================\n")

    # --------------------------------------------------
    # STEP 3: GPT-OSS creates EvidencePack
    # --------------------------------------------------

    extractor = openai_llm.with_structured_output(
        EvidencePack
    )

    pack = extractor.invoke(
        [
            SystemMessage(content=RESEARCH_SYSTEM),
            HumanMessage(
                content=(
                    "Create an EvidencePack from these research notes.\n\n"
                    f"{compressed_research}"
                )
            ),
        ]
    )

    # --------------------------------------------------
    # STEP 4: Deduplicate URLs
    # --------------------------------------------------

    dedup = {}

    for e in pack.evidence:

        if e.url:
            dedup[e.url] = e

    evidence = list(dedup.values())

    print(f"\nEvidence count: {len(evidence)}")

    return {
        "evidence": evidence
    }

# -----------------------------
# 5) Orchestrator (Plan)
# -----------------------------
ORCH_SYSTEM = """You are a senior technical writer and developer advocate.
Your job is to produce a highly actionable outline for a technical blog post.

Hard requirements:
- Create 5–9 sections (tasks) suitable for the topic and audience.
- Each task must include:
  1) goal (1 sentence)
  2) 3–6 bullets that are concrete, specific, and non-overlapping
  3) target word count (120–550)

Quality bar:
- Assume the reader is a developer; use correct terminology.
- Bullets must be actionable: build/compare/measure/verify/debug.
- Ensure the overall plan includes at least 2 of these somewhere:
  * minimal code sketch / MWE (set requires_code=True for that section)
  * edge cases / failure modes
  * performance/cost considerations
  * security/privacy considerations (if relevant)
  * debugging/observability tips

Grounding rules:
- Mode closed_book: keep it evergreen; do not depend on evidence.
- Mode hybrid:
  - Use evidence for up-to-date examples (models/tools/releases) in bullets.
  - Mark sections using fresh info as requires_research=True and requires_citations=True.
- Mode open_book:
  - Set blog_kind = "news_roundup".
  - Every section is about summarizing events + implications.
  - DO NOT include tutorial/how-to sections unless user explicitly asked for that.
  - If evidence is empty or insufficient, create a plan that transparently says "insufficient sources"
    and includes only what can be supported.

Output must strictly match the Plan schema.
"""

def orchestrator_node(state: State) -> dict:
    planner = openai_llm.with_structured_output(Plan)

    evidence = state.get("evidence", [])
    mode = state.get("mode", "closed_book")

    plan = planner.invoke(
        [
            SystemMessage(content=ORCH_SYSTEM),
            HumanMessage(
                content=(
                    f"Topic: {state['topic']}\n"
                    f"Mode: {mode}\n\n"
                    f"Evidence (ONLY use for fresh claims; may be empty):\n"
                    f"{[e.model_dump() for e in evidence][:16]}"
                )
            ),
        ]
    )

    return {"plan": plan}

# -----------------------------
# 6) Fanout
# -----------------------------
def fanout(state: State):
    return [
        Send(
            "worker",
            {
                "task": task.model_dump(),
                "topic": state["topic"],
                "mode": state["mode"],
                "plan": state["plan"].model_dump(),
                "evidence": [e.model_dump() for e in state.get("evidence", [])],
            },
        )
        for task in state["plan"].tasks
    ]

# -----------------------------
# 7) Worker (write one section)
# -----------------------------
WORKER_SYSTEM = """You are a senior technical writer and developer advocate.
Write ONE section of a technical blog post in Markdown.

Hard constraints:
- Follow the provided Goal and cover ALL Bullets in order (do not skip or merge bullets).
- Stay close to Target words (±15%).
- Output ONLY the section content in Markdown (no blog title H1, no extra commentary).
- Start with a '## <Section Title>' heading.

Scope guard:
- If blog_kind == "news_roundup": do NOT turn this into a tutorial/how-to guide.
  Do NOT teach web scraping, RSS, automation, or "how to fetch news" unless bullets explicitly ask for it.
  Focus on summarizing events and implications.

Grounding policy:
- If mode == open_book:
  - Do NOT introduce any specific event/company/model/funding/policy claim unless it is supported by provided Evidence URLs.
  - For each event claim, attach a source as a Markdown link: ([Source](URL)).
  - Only use URLs provided in Evidence. If not supported, write: "Not found in provided sources."
- If requires_citations == true:
  - For outside-world claims, cite Evidence URLs the same way.
- Evergreen reasoning is OK without citations unless requires_citations is true.

Code:
- If requires_code == true, include at least one minimal, correct code snippet relevant to the bullets.

Style:
- Short paragraphs, bullets where helpful, code fences for code.
- Avoid fluff/marketing. Be precise and implementation-oriented.
"""

def worker_node(payload: dict) -> dict:
    
    task = Task(**payload["task"])
    plan = Plan(**payload["plan"])
    evidence = [EvidenceItem(**e) for e in payload.get("evidence", [])]
    topic = payload["topic"]
    mode = payload.get("mode", "closed_book")

    bullets_text = "\n- " + "\n- ".join(task.bullets)

    evidence_text = ""
    if evidence:
        evidence_text = "\n".join(
            f"- {e.title} | {e.url} | {e.published_at or 'date:unknown'}".strip()
            for e in evidence[:20]
        )

    section_md = openai_llm.invoke(
        [
            SystemMessage(content=WORKER_SYSTEM),
            HumanMessage(
                content=(
                    f"Blog title: {plan.blog_title}\n"
                    f"Audience: {plan.audience}\n"
                    f"Tone: {plan.tone}\n"
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Constraints: {plan.constraints}\n"
                    f"Topic: {topic}\n"
                    f"Mode: {mode}\n\n"
                    f"Section title: {task.title}\n"
                    f"Goal: {task.goal}\n"
                    f"Target words: {task.target_words}\n"
                    f"Tags: {task.tags}\n"
                    f"requires_research: {task.requires_research}\n"
                    f"requires_citations: {task.requires_citations}\n"
                    f"requires_code: {task.requires_code}\n"
                    f"Bullets:{bullets_text}\n\n"
                    f"Evidence (ONLY use these URLs when citing):\n{evidence_text}\n"
                )
            ),
        ]
    ).content.strip()

    return {"sections": [(task.id, section_md)]}

# ============================================================
# 8) ReducerWithImages (subgraph)
#    merge_content -> decide_images -> generate_and_place_images
# ============================================================
def merge_content(state: State) -> dict:
    print("MERGE CONTENT")
    plan = state["plan"]

    ordered_sections = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]
    body = "\n\n".join(ordered_sections).strip()
    merged_md = f"# {plan.blog_title}\n\n{body}\n"
    return {"merged_md": merged_md}


DECIDE_IMAGES_SYSTEM = """You are an expert technical editor.
Your job is to decide which sections of a blog need images/diagrams.

Rules:
- Max 3 images total.
- Each image must materially improve understanding (diagram/flow/table-like visual).
- Avoid decorative images; prefer technical diagrams with short labels.
- If no images are needed, return an empty placements list.

IMPORTANT — you must NOT return or reproduce the blog content.
You must ONLY return a list of placements. Each placement contains:
  1. section_title: the exact text of a ## heading in the blog (without the ## prefix).
  2. image: an ImageSpec with placeholder, filename, alt, caption, prompt, size, quality.

Number placeholders sequentially: [[IMAGE_1]], [[IMAGE_2]], [[IMAGE_3]].

Return strictly GlobalImagePlan with only the placements field.
"""

def _extract_section_titles(md: str) -> List[str]:
    """Extract all ## heading titles from the merged markdown."""
    return [
        line.lstrip("#").strip()
        for line in md.splitlines()
        if line.startswith("## ")
    ]

def _insert_placeholders(md: str, placements: List[dict]) -> str:
    """Insert [[IMAGE_N]] placeholders directly after their matching ## headings."""
    for p in placements:
        section_title = p["section_title"]
        placeholder = p["image"]["placeholder"]

        # Build a regex that matches the ## heading line (with optional trailing whitespace)
        # and inserts the placeholder on the next line
        pattern = re.compile(
            r"(^##\s+" + re.escape(section_title) + r"\s*$)",
            re.MULTILINE,
        )
        replacement = r"\1" + f"\n\n{placeholder}\n"
        md, count = pattern.subn(replacement, md)

        if count == 0:
            # Fallback: try case-insensitive match
            pattern_ci = re.compile(
                r"(^##\s+" + re.escape(section_title) + r"\s*$)",
                re.MULTILINE | re.IGNORECASE,
            )
            md, _ = pattern_ci.subn(replacement, md)

    return md

def _build_image_context(md: str) -> str:

    sections = []

    current_title = None
    current_content = []

    for line in md.splitlines():

        if line.startswith("## "):

            if current_title:
                preview = " ".join(current_content)[:300]

                sections.append(
                    f"SECTION: {current_title}\n"
                    f"PREVIEW: {preview}\n"
                )

            current_title = line[3:].strip()
            current_content = []

        else:
            current_content.append(line)

    if current_title:
        preview = " ".join(current_content)[:300]

        sections.append(
            f"SECTION: {current_title}\n"
            f"PREVIEW: {preview}\n"
        )

    return "\n\n".join(sections)


def decide_images(state: State) -> dict:
    print("DECIDE IMAGES")
    planner = openai_llm.with_structured_output(GlobalImagePlan)
    merged_md = state["merged_md"]
    plan = state["plan"]
    assert plan is not None

    # Extract section titles to give the LLM a lightweight reference
    section_titles = _extract_section_titles(merged_md)
    titles_list = "\n".join(f"- {t}" for t in section_titles)
    image_context = _build_image_context(merged_md)
    image_plan = planner.invoke(
        [
            SystemMessage(content=DECIDE_IMAGES_SYSTEM),
            HumanMessage(
                content=(
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Topic: {state['topic']}\n\n"
                    f"Section titles in the blog:\n{titles_list}\n\n"
                    "Analyze the blog structure and decide which sections "
                    "would benefit from a diagram or visual. "
                    "Return ONLY the placements list.\n\n"
                    f"Section summaries:\n\n{image_context}"
                )
            ),
        ]
    )

    # Convert placements to dicts
    placements = [p.model_dump() for p in image_plan.placements]

    # Python-side: insert placeholders into the markdown
    md_with_placeholders = _insert_placeholders(merged_md, placements)

    # Flatten image specs for downstream generation
    image_specs = [p["image"] for p in placements]

    return {
        "merged_md": md_with_placeholders,
        "image_specs": image_specs,
    }


def _pollinations_generate_image_bytes(prompt: str) -> bytes:
    """Generate image using Pollinations AI modern unified API.

    Requires: API key from enter.pollinations.ai saved in environment
    variables.
    """
    encoded_prompt = urllib.parse.quote(prompt)

    # 1. Fetch your API key from your environment variables
    api_key = "sk_d2cRhzLrzkVdRsy9PIKBBv0Jb1jeqLuu"

    # 2. Use the unified endpoint path: /image/{prompt}
    url = f"https://gen.pollinations.ai/image/{encoded_prompt}"

    # 3. Supply valid schema parameters
    params = {
        "model": "flux",
        "width": 1024,
        "height": 1024,
        "safe": "true" # Optional: Enables privacy/secret protections if desired
    }
    
    if api_key:
        params["key"] = api_key

    try:
        # requests.get handles query serialization natively
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()

        # Content-type fallback safety check
        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type:
            raise RuntimeError(
                f"Pollinations returned non-image response: {content_type}"
            )

        return response.content

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Pollinations API request failed: {e}")


def generate_and_place_images(state: State) -> dict:
    plan = state["plan"]
    assert plan is not None

    md = state["merged_md"]
    image_specs = state.get("image_specs", []) or []

    # If no images requested, just write merged markdown
    if not image_specs:
        filename = f"{plan.blog_title}.md"
        Path(filename).write_text(md, encoding="utf-8")
        return {"final": md}

    images_dir = Path("images")
    images_dir.mkdir(exist_ok=True)

    for spec in image_specs:
        print(f"Generating image: {spec['prompt'][:80]}...")
        placeholder = spec["placeholder"]
        ext = Path(spec["filename"]).suffix or ".png"
        filename = f"{uuid.uuid4().hex[:12]}{ext}"
        out_path = images_dir / filename

        # generate only if needed
        if not out_path.exists():
            try:
                img_bytes = _pollinations_generate_image_bytes(spec["prompt"])
                out_path.write_bytes(img_bytes)
            except Exception as e:
                # graceful fallback: keep doc usable
                prompt_block = (
                    f"> **[IMAGE GENERATION FAILED]** {spec.get('caption','')}\n>\n"
                    f"> **Alt:** {spec.get('alt','')}\n>\n"
                    f"> **Prompt:** {spec.get('prompt','')}\n>\n"
                    f"> **Error:** {e}\n"
                )
                md = md.replace(placeholder, prompt_block)
                continue

        spec["filename"] = filename
        img_md = f"![{spec['alt']}](images/{filename})\n*{spec['caption']}*"
        md = md.replace(placeholder, img_md)

    filename = f"{plan.blog_title}.md"
    Path(filename).write_text(md, encoding="utf-8")
    return {"final": md, "image_specs": image_specs}

# build reducer subgraph
reducer_graph = StateGraph(State)
reducer_graph.add_node("merge_content", merge_content)
reducer_graph.add_node("decide_images", decide_images)
reducer_graph.add_node("generate_and_place_images", generate_and_place_images)
reducer_graph.add_edge(START, "merge_content")
reducer_graph.add_edge("merge_content", "decide_images")
reducer_graph.add_edge("decide_images", "generate_and_place_images")
reducer_graph.add_edge("generate_and_place_images", END)
reducer_subgraph = reducer_graph.compile()


# -----------------------------
# 9) Build main graph
# -----------------------------
g = StateGraph(State)
g.add_node("router", router_node)
g.add_node("research", research_node)
g.add_node("orchestrator", orchestrator_node)
g.add_node("worker", worker_node)
g.add_node("reducer", reducer_subgraph)

g.add_edge(START, "router")
g.add_conditional_edges("router", route_next, {"research": "research", "orchestrator": "orchestrator"})
g.add_edge("research", "orchestrator")

g.add_conditional_edges("orchestrator", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", END)

app = g.compile()


# -----------------------------
# 10) Runner
# -----------------------------
def run(topic: str, as_of: Optional[str] = None):
    if as_of is None:
        as_of = date.today().isoformat()

    out = app.invoke(
        {
            "topic": topic,
            "mode": "",
            "needs_research": False,
            "queries": [],
            "evidence": [],
            "plan": None,
            "as_of": as_of,
            "recency_days": 7,
            "sections": [],
            "merged_md": "",
            "image_specs": [],
            "final": "",
        }
    )

    return out


if __name__ == "__main__":
    out = run("Single-Agent vs Multi-Agent Architectures")
    print(out["final"])  # print first 1000 chars of final markdown




# from langchain_openai import ChatOpenAI
# import os

# llm = ChatOpenAI(
#     model="nvidia/nemotron-3-super-120b-a12b:free",
#     api_key=os.getenv("OPENROUTER_API_KEY"),
#     base_url="https://openrouter.ai/api/v1",
# )

# class Test(BaseModel):
#     message: str
#     category: Literal["greeting", "farewell", "question"]


# SYSTEM_MSG = """You are a helpful assistant that categorizes messages into one of three categories: greeting, farewell, or question.
# - If the message is a greeting (e.g., "Hello", "Hi there"), categorize it as "greeting".
# - If the message is a farewell (e.g., "Goodbye", "See you later"), categorize it as "farewell".
# - If the message is a question (e.g., "What is the weather today?"), categorize it as "question".
# - Return the result as a JSON object with two fields: "message" (the original message) and "category" (the determined category)."""

# res = openai_llm.with_structured_output(Test).invoke([
#     SystemMessage(content=SYSTEM_MSG),
#     HumanMessage(content="Hello, how are you?")])
# print(res)


# %%
