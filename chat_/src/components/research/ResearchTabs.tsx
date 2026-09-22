"use client";

import {
  ListChecks,
  FileSearch,
  FileText,
  ImageIcon,
  Terminal,
} from "lucide-react";

export type TabKey = "plan" | "evidence" | "markdown" | "images" | "logs";

type Props = {
  activeTab: TabKey;
  onTabChange: (tab: TabKey) => void;
  evidenceCount: number;
  imageCount: number;
  logCount: number;
};

const TABS: {
  key: TabKey;
  label: string;
  icon: React.ReactNode;
  badgeField?: "evidenceCount" | "imageCount" | "logCount";
}[] = [
  { key: "plan", label: "Plan", icon: <ListChecks size={15} /> },
  {
    key: "evidence",
    label: "Evidence",
    icon: <FileSearch size={15} />,
    badgeField: "evidenceCount",
  },
  { key: "markdown", label: "Markdown Preview", icon: <FileText size={15} /> },
  {
    key: "images",
    label: "Images",
    icon: <ImageIcon size={15} />,
    badgeField: "imageCount",
  },
  {
    key: "logs",
    label: "Logs",
    icon: <Terminal size={15} />,
    badgeField: "logCount",
  },
];

export default function ResearchTabs({
  activeTab,
  onTabChange,
  evidenceCount,
  imageCount,
  logCount,
}: Props) {
  const counts = { evidenceCount, imageCount, logCount };

  return (
    <div className="border-b border-zinc-800/80 bg-zinc-950/50 backdrop-blur-sm">
      <div className="flex items-center gap-1 px-4 overflow-x-auto scrollbar-thin">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key;
          const count = tab.badgeField ? counts[tab.badgeField] : 0;

          return (
            <button
              key={tab.key}
              onClick={() => onTabChange(tab.key)}
              className={`
                relative
                flex
                items-center
                gap-2
                px-4
                py-3
                text-sm
                font-medium
                transition-all
                duration-200
                whitespace-nowrap
                border-b-2
                -mb-px
                ${
                  isActive
                    ? "border-emerald-500 text-emerald-400"
                    : "border-transparent text-zinc-500 hover:text-zinc-300 hover:border-zinc-700"
                }
              `}
            >
              <span
                className={
                  isActive ? "text-emerald-400" : "text-zinc-600"
                }
              >
                {tab.icon}
              </span>
              {tab.label}
              {tab.badgeField && count > 0 && (
                <span
                  className={`
                    inline-flex
                    items-center
                    justify-center
                    min-w-[18px]
                    h-[18px]
                    rounded-full
                    px-1
                    text-[10px]
                    font-bold
                    ${
                      isActive
                        ? "bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/30"
                        : "bg-zinc-800 text-zinc-500"
                    }
                  `}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
