"use client";

import Link from "next/link";
import { useState, useEffect, type Dispatch, type SetStateAction } from "react";
import { useRouter, useParams, usePathname } from "next/navigation";
import { Plus, MessageSquare, LogOut, Trash2, FileText, Upload, Loader2, FlaskConical } from "lucide-react";

import type { Thread } from "@/components/thread-state";
import { apiUrl } from "@/lib/api";

type SidebarProps = {
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
};

export default function Sidebar({ threads, setThreads }: SidebarProps) {
  const router = useRouter();
  const params = useParams();
  const pathname = usePathname();
  const activeThreadId = params?.threadId as string;
  const isResearchActive = pathname === "/research";

  const [documents, setDocuments] = useState<{ doc_id: string; filename: string }[]>([]);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (!activeThreadId) {
      return;
    }

    async function fetchDocs() {
      try {
        const res = await fetch(apiUrl(`/threads/${activeThreadId}/documents`));
        if (res.ok) {
          const data = await res.json();
          setDocuments(data);
        }
      } catch (err) {
        console.error("Error fetching documents:", err);
      }
    }

    fetchDocs();
  }, [activeThreadId]);

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !activeThreadId) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(apiUrl(`/threads/${activeThreadId}/documents`), {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error("Failed to upload document");
      }

      const newDoc = await res.json();
      setDocuments((prev) => [...prev, newDoc]);
    } catch (err) {
      console.error("Error uploading document:", err);
      alert("Error indexing document. Please try again.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDeleteDoc(docId: string) {
    if (!confirm("Are you sure you want to delete this indexed document?")) return;

    try {
      const res = await fetch(apiUrl(`/threads/${activeThreadId}/documents/${docId}`), {
        method: "DELETE",
      });

      if (!res.ok) {
        throw new Error("Failed to delete document");
      }

      setDocuments((prev) => prev.filter((d) => d.doc_id !== docId));
    } catch (err) {
      console.error("Error deleting document:", err);
    }
  }

  async function handleClick() {
    try {
      const res = await fetch(apiUrl("/threads"), {
        method: "POST",
      });
      if (!res.ok) {
        throw new Error(`Failed to create thread (${res.status})`);
      }
      const newThread: Thread = await res.json();
      setThreads((prev) => [newThread, ...prev]);
      router.push(`/chats/${newThread.thread_id}`);
    } catch (error) {
      console.error("Error creating thread:", error);
    }
  }

  async function handleDeleteAllChats() {
    if (!confirm("Are you sure you want to delete all chats? This action cannot be undone.")) {
      return;
    }

    try {
      const res = await fetch(apiUrl("/threads"), {
        method: "DELETE",
      });
      if (!res.ok) {
        throw new Error(`Failed to delete threads (${res.status})`);
      }
      setThreads([]);
      router.push("/");
    } catch (error) {
      console.error("Error deleting threads:", error);
    }
  }

  return (
    <aside
      className="
        flex
        h-screen
        w-72
        flex-col
        border-r
        border-zinc-800/80
        bg-zinc-950
        text-zinc-100
      "
    >
      {/* Header */}
      <div
        className="
          flex
          h-16
          items-center
          justify-between
          border-b
          border-zinc-800/80
          px-6
        "
      >
        <div className="flex items-center gap-2.5">
          <div className="h-6 w-6 rounded-lg bg-gradient-to-tr from-indigo-500 to-violet-500 shadow-md shadow-indigo-500/20" />
          <h1 className="text-lg font-bold tracking-tight bg-gradient-to-r from-zinc-100 to-zinc-400 bg-clip-text text-transparent">
            EchoBox
          </h1>
        </div>
        <span className="inline-flex items-center rounded-md bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
          v1.0
        </span>
      </div>

      {/* New Chat Button */}
      <div className="p-4">
        <button
          className="
            flex
            w-full
            items-center
            justify-center
            gap-2
            rounded-xl
            bg-gradient-to-r
            from-indigo-650
            to-violet-650
            hover:from-indigo-600
            hover:to-violet-600
            active:scale-[0.98]
            px-4
            py-3
            text-sm
            font-semibold
            text-white
            shadow-lg
            shadow-indigo-950/40
            transition-all
            duration-200
          "
          onClick={handleClick}
        >
          <Plus size={16} className="stroke-[2.5]" />
          New Chat
        </button>
      </div>

      {/* Chat Threads and Documents */}
      <div className="flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin scrollbar-thumb-zinc-900 scrollbar-track-transparent">
        <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-widest text-zinc-500">
          Conversations
        </p>

        <div className="space-y-1">
          {threads.map((thread) => (
            <Link
              key={thread.thread_id}
              href={`/chats/${thread.thread_id}`}
              className="
                group
                flex
                items-center
                gap-3
                rounded-xl
                px-3
                py-2.5
                text-sm
                text-zinc-450
                transition-all
                duration-200
                hover:bg-zinc-900/60
                hover:text-zinc-100
                border border-transparent
                hover:border-zinc-800/30
              "
            >
              <MessageSquare size={16} className="text-zinc-500 group-hover:text-indigo-400 transition-colors" />
              <span className="truncate flex-1">
                {thread.title}
              </span>
            </Link>
          ))}
        </div>

        <div>
          <button
            className="
              mt-4
              flex
              w-full
              items-center
              justify-center
              gap-2
              rounded-xl
              border
              border-zinc-800/80
              bg-zinc-900/10
              px-4
              py-2.5
              text-xs
              font-medium
              text-zinc-400
              transition-all
              duration-200
              hover:bg-red-950/20
              hover:border-red-900/30
              hover:text-red-400
              disabled:opacity-40
              disabled:cursor-not-allowed
              disabled:hover:bg-transparent
              disabled:hover:border-zinc-800/80
              disabled:hover:text-zinc-400
            "
            disabled={threads.length === 0}
            onClick={handleDeleteAllChats}
          >
            <Trash2 size={14} />
            Delete All Chats
          </button>
        </div>

        {/* Research Agent Divider + Link */}
        <div className="mt-5 pt-5 border-t border-zinc-800/50">
          <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-widest text-zinc-500">
            Agents
          </p>
          <Link
            href="/research"
            className={`
              group
              flex
              items-center
              gap-3
              rounded-xl
              px-3
              py-2.5
              text-sm
              transition-all
              duration-200
              border
              ${
                isResearchActive
                  ? "bg-emerald-950/30 border-emerald-500/20 text-emerald-300"
                  : "border-transparent text-zinc-450 hover:bg-zinc-900/60 hover:text-zinc-100 hover:border-zinc-800/30"
              }
            `}
          >
            <div
              className={`
                flex h-7 w-7 items-center justify-center rounded-lg transition-colors
                ${
                  isResearchActive
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-zinc-800/50 text-zinc-500 group-hover:bg-emerald-500/10 group-hover:text-emerald-400"
                }
              `}
            >
              <FlaskConical size={14} />
            </div>
            <span className="font-medium">Research Agent</span>
            <span
              className={`
                ml-auto inline-flex items-center rounded-md px-1.5 py-0.5 text-[9px] font-semibold ring-1 ring-inset
                ${
                  isResearchActive
                    ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20"
                    : "bg-zinc-800/30 text-zinc-600 ring-zinc-700/20"
                }
              `}
            >
              NEW
            </span>
          </Link>
        </div>

        {activeThreadId && (
          <div className="mt-6 pt-6 border-t border-zinc-800/50">
            <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-widest text-zinc-500 flex items-center justify-between">
              <span>Indexed Documents</span>
              <span className="text-[9px] lowercase bg-indigo-950/40 border border-indigo-500/20 px-1.5 py-0.5 rounded text-indigo-400">active thread</span>
            </p>

            <div className="px-3 mb-4">
              <label
                className="
                  flex
                  w-full
                  cursor-pointer
                  items-center
                  justify-center
                  gap-2
                  rounded-xl
                  border
                  border-dashed
                  border-zinc-800
                  bg-zinc-900/10
                  hover:bg-zinc-900/30
                  hover:border-zinc-700
                  active:scale-[0.98]
                  px-4
                  py-3
                  text-xs
                  font-semibold
                  text-zinc-300
                  shadow-inner
                  transition-all
                  duration-200
                "
              >
                {uploading ? (
                  <>
                    <Loader2 size={14} className="animate-spin text-indigo-400" />
                    <span>Indexing...</span>
                  </>
                ) : (
                  <>
                    <Upload size={14} className="text-zinc-400" />
                    <span>Index Document</span>
                  </>
                )}
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={uploading}
                />
              </label>
            </div>

            {documents.length === 0 ? (
              <p className="text-[11px] text-zinc-600 px-3 italic">
                No documents indexed for this thread.
              </p>
            ) : (
              <div className="space-y-1 px-1 max-h-48 overflow-y-auto scrollbar-thin">
                {documents.map((doc) => (
                  <div
                    key={doc.doc_id}
                    className="
                      group
                      flex
                      items-center
                      justify-between
                      gap-2
                      rounded-lg
                      px-2.5
                      py-1.5
                      text-xs
                      text-zinc-400
                      hover:bg-zinc-900/40
                      hover:text-zinc-200
                      border border-transparent
                      transition-all
                      duration-150
                    "
                  >
                    <div className="flex items-center gap-2 truncate flex-1">
                      <FileText size={13} className="text-zinc-500 shrink-0" />
                      <span className="truncate" title={doc.filename}>{doc.filename}</span>
                    </div>
                    <button
                      onClick={() => handleDeleteDoc(doc.doc_id)}
                      className="
                        opacity-0
                        group-hover:opacity-100
                        p-1
                        rounded
                        hover:bg-red-950/20
                        hover:text-red-400
                        text-zinc-500
                        transition-all
                        duration-150
                      "
                      title="Un-index document"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* User Section */}
      <div
        className="
          border-t
          border-zinc-900/80
          bg-zinc-950/30
          p-4
        "
      >
        <div
          className="
            mb-3
            flex
            items-center
            gap-3
            rounded-xl
            border
            border-zinc-900/80
            bg-zinc-900/40
            p-3
            shadow-inner
          "
        >
          <div
            className="
              flex
              h-10
              w-10
              items-center
              justify-center
              rounded-xl
              bg-gradient-to-tr
              from-indigo-500
              to-violet-500
              text-white
              font-semibold
              shadow-md
              shadow-indigo-500/10
              shrink-0
            "
          >
            SD
          </div>

          <div className="truncate">
            <p className="text-sm font-semibold text-zinc-200 leading-tight">
              Sarada
            </p>
            <p className="text-xs text-zinc-500 mt-0.5 truncate">
              IIT Bhubaneswar
            </p>
          </div>
        </div>

        <button
          className="
            flex
            w-full
            items-center
            gap-3
            rounded-xl
            px-4
            py-2.5
            text-sm
            text-zinc-450
            transition-all
            duration-200
            hover:bg-zinc-900/60
            hover:text-red-400
          "
        >
          <LogOut size={16} />
          Logout
        </button>
      </div>
    </aside>
  );
}
