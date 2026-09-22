"use client";

import {
  Target,
  Users,
  Volume2,
  Layers,
  List,
  Hash,
  BookOpen,
  Code2,
  Search,
  FileText,
} from "lucide-react";
import type { Plan } from "@/types/research";

type Props = {
  plan: Plan | null;
};

export default function PlanView({ plan }: Props) {
  if (!plan) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="animate-pulse space-y-6 w-full max-w-3xl">
          {/* Skeleton header */}
          <div className="space-y-3">
            <div className="h-7 bg-zinc-800/60 rounded-xl w-2/3" />
            <div className="flex gap-3">
              <div className="h-5 bg-zinc-800/40 rounded-lg w-28" />
              <div className="h-5 bg-zinc-800/40 rounded-lg w-28" />
              <div className="h-5 bg-zinc-800/40 rounded-lg w-20" />
            </div>
          </div>
          {/* Skeleton cards */}
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="rounded-2xl border border-zinc-800/40 bg-zinc-900/20 p-5 space-y-3"
            >
              <div className="h-5 bg-zinc-800/50 rounded-lg w-1/2" />
              <div className="h-4 bg-zinc-800/30 rounded w-full" />
              <div className="space-y-2">
                <div className="h-3 bg-zinc-800/30 rounded w-5/6" />
                <div className="h-3 bg-zinc-800/30 rounded w-4/6" />
                <div className="h-3 bg-zinc-800/30 rounded w-3/6" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Blog Header */}
        <div className="rounded-2xl border border-zinc-800/60 bg-zinc-900/30 p-6 backdrop-blur-sm">
          <h2 className="text-xl font-bold text-zinc-100 mb-4 flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
              <BookOpen size={18} />
            </div>
            {plan.blog_title}
          </h2>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="flex items-center gap-2 rounded-xl bg-zinc-800/30 px-3 py-2">
              <Users size={14} className="text-zinc-500 shrink-0" />
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-600">
                  Audience
                </p>
                <p className="text-xs text-zinc-300 truncate">{plan.audience}</p>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-xl bg-zinc-800/30 px-3 py-2">
              <Volume2 size={14} className="text-zinc-500 shrink-0" />
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-600">
                  Tone
                </p>
                <p className="text-xs text-zinc-300 truncate">{plan.tone}</p>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-xl bg-zinc-800/30 px-3 py-2">
              <Layers size={14} className="text-zinc-500 shrink-0" />
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-600">
                  Mode
                </p>
                <p className="text-xs text-zinc-300 truncate">
                  {plan.blog_kind.replace("_", " ")}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-xl bg-zinc-800/30 px-3 py-2">
              <List size={14} className="text-zinc-500 shrink-0" />
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-600">
                  Sections
                </p>
                <p className="text-xs text-zinc-300">{plan.tasks.length}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Task Cards */}
        <div className="space-y-3">
          <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 px-1 flex items-center gap-2">
            <Target size={12} />
            Tasks
          </h3>

          {plan.tasks.map((task, idx) => (
            <div
              key={task.id}
              className="group rounded-2xl border border-zinc-800/60 bg-zinc-900/20 p-5 transition-all duration-200 hover:border-zinc-700/60 hover:bg-zinc-900/40"
            >
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex items-center gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-950/40 text-emerald-400 text-xs font-bold ring-1 ring-emerald-500/20">
                    {idx + 1}
                  </span>
                  <h4 className="text-sm font-semibold text-zinc-200">
                    {task.title}
                  </h4>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {task.requires_research && (
                    <span className="rounded-md bg-blue-950/30 px-1.5 py-0.5 text-[9px] font-bold text-blue-400 ring-1 ring-blue-500/20">
                      <Search size={8} className="inline -mt-0.5 mr-0.5" />
                      Research
                    </span>
                  )}
                  {task.requires_code && (
                    <span className="rounded-md bg-amber-950/30 px-1.5 py-0.5 text-[9px] font-bold text-amber-400 ring-1 ring-amber-500/20">
                      <Code2 size={8} className="inline -mt-0.5 mr-0.5" />
                      Code
                    </span>
                  )}
                  {task.requires_citations && (
                    <span className="rounded-md bg-purple-950/30 px-1.5 py-0.5 text-[9px] font-bold text-purple-400 ring-1 ring-purple-500/20">
                      <FileText size={8} className="inline -mt-0.5 mr-0.5" />
                      Citations
                    </span>
                  )}
                </div>
              </div>

              {/* Goal */}
              <p className="text-[13px] text-zinc-400 mb-3 pl-10 leading-relaxed">
                {task.goal}
              </p>

              {/* Bullets */}
              <ul className="space-y-1.5 pl-10 mb-3">
                {task.bullets.map((bullet, bIdx) => (
                  <li
                    key={bIdx}
                    className="flex items-start gap-2 text-xs text-zinc-500"
                  >
                    <span className="mt-1.5 h-1 w-1 rounded-full bg-emerald-500/60 shrink-0" />
                    <span className="leading-relaxed">{bullet}</span>
                  </li>
                ))}
              </ul>

              {/* Footer */}
              <div className="flex items-center gap-3 pl-10">
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-zinc-600">
                  <Hash size={10} />
                  {task.target_words} words
                </span>
                {task.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-md bg-zinc-800/60 px-1.5 py-0.5 text-[9px] font-medium text-zinc-500"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
