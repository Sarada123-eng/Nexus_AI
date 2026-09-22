"use client";

import { useState } from "react";
import { ImageIcon, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import type { ImageSpec } from "@/types/research";
import { apiUrl } from "@/lib/api";

type Props = {
  images: ImageSpec[];
};

function ImageCard({ image }: { image: ImageSpec }) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [imgError, setImgError] = useState(false);

  const imgSrc = image.filename.startsWith("images/")
    ? apiUrl(`/${image.filename}`)
    : apiUrl(`/images/${image.filename}`);

  return (
    <div className="group rounded-2xl border border-zinc-800/60 bg-zinc-900/20 overflow-hidden transition-all duration-200 hover:border-zinc-700/60 hover:bg-zinc-900/40">
      {/* Image */}
      <div className="relative aspect-square bg-zinc-900/60 flex items-center justify-center">
        {imgError ? (
          <div className="flex flex-col items-center gap-2 text-zinc-600 p-4">
            <ImageIcon size={32} />
            <p className="text-[10px] text-center">Image unavailable</p>
          </div>
        ) : (
          <img
            src={imgSrc}
            alt={image.alt}
            className="w-full h-full object-cover"
            onError={() => setImgError(true)}
          />
        )}
      </div>

      {/* Info */}
      <div className="p-4 space-y-2">
        <p className="text-sm font-semibold text-zinc-200 leading-snug">
          {image.caption}
        </p>

        <p className="text-[11px] text-zinc-500 leading-relaxed">
          <span className="font-medium text-zinc-600">Alt:</span> {image.alt}
        </p>

        {/* Prompt (collapsible) */}
        <button
          onClick={() => setShowPrompt(!showPrompt)}
          className="flex items-center gap-1.5 text-[11px] font-medium text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <Sparkles size={10} />
          Generation Prompt
          {showPrompt ? (
            <ChevronUp size={12} />
          ) : (
            <ChevronDown size={12} />
          )}
        </button>

        {showPrompt && (
          <div className="rounded-xl bg-zinc-950/60 border border-zinc-800/40 px-3 py-2.5 text-[11px] text-zinc-500 leading-relaxed font-mono">
            {image.prompt}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ImageGallery({ images }: Props) {
  if (images.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="rounded-2xl bg-zinc-900/30 border border-zinc-800/50 p-8 text-center max-w-md">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-800/50 text-zinc-600 mx-auto mb-4">
            <ImageIcon size={24} />
          </div>
          <h3 className="text-sm font-semibold text-zinc-400 mb-1">
            No Images Yet
          </h3>
          <p className="text-xs text-zinc-600 leading-relaxed">
            Generated images will appear here once the Images pipeline node
            completes. Up to 3 images per blog post.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 scrollbar-thin scrollbar-thumb-zinc-800 scrollbar-track-transparent">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 flex items-center gap-2">
            <ImageIcon size={12} />
            Generated Images
          </h3>
          <span className="inline-flex items-center rounded-full bg-emerald-950/30 px-2.5 py-1 text-[11px] font-bold text-emerald-400 ring-1 ring-emerald-500/20">
            {images.length} image{images.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {images.map((image, idx) => (
            <ImageCard key={idx} image={image} />
          ))}
        </div>
      </div>
    </div>
  );
}
