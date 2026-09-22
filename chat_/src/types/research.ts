// ─────────────────────────────────────────────────
// Research Agent – shared type definitions
// Mirrors schemas from blog/research_image.py
// ─────────────────────────────────────────────────

export interface Task {
  id: number;
  title: string;
  goal: string;
  bullets: string[];
  target_words: number;
  tags: string[];
  requires_research: boolean;
  requires_citations: boolean;
  requires_code: boolean;
}

export interface Plan {
  blog_title: string;
  audience: string;
  tone: string;
  blog_kind:
    | "explainer"
    | "tutorial"
    | "news_roundup"
    | "comparison"
    | "system_design";
  constraints: string[];
  tasks: Task[];
}

export interface EvidenceItem {
  title: string;
  url: string;
  published_at?: string | null;
  snippet?: string | null;
  source?: string | null;
}

export interface ImageSpec {
  placeholder: string;
  filename: string;
  alt: string;
  caption: string;
  prompt: string;
  size: "1024x1024" | "1024x1536" | "1536x1024";
  quality: "low" | "medium" | "high";
}

// ─── API response types ──────────────────────────

export type NodeStatus = "idle" | "running" | "completed" | "failed";

export interface LogEntry {
  node: string;
  message: string;
  timestamp?: string;
}

export interface ResearchJobStatus {
  node: string;
  progress: number;
  logs: LogEntry[];
}

export interface ResearchJobState {
  plan: Plan | null;
  evidence: EvidenceItem[];
  markdown: string;
  images: ImageSpec[];
}

export interface ResearchNode {
  name: string;
  label: string;
  status: NodeStatus;
}

export interface PastBlog {
  job_id: string;
  topic: string;
  created_at: string;
  status: "running" | "completed" | "failed";
}

// ─── Pipeline node names ─────────────────────────

export const PIPELINE_NODES: { name: string; label: string }[] = [
  { name: "router", label: "Router" },
  { name: "research", label: "Research" },
  { name: "orchestrator", label: "Orchestrator" },
  { name: "worker", label: "Workers" },
  { name: "reducer", label: "Reducer" },
  { name: "images", label: "Images" },
];
