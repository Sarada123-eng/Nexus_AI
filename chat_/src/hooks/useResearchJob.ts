"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type {
  ResearchJobStatus,
  ResearchJobState,
  LogEntry,
  ResearchNode,
  PastBlog,
} from "@/types/research";
import { apiUrl } from "@/lib/api";

const POLL_INTERVAL_MS = 2000;

const NODES: { name: string; label: string }[] = [
  { name: "router", label: "Router" },
  { name: "research", label: "Research" },
  { name: "orchestrator", label: "Orchestrator" },
  { name: "worker", label: "Workers" },
  { name: "reducer", label: "Reducer" },
  { name: "images", label: "Images" },
];

// ─── Helpers ──────────────────────────────────────

function buildNodeList(currentNode: string): ResearchNode[] {
  const order = NODES.map((n) => n.name);
  const currentIdx = order.indexOf(currentNode);

  return NODES.map((n, idx) => {
    let status: ResearchNode["status"] = "idle";
    if (currentIdx < 0) {
      status = "idle";
    } else if (idx < currentIdx) {
      status = "completed";
    } else if (idx === currentIdx) {
      status = "running";
    }
    return { name: n.name, label: n.label, status };
  });
}

// ─── Past blogs localStorage ──────────────────────

const STORAGE_KEY = "echobox_past_blogs";

function loadPastBlogs(): PastBlog[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PastBlog[]) : [];
  } catch {
    return [];
  }
}

function savePastBlogs(blogs: PastBlog[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(blogs));
}

// ─── Hook ─────────────────────────────────────────

export function useResearchJob() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [currentNode, setCurrentNode] = useState("");
  const [nodes, setNodes] = useState<ResearchNode[]>(
    NODES.map((n) => ({ ...n, status: "idle" as const }))
  );
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [state, setState] = useState<ResearchJobState>({
    plan: null,
    evidence: [],
    markdown: "",
    images: [],
  });
  const [pastBlogs, setPastBlogs] = useState<PastBlog[]>(loadPastBlogs);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Stop polling ──────────────────────────────
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // ── Poll status + state ───────────────────────
  const poll = useCallback(
    async (id: string) => {
      try {
        const [statusRes, stateRes] = await Promise.all([
          fetch(apiUrl(`/research/${id}/status`)),
          fetch(apiUrl(`/research/${id}/state`)),
        ]);

        if (statusRes.ok) {
          const statusData: ResearchJobStatus = await statusRes.json();
          setProgress(statusData.progress);
          setCurrentNode(statusData.node);
          setNodes(buildNodeList(statusData.node));
          setLogs(statusData.logs ?? []);

          // Check for completion
          if (statusData.progress >= 100 || statusData.node === "complete") {
            setIsRunning(false);
            stopPolling();
            setNodes((prev) =>
              prev.map((n) => ({ ...n, status: "completed" as const }))
            );
            // Update past blog status
            setPastBlogs((prev) => {
              const updated = prev.map((b) =>
                b.job_id === id ? { ...b, status: "completed" as const } : b
              );
              savePastBlogs(updated);
              return updated;
            });
          }
        }

        if (stateRes.ok) {
          const stateData: ResearchJobState = await stateRes.json();
          setState(stateData);
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    },
    [stopPolling]
  );

  // ── Start a job ───────────────────────────────
  const startJob = useCallback(
    async (topic: string, asOfDate?: string) => {
      setError(null);
      setProgress(0);
      setCurrentNode("");
      setLogs([]);
      setState({ plan: null, evidence: [], markdown: "", images: [] });
      setNodes(NODES.map((n) => ({ ...n, status: "idle" as const })));

      try {
        const body: Record<string, string> = { topic };
        if (asOfDate) body.as_of = asOfDate;

        const res = await fetch(apiUrl("/research/start"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (!res.ok) {
          throw new Error(`Failed to start research (${res.status})`);
        }

        const data: { job_id: string } = await res.json();
        setJobId(data.job_id);
        setIsRunning(true);

        // Save to past blogs
        const newBlog: PastBlog = {
          job_id: data.job_id,
          topic,
          created_at: new Date().toISOString(),
          status: "running",
        };
        setPastBlogs((prev) => {
          const updated = [newBlog, ...prev];
          savePastBlogs(updated);
          return updated;
        });

        // Start polling
        stopPolling();
        pollRef.current = setInterval(() => {
          void poll(data.job_id);
        }, POLL_INTERVAL_MS);

        // Immediate first poll
        void poll(data.job_id);
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Failed to start research job";
        setError(message);
        setIsRunning(false);
      }
    },
    [poll, stopPolling]
  );

  // ── Load a past job ───────────────────────────
  const loadJob = useCallback(
    async (id: string) => {
      setJobId(id);
      setError(null);
      setIsRunning(false);
      stopPolling();
      try {
        const stateRes = await fetch(apiUrl(`/research/${id}/state`));
        if (stateRes.ok) {
          const stateData: ResearchJobState = await stateRes.json();
          setState(stateData);
        }
        const statusRes = await fetch(apiUrl(`/research/${id}/status`));
        if (statusRes.ok) {
          const statusData: ResearchJobStatus = await statusRes.json();
          setProgress(statusData.progress);
          setCurrentNode(statusData.node);
          setNodes(buildNodeList(statusData.node));
          setLogs(statusData.logs ?? []);

          // If still running, resume polling
          if (statusData.progress < 100 && statusData.node !== "complete") {
            setIsRunning(true);
            pollRef.current = setInterval(() => {
              void poll(id);
            }, POLL_INTERVAL_MS);
          } else {
            setNodes((prev) =>
              prev.map((n) => ({ ...n, status: "completed" as const }))
            );
          }
        }
      } catch (err) {
        console.error("Failed to load job:", err);
        setError("Failed to load past research job.");
      }
    },
    [poll, stopPolling]
  );

  // ── Cleanup ───────────────────────────────────
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  return {
    jobId,
    isRunning,
    error,
    progress,
    currentNode,
    nodes,
    logs,
    state,
    pastBlogs,
    startJob,
    loadJob,
  };
}
