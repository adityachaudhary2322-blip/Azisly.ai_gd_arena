"use client";

import {
  ArrowLeft,
  LoaderCircle,
  MessageSquareText,
  Mic,
  PhoneOff,
  Timer,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { TranscriptDrawer } from "@/components/arena/TranscriptDrawer";
import { EmptyState } from "@/components/EmptyState";
import { useGDSession } from "@/components/GDSessionProvider";
import { SeatAvatar } from "@/components/SeatAvatar";
import { formatClock } from "@/lib/format";
import { type Seat, type SeatId, seatForSpeaker, USER_SEAT } from "@/lib/personas";
import type { ConnectionStatus } from "@/hooks/useGDSocket";

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  idle: "Not started",
  connecting: "Connecting…",
  connected: "Live",
  disconnected: "Ended",
  error: "Error",
};

export function Arena() {
  const router = useRouter();
  const {
    config,
    panel,
    seats,
    connectionStatus,
    activeSpeaker,
    transcriptList,
    timeLeft,
    reportData,
    error,
    endSession,
    getAudioLevels,
  } = useGDSession();

  const [ending, setEnding] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const table: Seat[] = [USER_SEAT, ...panel];
  const activeSeat = activeSpeaker ? seatForSpeaker(activeSpeaker, seats) : null;
  const activeSeatId: SeatId | null = activeSeat?.id ?? null;
  const nameBySeat = new Map<SeatId, string>();
  for (const [name, id] of seats) nameBySeat.set(id, name);

  // Report arrived -> go show it.
  useEffect(() => {
    if (reportData) router.replace("/report");
  }, [reportData, router]);

  useAudioReactiveRing(activeSeatId, connectionStatus === "connected", getAudioLevels);

  if (!config) {
    return (
      <EmptyState
        title="No discussion in progress"
        body="Start a session from the lobby to enter the arena."
      />
    );
  }

  const live = connectionStatus === "connected";
  const waitingForReport = ending && !reportData && connectionStatus !== "error";
  const lowTime = timeLeft !== null && timeLeft <= 60;

  function handleEnd() {
    setEnding(true);
    endSession();
  }

  return (
    <div className="flex min-h-dvh flex-col lg:h-dvh lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="inline-flex items-center gap-1 rounded-md text-sm text-muted hover:text-foreground"
          >
            <ArrowLeft aria-hidden className="size-4" />
            Lobby
          </Link>
          <StatusPill status={connectionStatus} />
          <h1 className="order-last w-full truncate text-base font-semibold sm:order-none sm:w-auto sm:flex-1 sm:text-lg">
            {config.topic}
          </h1>
          <div
            role="timer"
            aria-label="Time left"
            className={`ml-auto inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 font-mono text-xl font-semibold tabular-nums sm:ml-0 ${
              lowTime ? "border-warning text-warning" : "border-border text-foreground"
            }`}
          >
            <Timer aria-hidden className="size-5" />
            {timeLeft === null ? "--:--" : formatClock(timeLeft)}
          </div>
        </header>

        {error && (
          <div
            role="alert"
            className="mx-4 mt-4 flex items-start gap-3 rounded-lg border border-danger/60 bg-danger/10 px-4 py-3 text-sm sm:mx-6"
          >
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
            <div className="flex-1">
              <p className="text-foreground">{error}</p>
              <Link href="/" className="mt-1 inline-block font-medium text-primary underline">
                Back to lobby
              </Link>
            </div>
          </div>
        )}

        {/* Round table */}
        <main className="flex flex-1 items-center justify-center p-4 sm:p-8">
          <div className="relative aspect-square w-full max-w-[min(100%,36rem)] lg:max-h-[calc(100dvh-10rem)] lg:w-auto lg:max-w-none lg:h-full">
            <div
              aria-hidden
              className="absolute inset-[22%] rounded-full border border-border bg-[radial-gradient(circle_at_50%_40%,var(--color-surface-raised),var(--color-surface)_70%)]"
            />
            <div className="absolute inset-[26%] flex flex-col items-center justify-center gap-1 text-center">
              <p className="text-xs font-medium uppercase tracking-widest text-subtle">Now speaking</p>
              <p className="text-base font-semibold sm:text-xl" aria-live="polite">
                {activeSeat
                  ? activeSeat.id === "user"
                    ? "You"
                    : `${activeSpeaker} · ${activeSeat.label}`
                  : live
                    ? "—"
                    : STATUS_LABEL[connectionStatus]}
              </p>
            </div>

            <ul aria-label="Participants">
              {table.map((seat, i) => {
                // Candidate sits at the bottom; others spread clockwise.
                const angle = Math.PI / 2 + (i * 2 * Math.PI) / table.length;
                const x = 50 + 40 * Math.cos(angle);
                const y = 50 + 40 * Math.sin(angle);
                const active = seat.id === activeSeatId;
                const name =
                  seat.id === "user" ? null : (nameBySeat.get(seat.id) ?? seat.defaultName);
                return (
                  <li
                    key={seat.id}
                    className="absolute flex w-24 -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2 text-center sm:w-32"
                    style={{ left: `${x}%`, top: `${y}%` }}
                    aria-current={active || undefined}
                  >
                    <SeatAvatar
                      seat={seat}
                      size="lg"
                      active={active}
                      ringRef={(el) => {
                        ringEls.set(seat.id, el);
                      }}
                    />
                    <div className="leading-tight">
                      <p className={`text-sm font-semibold ${active ? "text-foreground" : "text-muted"}`}>
                        {name ?? seat.label}
                      </p>
                      {name && <p className="text-xs text-subtle">{seat.label}</p>}
                      {active && <span className="sr-only">(speaking)</span>}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </main>

        {/* Controls */}
        <footer className="flex items-center justify-center gap-2 border-t border-border px-4 py-4">
          <span
            className={`inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm ${
              live ? "bg-accent/15 text-accent" : "bg-surface-raised text-subtle"
            }`}
          >
            <Mic aria-hidden className="size-4" />
            <span className="sr-only sm:not-sr-only">{live ? "Mic on" : "Mic off"}</span>
          </span>
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="inline-flex items-center gap-2 rounded-full border border-border-strong px-4 py-2 whitespace-nowrap text-sm font-medium text-muted hover:text-foreground lg:hidden"
            aria-controls="transcript-drawer"
            aria-expanded={drawerOpen}
          >
            <MessageSquareText aria-hidden className="size-4" />
            Transcript
            <span className="rounded-full bg-surface-raised px-2 font-mono text-xs">
              {transcriptList.length}
            </span>
          </button>
          {connectionStatus === "connected" || connectionStatus === "connecting" ? (
            <button
              type="button"
              onClick={handleEnd}
              disabled={ending}
              className="inline-flex items-center gap-2 rounded-full bg-danger px-5 py-2 whitespace-nowrap text-sm font-semibold text-background hover:bg-danger/90 disabled:opacity-60"
            >
              <PhoneOff aria-hidden className="size-4" />
              End discussion
            </button>
          ) : (
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground"
            >
              New discussion
            </Link>
          )}
        </footer>
      </div>

      <TranscriptDrawer
        id="transcript-drawer"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        entries={transcriptList}
        seats={seats}
      />

      {(connectionStatus === "connecting" || waitingForReport) && (
        <div
          role="status"
          className="fixed inset-0 z-40 flex flex-col items-center justify-center gap-4 bg-background/85 backdrop-blur-sm"
        >
          <LoaderCircle aria-hidden className="size-10 animate-spin text-primary" />
          <p className="text-lg font-medium">
            {waitingForReport ? "Evaluating your discussion…" : "Joining the panel…"}
          </p>
          {!waitingForReport && (
            <p className="text-sm text-subtle">Allow microphone access if your browser asks.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

/** Ring elements by seat, populated via ref callbacks. Module-level: one arena at a time. */
const ringEls = new Map<SeatId, HTMLDivElement | null>();

/**
 * Drives `--level` on the active speaker's ring every animation frame, straight
 * on the DOM so the 60 fps loop never re-renders React.
 */
function useAudioReactiveRing(
  activeSeatId: SeatId | null,
  running: boolean,
  getLevels: () => { user: number; agent: number },
) {
  const smoothed = useRef(0);

  useEffect(() => {
    for (const [id, el] of ringEls) {
      if (id !== activeSeatId) el?.style.setProperty("--level", "0");
    }
    if (!running || !activeSeatId) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const tick = () => {
      const levels = getLevels();
      const target = reduced ? 0.4 : activeSeatId === "user" ? levels.user : levels.agent;
      // Fast attack, slow release reads as "breathing" rather than flicker.
      const k = target > smoothed.current ? 0.5 : 0.12;
      smoothed.current += (target - smoothed.current) * k;
      ringEls.get(activeSeatId)?.style.setProperty("--level", smoothed.current.toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [activeSeatId, running, getLevels]);
}

function StatusPill({ status }: { status: ConnectionStatus }) {
  const tone =
    status === "connected"
      ? "border-accent/50 text-accent"
      : status === "error"
        ? "border-danger/60 text-danger"
        : "border-border-strong text-muted";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone}`}
    >
      {status === "connected" && (
        <span aria-hidden className="size-2 animate-pulse rounded-full bg-accent" />
      )}
      {STATUS_LABEL[status]}
    </span>
  );
}
