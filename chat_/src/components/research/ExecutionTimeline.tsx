"use client";

import {
  GitBranch,
  Search,
  LayoutList,
  Users,
  Layers,
  ImageIcon,
  CheckCircle2,
  Circle,
  AlertCircle,
  Loader2,
} from "lucide-react";
import type { ResearchNode } from "@/types/research";

type Props = {
  nodes: ResearchNode[];
  progress: number;
  isRunning: boolean;
};

const NODE_ICONS: Record<string, React.ReactNode> = {
  router: <GitBranch size={16} />,
  research: <Search size={16} />,
  orchestrator: <LayoutList size={16} />,
  worker: <Users size={16} />,
  reducer: <Layers size={16} />,
  images: <ImageIcon size={16} />,
};

const STATUS_CONFIG = {
  idle: {
    bg: "bg-zinc-800/40",
    ring: "ring-zinc-700/30",
    text: "text-zinc-600",
    icon: <Circle size={14} className="text-zinc-600" />,
    dot: "bg-zinc-600",
  },
  running: {
    bg: "bg-blue-950/30",
    ring: "ring-blue-500/20",
    text: "text-blue-400",
    icon: <Loader2 size={14} className="text-blue-400 animate-spin" />,
    dot: "bg-blue-500",
  },
  completed: {
    bg: "bg-emerald-950/20",
    ring: "ring-emerald-500/20",
    text: "text-emerald-400",
    icon: <CheckCircle2 size={14} className="text-emerald-400" />,
    dot: "bg-emerald-500",
  },
  failed: {
    bg: "bg-red-950/20",
    ring: "ring-red-500/20",
    text: "text-red-400",
    icon: <AlertCircle size={14} className="text-red-400" />,
    dot: "bg-red-500",
  },
};

export default function ExecutionTimeline({
  nodes,
  progress,
  isRunning,
}: Props) {
  return (
    <div className="bg-zinc-900/30 border border-zinc-800/60 rounded-2xl p-4 backdrop-blur-sm">
      {/* Header with progress */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 flex items-center gap-2">
          <span className="flex h-5 w-5 items-center justify-center rounded-md bg-zinc-800 text-zinc-400">
            <GitBranch size={12} />
          </span>
          Execution Pipeline
        </h3>
        <div className="flex items-center gap-2">
          {isRunning && (
            <span className="flex items-center gap-1.5 text-[10px] font-semibold text-blue-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
              </span>
              Running
            </span>
          )}
          <span className="text-xs font-mono text-zinc-500">
            {Math.round(progress)}%
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden mb-4">
        <div
          className="h-full bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full transition-all duration-700 ease-out"
          style={{ width: `${Math.min(progress, 100)}%` }}
        />
      </div>

      {/* Node Grid */}
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {nodes.map((node) => {
          const config = STATUS_CONFIG[node.status];
          return (
            <div
              key={node.name}
              className={`
                flex
                flex-col
                items-center
                gap-1.5
                rounded-xl
                p-3
                ring-1
                transition-all
                duration-300
                ${config.bg}
                ${config.ring}
              `}
            >
              <div className={`${config.text} transition-colors duration-300`}>
                {NODE_ICONS[node.name]}
              </div>
              <span
                className={`text-[10px] font-semibold ${config.text} transition-colors duration-300`}
              >
                {node.label}
              </span>
              <div className="flex items-center gap-1">
                {config.icon}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
