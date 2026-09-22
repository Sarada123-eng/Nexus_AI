"use client";

import { ExternalLink, Globe, FileSearch, BookOpen } from "lucide-react";
import type { EvidenceItem } from "@/types/research";

type Props = {
  evidence: EvidenceItem[];
};

export default function EvidenceView({ evidence }: Props) {
  if (evidence.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="rounded-2xl bg-zinc-900/30 border border-zinc-800/50 p-8 text-center max-w-md">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-800/50 text-zinc-600 mx-auto mb-4">
            <FileSearch size={24} />
          </div>
          <h3 className="text-sm font-semibold text-zinc-400 mb-1">
            No Evidence Yet
          </h3>
          <p className="text-xs text-zinc-600 leading-relaxed">
            Evidence items will appear here once the Research node completes its web search and synthesis.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
      <div className="max-w-4xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 flex items-center gap-2">
            <BookOpen size={12} />
            Evidence Sources
          </h3>
          <span className="inline-flex items-center rounded-full bg-emerald-950/30 px-2.5 py-1 text-[11px] font-bold text-emerald-400 ring-1 ring-emerald-500/20">
            {evidence.length} source{evidence.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Evidence Cards */}
        <div className="grid gap-3">
          {evidence.map((item, idx) => (
            <div
              key={idx}
              className="group rounded-2xl border border-zinc-800/60 bg-zinc-900/20 p-5 transition-all duration-200 hover:border-zinc-700/60 hover:bg-zinc-900/40"
            >
              <div className="flex items-start justify-between gap-3 mb-2.5">
                <div className="flex items-start gap-3 min-w-0 flex-1">
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-950/40 text-blue-400 text-xs font-bold ring-1 ring-blue-500/20 shrink-0 mt-0.5">
                    {idx + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-semibold text-zinc-200 leading-snug mb-1">
                      {item.title}
                    </h4>
                    {item.source && (
                      <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                        <Globe size={10} className="shrink-0" />
                        <span className="truncate">{item.source}</span>
                      </div>
                    )}
                  </div>
                </div>

                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="
                    flex
                    items-center
                    gap-1.5
                    rounded-lg
                    bg-zinc-800/50
                    hover:bg-zinc-800
                    px-2.5
                    py-1.5
                    text-[11px]
                    font-medium
                    text-zinc-400
                    hover:text-zinc-100
                    transition-all
                    duration-150
                    border
                    border-transparent
                    hover:border-zinc-700/50
                    shrink-0
                  "
                >
                  <ExternalLink size={11} />
                  Open
                </a>
              </div>

              {item.snippet && (
                <div className="ml-10 mt-2 rounded-xl bg-zinc-950/60 border border-zinc-800/40 px-4 py-3">
                  <p className="text-xs text-zinc-400 leading-relaxed line-clamp-4">
                    {item.snippet}
                  </p>
                </div>
              )}

              {item.published_at && (
                <p className="ml-10 mt-2 text-[10px] text-zinc-600">
                  Published: {item.published_at}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
