"use client";

import { useState } from "react";
import { FlaskConical, Sparkles } from "lucide-react";
import { useResearchJob } from "@/hooks/useResearchJob";
import ResearchSidebar from "@/components/research/ResearchSidebar";
import ResearchTabs, { type TabKey } from "@/components/research/ResearchTabs";
import ExecutionTimeline from "@/components/research/ExecutionTimeline";
import PlanView from "@/components/research/PlanView";
import EvidenceView from "@/components/research/EvidenceView";
import MarkdownView from "@/components/research/MarkdownView";
import ImageGallery from "@/components/research/ImageGallery";
import LogsView from "@/components/research/LogsView";

export default function ResearchPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("plan");

  const {
    jobId,
    isRunning,
    error,
    progress,
    nodes,
    logs,
    state,
    pastBlogs,
    startJob,
    loadJob,
  } = useResearchJob();

  const evidenceCount = state.evidence.length;
  const imageCount = state.images.length;
  const logCount = logs.length;

  function renderTabContent() {
    switch (activeTab) {
      case "plan":
        return <PlanView plan={state.plan} />;
      case "evidence":
        return <EvidenceView evidence={state.evidence} />;
      case "markdown":
        return <MarkdownView markdown={state.markdown} />;
      case "images":
        return <ImageGallery images={state.images} />;
      case "logs":
        return <LogsView logs={logs} />;
      default:
        return null;
    }
  }

  return (
    <div className="flex h-screen w-full bg-zinc-950 text-zinc-100 overflow-hidden">
      {/* Left Sidebar */}
      <ResearchSidebar
        onStart={startJob}
        pastBlogs={pastBlogs}
        onLoadBlog={loadJob}
        isRunning={isRunning}
        activeJobId={jobId}
      />

      {/* Main Panel */}
      <main className="flex flex-1 flex-col min-w-0 relative overflow-hidden">
        {/* Background glow */}
        <div className="absolute top-0 right-0 -z-10 h-[300px] w-[300px] rounded-full bg-emerald-500/5 blur-[120px] pointer-events-none" />
        <div className="absolute bottom-0 left-0 -z-10 h-[300px] w-[300px] rounded-full bg-teal-500/5 blur-[120px] pointer-events-none" />

        {/* Header */}
        <header className="shrink-0 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-600 text-white shadow-lg shadow-emerald-500/20">
              <FlaskConical className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
                Research Agent
                <span className="inline-flex items-center rounded-md bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/20">
                  LangGraph Pipeline
                </span>
              </h2>
              {jobId && (
                <p className="text-xs text-zinc-400 font-mono mt-0.5 select-all">
                  Job: {jobId}
                </p>
              )}
            </div>
          </div>

          {isRunning && (
            <div className="flex items-center gap-2.5 bg-zinc-900/40 border border-zinc-800 px-3.5 py-1.5 rounded-xl backdrop-blur-sm shadow-inner animate-in fade-in duration-200">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              <span className="text-xs font-semibold text-emerald-400">
                Processing…
              </span>
            </div>
          )}
        </header>

        {/* Error Banner */}
        {error && (
          <div className="px-6 py-2 shrink-0">
            <div className="flex items-center gap-2 rounded-xl bg-red-950/30 border border-red-500/20 px-4 py-3 text-sm text-red-400 shadow-md shadow-red-950/10">
              <span>⚠️</span>
              <span>{error}</span>
            </div>
          </div>
        )}

        {/* Execution Timeline */}
        {(isRunning || jobId) && (
          <div className="px-6 pt-4 pb-2 shrink-0">
            <ExecutionTimeline
              nodes={nodes}
              progress={progress}
              isRunning={isRunning}
            />
          </div>
        )}

        {/* Content Area */}
        {jobId ? (
          <div className="flex flex-1 flex-col min-h-0">
            <ResearchTabs
              activeTab={activeTab}
              onTabChange={setActiveTab}
              evidenceCount={evidenceCount}
              imageCount={imageCount}
              logCount={logCount}
            />
            <div className="flex-1 min-h-0 flex flex-col">
              {renderTabContent()}
            </div>
          </div>
        ) : (
          /* Empty State */
          <div className="flex-1 flex flex-col items-center justify-center px-6 py-12">
            <div className="max-w-lg text-center">
              <div className="mb-6 flex justify-center">
                <div className="rounded-2xl bg-gradient-to-tr from-emerald-500/20 to-teal-500/20 p-5 ring-1 ring-emerald-500/30 shadow-xl shadow-emerald-950/20">
                  <Sparkles
                    size={48}
                    className="text-emerald-400 animate-pulse"
                  />
                </div>
              </div>
              <h1 className="mb-4 text-3xl font-extrabold tracking-tight bg-gradient-to-r from-zinc-100 via-zinc-200 to-emerald-300 bg-clip-text text-transparent">
                Research Agent
              </h1>
              <p className="mb-8 text-sm text-zinc-400 max-w-md mx-auto leading-relaxed">
                Enter a topic in the sidebar to generate a comprehensive,
                research-backed blog post. The AI pipeline will route, research,
                plan, write, and generate images automatically.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl mx-auto text-left">
                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-4 backdrop-blur-sm">
                  <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1">
                    Smart Routing
                  </h4>
                  <p className="text-[11px] text-zinc-500 leading-normal">
                    Auto-decides whether to use closed-book, hybrid, or
                    open-book research.
                  </p>
                </div>
                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-4 backdrop-blur-sm">
                  <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1">
                    Parallel Workers
                  </h4>
                  <p className="text-[11px] text-zinc-500 leading-normal">
                    Sections are written concurrently by independent worker
                    agents.
                  </p>
                </div>
                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-4 backdrop-blur-sm">
                  <h4 className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-1">
                    AI Images
                  </h4>
                  <p className="text-[11px] text-zinc-500 leading-normal">
                    Auto-generated diagrams and visuals placed in optimal
                    locations.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
