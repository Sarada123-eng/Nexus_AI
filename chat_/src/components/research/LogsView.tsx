"use client";

import { useEffect, useRef } from "react";
import { Terminal } from "lucide-react";
import type { LogEntry } from "@/types/research";

type Props = {
  logs: LogEntry[];
};

const NODE_COLORS: Record<string, string> = {
  router: "text-blue-400",
  research: "text-emerald-400",
  orchestrator: "text-violet-400",
  worker: "text-amber-400",
  reducer: "text-rose-400",
  images: "text-cyan-400",
  merge_content: "text-rose-400",
  decide_images: "text-cyan-400",
  generate_and_place_images: "text-cyan-400",
};

const NODE_BG: Record<string, string> = {
  router: "bg-blue-500/10",
  research: "bg-emerald-500/10",
  orchestrator: "bg-violet-500/10",
  worker: "bg-amber-500/10",
  reducer: "bg-rose-500/10",
  images: "bg-cyan-500/10",
  merge_content: "bg-rose-500/10",
  decide_images: "bg-cyan-500/10",
  generate_and_place_images: "bg-cyan-500/10",
};

export default function LogsView({ logs }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  if (logs.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="rounded-2xl bg-zinc-900/30 border border-zinc-800/50 p-8 text-center max-w-md">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-800/50 text-zinc-600 mx-auto mb-4">
            <Terminal size={24} />
          </div>
          <h3 className="text-sm font-semibold text-zinc-400 mb-1">
            No Logs Yet
          </h3>
          <p className="text-xs text-zinc-600 leading-relaxed">
            Execution logs will stream here in real time as the research
            pipeline runs.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-2.5 border-b border-zinc-800/60 bg-zinc-950/50 shrink-0">
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider flex items-center gap-2">
          <Terminal size={12} />
          Execution Logs
        </span>
        <span className="text-[10px] font-mono text-zinc-600">
          {logs.length} entries
        </span>
      </div>

      {/* Log Stream */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs bg-zinc-950/30 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
        <div className="space-y-1">
          {logs.map((log, idx) => {
            const nodeColor =
              NODE_COLORS[log.node.toLowerCase()] || "text-zinc-400";
            const nodeBg =
              NODE_BG[log.node.toLowerCase()] || "bg-zinc-800/30";

            return (
              <div
                key={idx}
                className="flex items-start gap-2 py-1 px-2 rounded-lg hover:bg-zinc-900/30 transition-colors duration-100 group"
              >
                {/* Timestamp */}
                {log.timestamp && (
                  <span className="text-[10px] text-zinc-700 font-mono shrink-0 mt-0.5 tabular-nums">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                )}

                {/* Node Badge */}
                <span
                  className={`
                    inline-flex
                    items-center
                    rounded-md
                    px-1.5
                    py-0.5
                    text-[10px]
                    font-bold
                    uppercase
                    tracking-wider
                    shrink-0
                    ${nodeBg}
                    ${nodeColor}
                  `}
                >
                  {log.node}
                </span>

                {/* Message */}
                <span className="text-zinc-400 leading-relaxed break-all">
                  {log.message}
                </span>
              </div>
            );
          })}
          <div ref={endRef} />
        </div>
      </div>
    </div>
  );
}
