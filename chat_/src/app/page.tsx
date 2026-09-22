import { Sparkles, MessageSquare, Cpu, Terminal } from "lucide-react";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center bg-zinc-950 relative overflow-hidden px-6 py-12">
      {/* Background glow elements */}
      <div className="absolute top-0 right-0 -z-10 h-[400px] w-[400px] rounded-full bg-indigo-500/5 blur-[150px] pointer-events-none" />
      <div className="absolute bottom-0 left-0 -z-10 h-[400px] w-[400px] rounded-full bg-purple-500/5 blur-[150px] pointer-events-none" />

      <div className="max-w-3xl text-center animate-in fade-in duration-500">
        <div className="mb-6 flex justify-center">
          <div className="rounded-2xl bg-gradient-to-tr from-indigo-500/20 to-purple-500/20 p-5 ring-1 ring-indigo-500/30 shadow-xl shadow-indigo-950/20">
            <MessageSquare
              size={48}
              className="text-indigo-400 animate-pulse"
            />
          </div>
        </div>

        <h1 className="mb-4 text-5xl font-extrabold tracking-tight bg-gradient-to-r from-zinc-100 via-zinc-200 to-indigo-300 bg-clip-text text-transparent">
          Welcome to EchoBox
        </h1>

        <p className="mb-10 text-lg text-zinc-400 max-w-xl mx-auto leading-relaxed">
          Your advanced AI workspace orchestrating LangGraph workflows, memory, tool integrations, and real-time streaming operations.
        </p>

        {/* Feature Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-2xl mx-auto mb-10 text-left">
          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-5 backdrop-blur-sm shadow-sm transition-all hover:border-zinc-700/60 duration-200">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 mb-3.5">
              <Cpu size={18} />
            </div>
            <h3 className="text-sm font-semibold text-zinc-200 mb-1.5">LangGraph Core</h3>
            <p className="text-xs text-zinc-500 leading-relaxed">Stateful multi-agent orchestrations with checkpoint memory support.</p>
          </div>

          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-5 backdrop-blur-sm shadow-sm transition-all hover:border-zinc-700/60 duration-200">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 mb-3.5">
              <Sparkles size={18} />
            </div>
            <h3 className="text-sm font-semibold text-zinc-200 mb-1.5">Real-time Stream</h3>
            <p className="text-xs text-zinc-500 leading-relaxed">Immediate token response updates with SSE server callbacks.</p>
          </div>

          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-5 backdrop-blur-sm shadow-sm transition-all hover:border-zinc-700/60 duration-200">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 mb-3.5">
              <Terminal size={18} />
            </div>
            <h3 className="text-sm font-semibold text-zinc-200 mb-1.5">Tool Integrations</h3>
            <p className="text-xs text-zinc-500 leading-relaxed">Pulsing visual indicators tracking background tools execution live.</p>
          </div>
        </div>

        <div className="inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/50 px-4 py-2 text-sm text-zinc-400 shadow-inner">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          Select a chat thread or create a new one to begin.
        </div>
      </div>
    </main>
  );
}
