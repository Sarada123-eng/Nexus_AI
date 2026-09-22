"use client";

import { useState } from "react";
import { Copy, Check, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { apiUrl } from "@/lib/api";

type Props = {
  markdown: string;
};

function CodeBlock({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
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
        <span className="font-mono uppercase tracking-wider text-[10px] text-zinc-500 font-semibold">
          {language || "code"}
        </span>
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

export default function MarkdownView({ markdown }: Props) {
  const [copiedAll, setCopiedAll] = useState(false);

  const handleCopyAll = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2000);
    } catch (err) {
      console.error("Failed to copy markdown:", err);
    }
  };

  if (!markdown) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="rounded-2xl bg-zinc-900/30 border border-zinc-800/50 p-8 text-center max-w-md">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-800/50 text-zinc-600 mx-auto mb-4">
            <FileText size={24} />
          </div>
          <h3 className="text-sm font-semibold text-zinc-400 mb-1">
            No Content Yet
          </h3>
          <p className="text-xs text-zinc-600 leading-relaxed">
            The markdown preview will appear here once the Workers and Reducer
            have completed processing.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
      {/* Toolbar */}
      <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-2.5 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-md">
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">
          Live Preview
        </span>
        <button
          onClick={handleCopyAll}
          className="
            flex
            items-center
            gap-1.5
            rounded-lg
            bg-zinc-800/50
            hover:bg-zinc-800
            px-3
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
          "
        >
          {copiedAll ? (
            <>
              <Check size={12} className="text-emerald-400" />
              <span className="text-emerald-400">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              Copy Markdown
            </>
          )}
        </button>
      </div>

      {/* Markdown Content */}
      <div className="p-6 max-w-4xl mx-auto">
        <div
          className="
            prose
            prose-invert
            max-w-none
            prose-headings:text-zinc-100
            prose-headings:font-bold
            prose-h1:text-2xl
            prose-h1:border-b
            prose-h1:border-zinc-800/60
            prose-h1:pb-3
            prose-h1:mb-6
            prose-h2:text-lg
            prose-h2:mt-8
            prose-h2:mb-3
            prose-h2:text-emerald-300
            prose-h3:text-base
            prose-h3:text-zinc-200
            prose-p:text-zinc-300
            prose-p:leading-relaxed
            prose-p:text-[15px]
            prose-strong:text-white
            prose-code:text-emerald-300
            prose-code:bg-emerald-950/30
            prose-code:border
            prose-code:border-emerald-500/20
            prose-code:px-1.5
            prose-code:py-0.5
            prose-code:rounded
            prose-code:text-xs
            prose-code:font-mono
            prose-pre:bg-transparent
            prose-pre:p-0
            prose-a:text-emerald-400
            prose-a:hover:text-emerald-300
            prose-a:underline-offset-2
            prose-li:text-zinc-300
            prose-li:text-[15px]
            prose-blockquote:border-emerald-500/40
            prose-blockquote:text-zinc-400
            prose-table:text-sm
            prose-th:text-zinc-200
            prose-th:bg-zinc-900/50
            prose-th:px-4
            prose-th:py-2
            prose-td:px-4
            prose-td:py-2
            prose-td:border-zinc-800
            prose-tr:border-zinc-800
            prose-img:rounded-xl
            prose-img:border
            prose-img:border-zinc-800
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
                    <code className={className} {...rest}>
                      {children}
                    </code>
                  );
                }

                return (
                  <CodeBlock className={className}>{codeString}</CodeBlock>
                );
              },
              img(props) {
                const { src, ...rest } = props;
                const fullSrc = src && typeof src === "string" && src.startsWith("images/")
                  ? apiUrl(`/${src}`)
                  : src;
                return <img src={fullSrc} {...rest} />;
              },
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
