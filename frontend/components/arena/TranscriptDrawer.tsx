"use client";

import { MessageSquareText, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { formatClock } from "@/lib/format";
import { type SeatId, seatForSpeaker } from "@/lib/personas";
import type { TranscriptUpdate } from "@/types/gd";

interface TranscriptDrawerProps {
  id: string;
  open: boolean;
  onClose: () => void;
  entries: TranscriptUpdate[];
  seats: Map<string, SeatId>;
}

/** Bottom sheet on small screens, fixed side panel on lg+. */
export function TranscriptDrawer({ id, open, onClose, entries, seats }: TranscriptDrawerProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  // Follow new lines unless the reader has scrolled up to re-read.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedToBottom.current) el.scrollTop = el.scrollHeight;
  }, [entries.length, open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {open && (
        <div aria-hidden className="fixed inset-0 z-20 bg-black/60 lg:hidden" onClick={onClose} />
      )}
      <aside
        id={id}
        aria-label="Live transcript"
        className={`float-pane fixed inset-x-0 bottom-0 z-30 flex h-[70dvh] flex-col rounded-t-3xl border-t pb-[env(safe-area-inset-bottom)] transition-transform duration-200 lg:static lg:z-auto lg:h-auto lg:w-96 lg:translate-y-0 lg:rounded-none lg:border-t-0 lg:border-l ${
          open ? "translate-y-0" : "translate-y-full max-lg:invisible"
        }`}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="flex items-center gap-2 font-semibold">
            <MessageSquareText aria-hidden className="size-4 text-primary" />
            Transcript
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted hover:text-foreground lg:hidden"
            aria-label="Close transcript"
          >
            <X aria-hidden className="size-5" />
          </button>
        </div>

        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
          }}
          className="flex-1 overflow-y-auto overscroll-contain px-4 py-4"
        >
          {entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-subtle">
              The transcript will appear here as people speak.
            </p>
          ) : (
            <ol className="space-y-4" aria-live="polite" aria-relevant="additions">
              {entries.map((entry, i) => {
                const seat = seatForSpeaker(entry.speaker, seats);
                const isUser = entry.speaker === "User";
                return (
                  <li key={i} className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
                    <div className="flex items-center gap-2 text-xs">
                      <span
                        aria-hidden
                        className="size-2 rounded-full"
                        style={{ background: seat?.color ?? "var(--color-subtle)" }}
                      />
                      <span className="font-semibold text-foreground">
                        {isUser ? "You" : entry.speaker}
                      </span>
                      {seat && !isUser && <span className="text-subtle">{seat.label}</span>}
                      <span className="font-mono text-subtle">{formatClock(entry.timestamp)}</span>
                    </div>
                    <p
                      className={`max-w-[90%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                        isUser
                          ? "rounded-tr-sm bg-accent/15 text-foreground"
                          : "rounded-tl-sm bg-surface-raised text-foreground"
                      }`}
                    >
                      {entry.text}
                    </p>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </aside>
    </>
  );
}
