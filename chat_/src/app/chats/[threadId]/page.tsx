"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { type Thread, useThreadState } from "@/components/thread-state";
import { apiUrl } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { Send, Bot, Sparkles, AlertCircle, Layers, RefreshCw, Check, Copy } from "lucide-react";

type ChatMessage = {
  role: "user" | "assistant";
  thread_id?: string;
  message: string;
  user_id?: string;
  sources?: Source[];
};

type Source = {
  text?: string;
  distance?: number;
  metadata?: {
    source?: string;
    chunk_index?: number;
  };
};

function CodeBlock({ children, className }: { children: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const language = className ? className.replace("language-", "") : "";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(children);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy code: ", err);
    }
  };

  return (
    <div className="relative group/code my-4 rounded-xl overflow-hidden border border-zinc-800 bg-zinc-950/90 shadow-md">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800/80 bg-zinc-900/60 text-xs text-zinc-400 select-none">
        <span className="font-mono uppercase tracking-wider text-[10px] text-zinc-500 font-semibold">{language || "code"}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-zinc-800/50 hover:bg-zinc-800 hover:text-zinc-100 text-zinc-400 transition duration-150 border border-transparent hover:border-zinc-700/50 cursor-pointer"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span className="font-medium">Copy</span>
            </>
          )}
        </button>
      </div>

      <pre className="overflow-x-auto p-4 text-[13.5px] font-mono leading-relaxed text-zinc-200">
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

export default function ChatPage() {
  const params = useParams();
  const threadId = params.threadId as string;
  const { setThreads } = useThreadState();

  const [currMessage, setCurrMessage] = useState("");
  const [processing, setProcessing] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState("");
  const [toolStatus, setToolStatus] = useState("");
  const [useRag, setUseRag] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadMessages() {
      try {
        setError("");

        const res = await fetch(apiUrl(`/threads/${threadId}/messages`));

        if (!res.ok) {
          throw new Error(`Failed to load messages (${res.status})`);
        }

        const data: ChatMessage[] = await res.json();

        if (!cancelled) {
          setMessages(data);
        }
      } catch (err) {
        console.error(err);

        if (!cancelled) {
          setError("Failed to load chat history.");
        }
      }
    }

    if (threadId) {
      void loadMessages();
    }

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages]);

  async function sendMessage() {
    const trimmedMessage = currMessage.trim();

    if (!trimmedMessage || processing) {
      return;
    }

    setError("");

    const userMessage: ChatMessage = {
      role: "user",
      message: trimmedMessage,
      thread_id: threadId,
      user_id: "u1",
    };

    // Add user message and an empty assistant placeholder
    setMessages((prev) => [
      ...prev,
      userMessage,
      { role: "assistant", message: "", thread_id: threadId, user_id: "u1" },
    ]);
    setCurrMessage("");
    setProcessing(true);

    try {
      const res = await fetch(apiUrl("/chat/stream"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmedMessage, thread_id: threadId , "user_id": "u1", use_rag: useRag}),
      });

      if (!res.ok || !res.body) {
        throw new Error(`Request failed (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE blocks are separated by double newlines
        const blocks = buffer.split("\n\n");
        // Keep the last (possibly incomplete) block in the buffer
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const lines = block.split("\n");
          const eventLine = lines.find((l) => l.startsWith("event:"));
          const dataLine = lines.find((l) => l.startsWith("data:"));
          if (!eventLine || !dataLine) continue;

          const eventType = eventLine.replace("event:", "").trim();
          const payload = JSON.parse(dataLine.replace("data:", "").trim()) as {
            content?: string;
            thread_id?: string;
            message?: string;
            tool?: string;
            sources?: Source[];
          };

          if (eventType === "tool_start" && payload.tool) {
            setToolStatus(payload.tool);
          } else if (eventType === "sources" && payload.sources) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  sources: payload.sources,
                };
              }
              return updated;
            });
          } else if (eventType === "token" && payload.content) {
            // Clear tool status once real content starts arriving
            setToolStatus("");
            // Append token to the last (assistant placeholder) message
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = {
                ...last,
                message: last.message + payload.content,
              };
              return updated;
            });
          } else if (eventType === "complete") {
            // Refresh thread list so the sidebar title updates
            try {
              const threadsResponse = await fetch(apiUrl("/threads"));
              if (threadsResponse.ok) {
                const updatedThreads: Thread[] = await threadsResponse.json();
                setThreads(updatedThreads);
              }
            } catch (refreshError) {
              console.error("Failed to refresh thread titles:", refreshError);
            }
          } else if (eventType === "error") {
            throw new Error(payload.message ?? "Streaming error");
          }
        }
      }
    } catch (err) {
      console.error(err);
      setError("Failed to send message.");
      // Replace the empty assistant placeholder with an error message
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant" && last.message === "") {
          updated[updated.length - 1] = {
            ...last,
            message: "Failed to get a response from the server.",
          };
        }
        return updated;
      });
    } finally {
      setProcessing(false);
      setToolStatus("");
    }
  }

  return (
    <main className="flex flex-1 flex-col bg-zinc-950 relative overflow-hidden h-full">
      {/* Background glow elements */}
      <div className="absolute top-0 right-0 -z-10 h-[300px] w-[300px] rounded-full bg-indigo-500/5 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-0 left-0 -z-10 h-[300px] w-[300px] rounded-full bg-purple-500/5 blur-[120px] pointer-events-none" />

      {/* Sticky Header */}
      <header className="sticky top-0 z-10 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-500/20">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-zinc-100 flex items-center gap-2">
              Workspace Chat
              <span className="inline-flex items-center rounded-md bg-indigo-500/10 px-2 py-0.5 text-[11px] font-medium text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
                LangGraph Active
              </span>
            </h2>
            <p className="text-xs text-zinc-400 font-mono mt-0.5 select-all">
              ID: {threadId}
            </p>
          </div>
        </div>

        {/* Right side: RAG Toggle */}
        <div className="flex items-center gap-2.5 bg-zinc-900/40 border border-zinc-800 px-3.5 py-1.5 rounded-xl backdrop-blur-sm shadow-inner select-none animate-in fade-in duration-200">
          <span className="text-xs font-semibold text-zinc-400 flex items-center gap-1.5">
            🔍 Search Documents (RAG)
          </span>
          <button
            onClick={() => setUseRag(!useRag)}
            className={`
              relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-1 focus:ring-indigo-500/30 focus:ring-offset-1 focus:ring-offset-zinc-950
              ${useRag ? "bg-indigo-600" : "bg-zinc-800"}
            `}
          >
            <span
              className={`
                pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out
                ${useRag ? "translate-x-4" : "translate-x-0"}
              `}
            />
          </button>
        </div>
      </header>

      {/* Messages List */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full max-w-lg mx-auto text-center px-4 py-12 animate-in fade-in duration-300">
            <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-500/10 text-indigo-400 ring-1 ring-indigo-500/20">
              <Sparkles className="h-6 w-6 animate-pulse" />
            </div>
            <h3 className="text-xl font-semibold text-zinc-100 mb-2">
              New Conversation Thread
            </h3>
            <p className="text-sm text-zinc-400 mb-6 leading-relaxed">
              This is the beginning of your chat workspace. You can send queries, utilize agentic search tools, and monitor state updates in real time.
            </p>
            <div className="grid grid-cols-2 gap-3 w-full max-w-md text-left">
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/30 p-3.5 backdrop-blur-sm">
                <h4 className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-1">Tools Enabled</h4>
                <p className="text-[11px] text-zinc-500 leading-normal">Search tools and web APIs can run automatically.</p>
              </div>
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/30 p-3.5 backdrop-blur-sm">
                <h4 className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-1">Streaming Mode</h4>
                <p className="text-[11px] text-zinc-500 leading-normal">Real-time token streaming and status execution outputs.</p>
              </div>
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, index) => (
              <div
                key={index}
                className={`flex gap-3 items-end animate-in fade-in duration-200 ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {msg.role === "assistant" && (
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-500 to-violet-500 text-white shadow-md shadow-indigo-500/10 shrink-0 self-start">
                    <Bot className="h-4.5 w-4.5" />
                  </div>
                )}

                <div className={`flex flex-col max-w-[80%] ${msg.role === "user" ? "items-end" : "items-start"}`}>
                  <div
                    className={`px-4 py-3 shadow-md ${
                      msg.role === "user"
                        ? "rounded-2xl rounded-br-sm bg-gradient-to-br from-indigo-600 to-violet-600 text-zinc-100 shadow-indigo-950/20"
                        : "rounded-2xl rounded-bl-sm bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/80 text-zinc-100"
                    }`}
                  >
                    {msg.role === "assistant" ? (
                      <div
                        className="
                          prose
                          prose-invert
                          max-w-none
                          prose-p:my-2
                          prose-p:first:mt-0
                          prose-p:last:mb-0
                          prose-headings:text-white
                          prose-strong:text-white
                          prose-code:text-indigo-300
                          prose-pre:bg-zinc-950/80
                          prose-pre:border
                          prose-pre:border-zinc-800
                          prose-pre:rounded-xl
                          prose-a:text-indigo-400
                          prose-a:hover:text-indigo-300
                          text-[15px]
                          leading-relaxed
                        "
                      >
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeRaw]}
                          components={{
                            code(props) {
                              const { children, className, ...rest } = props;
                              const match = /language-(\w+)/.exec(className || "");
                              const codeString = String(children).replace(/\n$/, "");

                              if (!match && !codeString.includes("\n")) {
                                return (
                                  <code className="bg-indigo-950/40 text-indigo-300 border border-indigo-500/20 px-1.5 py-0.5 rounded font-mono text-xs" {...rest}>
                                    {children}
                                  </code>
                                );
                              }

                              return <CodeBlock className={className}>{codeString}</CodeBlock>;
                            }
                          }}
                        >
                          {msg.message}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
                        {msg.message}
                      </p>
                    )}

                    {/* RAG Sources list */}
                    {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                      <details className="mt-3 text-xs border border-zinc-800/60 bg-zinc-950/45 rounded-xl overflow-hidden group/sources">
                        <summary className="flex items-center gap-1.5 px-3 py-2 text-zinc-400 font-semibold cursor-pointer select-none hover:text-zinc-200 transition-colors">
                          <span>📚 Sources ({msg.sources.length})</span>
                          <span className="ml-auto text-[10px] text-zinc-500 group-open/sources:rotate-180 transition-transform duration-200">▼</span>
                        </summary>
                        <div className="px-3 pb-3 pt-1 border-t border-zinc-900/50 space-y-2 max-h-40 overflow-y-auto divide-y divide-zinc-900/50">
                          {msg.sources.map((src, sIdx) => {
                            const meta = src.metadata || {};
                            const sourceName = meta.source || "Unknown File";
                            const chunkIndex = meta.chunk_index !== undefined ? meta.chunk_index : "?";
                            const distance = src.distance;
                            return (
                              <div key={sIdx} className="pt-2 first:pt-0 leading-relaxed text-zinc-400">
                                <div className="flex items-center justify-between text-[11px] font-medium text-indigo-300 mb-1">
                                  <span>{sourceName} (Chunk {chunkIndex})</span>
                                  {distance !== undefined && (
                                    <span className="text-[10px] text-zinc-500 font-mono">Distance: {distance.toFixed(4)}</span>
                                  )}
                                </div>
                                <p className="bg-zinc-950/80 px-2 py-1.5 rounded-lg border border-zinc-900 font-mono text-[11px] whitespace-pre-wrap leading-normal select-all">
                                  {src.text}
                                </p>
                              </div>
                            );
                          })}
                        </div>
                      </details>
                    )}
                  </div>
                  <span className="text-[10px] text-zinc-500 mt-1 mx-1 uppercase font-semibold tracking-wider">
                    {msg.role === "user" ? "You" : "Assistant"}
                  </span>
                </div>

                {msg.role === "user" && (
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-800 border border-zinc-700 text-xs font-semibold text-zinc-300 shrink-0 self-start">
                    SD
                  </div>
                )}
              </div>
            ))}

            {processing && messages[messages.length - 1]?.message === "" && (
              <div className="flex justify-start items-start gap-3 animate-in fade-in duration-200">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-900 text-zinc-400 shrink-0">
                  <Sparkles className="h-4.5 w-4.5 animate-pulse text-indigo-400" />
                </div>
                <div
                  className="
                    max-w-[75%]
                    rounded-2xl
                    rounded-bl-sm
                    bg-zinc-900/40
                    backdrop-blur-sm
                    border
                    border-zinc-800/80
                    px-5
                    py-4
                    text-zinc-400
                    shadow-lg
                  "
                >
                  {toolStatus ? (
                    <div className="flex items-center gap-3 text-sm">
                      <div className="relative flex h-5 w-5 items-center justify-center">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500"></span>
                      </div>
                      <span className="text-zinc-300">
                        Running tool <code className="bg-indigo-950/60 text-indigo-300 border border-indigo-500/20 px-2 py-0.5 rounded font-mono text-xs">{toolStatus}</code>…
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5 py-1">
                      <div className="h-2 w-2 animate-bounce rounded-full bg-indigo-500 [animation-delay:-0.3s]" />
                      <div className="h-2 w-2 animate-bounce rounded-full bg-indigo-500 [animation-delay:-0.15s]" />
                      <div className="h-2 w-2 animate-bounce rounded-full bg-indigo-500" />
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      {error && (
        <div className="px-6 py-2">
          <div className="flex items-center gap-2 rounded-xl bg-red-950/30 border border-red-500/20 px-4 py-3 text-sm text-red-400 shadow-md shadow-red-950/10">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-zinc-800/80 bg-zinc-950/50 backdrop-blur-md p-4">
        <div className="max-w-4xl mx-auto flex gap-3 items-center bg-zinc-900/80 border border-zinc-800 rounded-2xl px-4 py-2.5 focus-within:border-indigo-500/50 focus-within:ring-1 focus-within:ring-indigo-500/50 transition-all duration-200">
          <input
            type="text"
            value={currMessage}
            disabled={processing}
            placeholder={processing ? "AI is processing..." : "Type your message..."}
            onChange={(e) => setCurrMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                void sendMessage();
              }
            }}
            className="
              flex-1
              bg-transparent
              text-[15px]
              text-zinc-100
              placeholder-zinc-500
              outline-none
              py-1.5
              disabled:cursor-not-allowed
            "
          />

          <button
            onClick={() => void sendMessage()}
            disabled={processing}
            className="
              flex
              h-10
              w-10
              items-center
              justify-center
              rounded-xl
              bg-indigo-600
              text-white
              transition-all
              duration-200
              hover:bg-indigo-500
              active:scale-95
              disabled:cursor-not-allowed
              disabled:opacity-50
              shadow-md
              shadow-indigo-600/10
              shrink-0
            "
            title="Send Message"
          >
            {processing ? (
              <RefreshCw className="h-4.5 w-4.5 animate-spin" />
            ) : (
              <Send className="h-4.5 w-4.5" />
            )}
          </button>
        </div>
      </div>
    </main>
  );
}
