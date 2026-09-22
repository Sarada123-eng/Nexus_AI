"use client";

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useContext,
  useEffect,
  useState,
} from "react";

import Sidebar from "@/components/SideBar";
import { apiUrl } from "@/lib/api";

export type Thread = {
  thread_id: string;
  title: string;
  created_at?: string | null;
};

type ThreadState = {
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
};

const ThreadContext = createContext<ThreadState | null>(null);

export function ThreadLayout({ children }: { children: ReactNode }) {
  const [threads, setThreads] = useState<Thread[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadThreads() {
      try {
        const response = await fetch(apiUrl("/threads"));
        if (!response.ok) {
          throw new Error(`Failed to load threads (${response.status})`);
        }

        const updatedThreads: Thread[] = await response.json();
        if (!cancelled) {
          setThreads(updatedThreads);
        }
      } catch (error) {
        console.error("Error fetching threads:", error);
      }
    }

    void loadThreads();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <ThreadContext.Provider value={{ threads, setThreads }}>
      <div className="flex h-screen bg-zinc-950 text-zinc-100">
        <Sidebar threads={threads} setThreads={setThreads} />
        {children}
      </div>
    </ThreadContext.Provider>
  );
}

export function useThreadState() {
  const context = useContext(ThreadContext);
  if (!context) {
    throw new Error("useThreadState must be used within ThreadLayout.");
  }

  return context;
}
