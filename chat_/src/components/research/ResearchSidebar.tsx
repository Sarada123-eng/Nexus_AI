"use client";

import { useState } from "react";
import {
  FlaskConical,
  CalendarDays,
  Sparkles,
  Loader2,
  Clock,
  ChevronRight,
} from "lucide-react";
import type { PastBlog } from "@/types/research";

type Props = {
  onStart: (topic: string, asOfDate?: string) => void;
  pastBlogs: PastBlog[];
  onLoadBlog: (jobId: string) => void;
  isRunning: boolean;
  activeJobId: string | null;
};

export default function ResearchSidebar({
  onStart,
  pastBlogs,
  onLoadBlog,
  isRunning,
  activeJobId,
}: Props) {
  const [topic, setTopic] = useState("");
  const [asOfDate, setAsOfDate] = useState(
    new Date().toISOString().split("T")[0]
  );

  function handleGenerate() {
    const trimmed = topic.trim();
    if (!trimmed || isRunning) return;
    onStart(trimmed, asOfDate);
  }

  return (
    <aside
      className="
        flex
        w-80
        flex-col
        border-r
        border-zinc-800/80
        bg-zinc-950
        h-full
        shrink-0
      "
    >
      {/* Header */}
      <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-emerald-500 to-teal-500 shadow-md shadow-emerald-500/20">
          <FlaskConical size={16} className="text-white" />
        </div>
        <div>
          <h2 className="text-sm font-bold text-zinc-100">Research Agent</h2>
          <p className="text-[10px] text-zinc-500 font-medium">
            AI Blog Generator
          </p>
        </div>
      </div>

      {/* Topic Input */}
      <div className="px-4 space-y-3">
        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-1.5 px-1">
            Topic
          </label>
          <textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Single-Agent vs Multi-Agent Architectures"
            rows={3}
            className="
              w-full
              resize-none
              rounded-xl
              border
              border-zinc-800
              bg-zinc-900/60
              px-3.5
              py-2.5
              text-sm
              text-zinc-200
              placeholder-zinc-600
              outline-none
              focus:border-emerald-500/50
              focus:ring-1
              focus:ring-emerald-500/30
              transition-all
              duration-200
              scrollbar-thin
            "
          />
          <p className="text-right text-[10px] text-zinc-600 mt-0.5 px-1">
            {topic.length} chars
          </p>
        </div>

        {/* Date Picker */}
        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-1.5 px-1">
            <CalendarDays size={10} className="inline mr-1 -mt-0.5" />
            As Of Date
          </label>
          <input
            type="date"
            value={asOfDate}
            onChange={(e) => setAsOfDate(e.target.value)}
            className="
              w-full
              rounded-xl
              border
              border-zinc-800
              bg-zinc-900/60
              px-3.5
              py-2.5
              text-sm
              text-zinc-300
              outline-none
              focus:border-emerald-500/50
              focus:ring-1
              focus:ring-emerald-500/30
              transition-all
              duration-200
              [color-scheme:dark]
            "
          />
        </div>

        {/* Generate Button */}
        <button
          onClick={handleGenerate}
          disabled={!topic.trim() || isRunning}
          className="
            flex
            w-full
            items-center
            justify-center
            gap-2
            rounded-xl
            bg-gradient-to-r
            from-emerald-600
            to-teal-600
            hover:from-emerald-500
            hover:to-teal-500
            active:scale-[0.98]
            px-4
            py-3
            text-sm
            font-semibold
            text-white
            shadow-lg
            shadow-emerald-950/40
            transition-all
            duration-200
            disabled:opacity-50
            disabled:cursor-not-allowed
            disabled:hover:from-emerald-600
            disabled:hover:to-teal-600
          "
        >
          {isRunning ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <Sparkles size={16} className="stroke-[2.5]" />
              Generate Blog
            </>
          )}
        </button>
      </div>

      {/* Divider */}
      <div className="mx-4 my-5 border-t border-zinc-800/60" />

      {/* Past Blogs */}
      <div className="flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin scrollbar-thumb-zinc-900 scrollbar-track-transparent">
        <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-widest text-zinc-500">
          Past Blogs
        </p>

        {pastBlogs.length === 0 ? (
          <p className="text-[11px] text-zinc-600 px-3 italic">
            No past blogs yet. Generate your first!
          </p>
        ) : (
          <div className="space-y-1">
            {pastBlogs.map((blog) => (
              <button
                key={blog.job_id}
                onClick={() => onLoadBlog(blog.job_id)}
                className={`
                  group
                  flex
                  w-full
                  items-center
                  gap-3
                  rounded-xl
                  px-3
                  py-2.5
                  text-left
                  text-sm
                  transition-all
                  duration-200
                  border border-transparent
                  ${
                    activeJobId === blog.job_id
                      ? "bg-emerald-950/30 border-emerald-500/20 text-emerald-300"
                      : "text-zinc-450 hover:bg-zinc-900/60 hover:text-zinc-100 hover:border-zinc-800/30"
                  }
                `}
              >
                <div className="flex-1 min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {blog.topic}
                  </span>
                  <span className="flex items-center gap-1.5 text-[10px] text-zinc-600 mt-0.5">
                    <Clock size={9} />
                    {new Date(blog.created_at).toLocaleDateString()}
                    <span
                      className={`
                        ml-auto
                        inline-flex
                        items-center
                        rounded-full
                        px-1.5
                        py-0.5
                        text-[9px]
                        font-semibold
                        ${
                          blog.status === "completed"
                            ? "bg-emerald-950/50 text-emerald-400 ring-1 ring-emerald-500/20"
                            : blog.status === "running"
                            ? "bg-amber-950/50 text-amber-400 ring-1 ring-amber-500/20"
                            : "bg-red-950/50 text-red-400 ring-1 ring-red-500/20"
                        }
                      `}
                    >
                      {blog.status}
                    </span>
                  </span>
                </div>
                <ChevronRight
                  size={14}
                  className="text-zinc-700 group-hover:text-zinc-400 transition-colors shrink-0"
                />
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
