"use client";

import { ArrowLeft, Clock, Quote, RotateCcw, Target, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/EmptyState";
import { useGDSession } from "@/components/GDSessionProvider";
import { SeatAvatar } from "@/components/SeatAvatar";
import { formatClock, wordCount } from "@/lib/format";
import {
  assignSeats,
  panelForSize,
  type Seat,
  seatForSpeaker,
  USER_SEAT,
} from "@/lib/personas";
import { type StoredSession, useLastSession } from "@/lib/sessionStore";

/** Chart colours, validated as a pair on the dark surface (CVD ΔE 23.6, ≥3:1 contrast). */
const BAR_USER = "#059669";
const BAR_PANEL = "#6366f1";

const INITIATIVE_MAX = 10;

interface BalanceRow {
  key: string;
  name: string;
  seat: Seat | null;
  percent: number;
  isUser: boolean;
}

export function Report() {
  const router = useRouter();
  const live = useGDSession();
  const stored = useLastSession();

  const session: StoredSession | null =
    live.reportData && live.config
      ? {
          config: live.config,
          report: live.reportData,
          transcript: live.transcriptList,
          speakerAvatars: live.speakerAvatars,
        }
      : stored;

  const derived = session ? deriveBalance(session) : null;

  if (!session || !derived) {
    return (
      <EmptyState
        title="No report yet"
        body="Finish a discussion in the arena and your evaluation will appear here."
      />
    );
  }

  const { config, report, transcript } = session;
  const { rows, fairShare, seats, estimated } = derived;
  const { metrics, feedback } = report;
  const userDelta = metrics.speaking_time_user_percent - fairShare;

  function retry() {
    void live.startSession(config);
    router.push("/arena");
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-8 px-4 py-8 sm:px-6 sm:py-12">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
            <ArrowLeft aria-hidden className="size-4" />
            Lobby
          </Link>
          <p className="text-sm font-medium uppercase tracking-widest text-primary">
            Post-discussion report
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{config.topic}</h1>
          <p className="text-sm text-subtle">
            Panel of {config.panel_size} · {config.language}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={retry}
            className="inline-flex items-center gap-2 rounded-xl border border-border-strong px-4 py-2.5 text-sm font-semibold text-foreground hover:border-primary"
          >
            <RotateCcw aria-hidden className="size-4" />
            Retry topic
          </button>
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong"
          >
            New discussion
          </Link>
        </div>
      </header>

      {/* Headline scores */}
      <section aria-labelledby="scores-h" className="space-y-4">
        <h2 id="scores-h" className="text-lg font-semibold">
          Evaluation scores
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <StatTile
            icon={<Clock aria-hidden className="size-5 text-accent" />}
            label="Your speaking time"
            value={`${metrics.speaking_time_user_percent}%`}
            hint={`Fair share is ${Math.round(fairShare)}% · ${
              Math.abs(userDelta) < 3
                ? "well balanced"
                : userDelta > 0
                  ? `${Math.round(userDelta)} pts over`
                  : `${Math.round(-userDelta)} pts under`
            }`}
          />
          <StatTile
            icon={<Zap aria-hidden className="size-5 text-accent" />}
            label="Interruptions handled"
            value={String(metrics.interruptions_handled)}
            hint="Times you held or took the floor under pressure"
          />
          <StatTile
            icon={<Target aria-hidden className="size-5 text-accent" />}
            label="Initiative score"
            value={
              <>
                {metrics.initiative_score}
                <span className="text-lg font-medium text-subtle">/{INITIATIVE_MAX}</span>
              </>
            }
            hint={
              <Meter
                value={metrics.initiative_score}
                max={INITIATIVE_MAX}
                label="Initiative score"
              />
            }
          />
        </div>
      </section>

      {/* Speaker balance */}
      <section
        aria-labelledby="balance-h"
        className="space-y-5 rounded-xl border border-border bg-surface p-5 sm:p-6"
      >
        <div className="space-y-1">
          <h2 id="balance-h" className="text-lg font-semibold">
            Speaker balance
          </h2>
          <p className="text-sm text-subtle">Share of total speaking time</p>
        </div>
        <BalanceChart rows={rows} fairShare={fairShare} />
        {estimated && (
          <p className="text-xs text-subtle">
            Your share comes from the evaluator. The panel&apos;s split is estimated from
            transcript word counts.
          </p>
        )}
        <details className="text-sm">
          <summary className="cursor-pointer text-muted hover:text-foreground">View as table</summary>
          <table className="mt-3 w-full text-left">
            <thead className="text-subtle">
              <tr>
                <th className="py-1 font-medium">Speaker</th>
                <th className="py-1 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className="border-t border-border">
                  <td className="py-1.5">
                    {r.name}
                    {r.seat && !r.isUser && <span className="text-subtle"> · {r.seat.label}</span>}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{r.percent.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      {/* Feedback */}
      <section aria-labelledby="feedback-h" className="space-y-4">
        <h2 id="feedback-h" className="text-lg font-semibold">
          Feedback
        </h2>
        {feedback.length === 0 ? (
          <p className="text-muted">No feedback items were returned for this session.</p>
        ) : (
          <ul className="grid gap-4 md:grid-cols-2">
            {feedback.map((item, i) => (
              <li
                key={i}
                className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5"
              >
                <h3 className="text-sm font-semibold uppercase tracking-wider text-primary">
                  {item.criterion}
                </h3>
                <figure className="relative rounded-lg border-l-4 border-accent bg-background/60 py-3 pr-4 pl-10">
                  <Quote aria-hidden className="absolute top-3 left-3 size-4 text-accent" />
                  <blockquote className="text-foreground italic">{item.quote}</blockquote>
                  <figcaption className="sr-only">Your words</figcaption>
                </figure>
                <p className="leading-relaxed text-muted">{item.analysis}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {transcript.length > 0 && (
        <details className="rounded-xl border border-border bg-surface p-5">
          <summary className="cursor-pointer font-semibold">
            Full transcript <span className="text-sm font-normal text-subtle">({transcript.length} lines)</span>
          </summary>
          <ol className="mt-4 space-y-3 text-sm">
            {transcript.map((t, i) => {
              const seat = seatForSpeaker(t.speaker, seats);
              return (
                <li key={i} className="grid grid-cols-[3rem_1fr] gap-3">
                  <span className="font-mono text-subtle">{formatClock(t.timestamp)}</span>
                  <p>
                    <span className="font-semibold">{t.speaker === "User" ? "You" : t.speaker}</span>
                    {seat && t.speaker !== "User" && <span className="text-subtle"> ({seat.label})</span>}
                    <span className="text-muted">: {t.text}</span>
                  </p>
                </li>
              );
            })}
          </ol>
        </details>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------

function deriveBalance({ config, report, transcript, speakerAvatars }: StoredSession) {
  const panel = panelForSize(config.panel_size);
  const seats = assignSeats(panel, speakerAvatars);
  const fairShare = 100 / (panel.length + 1);
  const userPct = clampPct(report.metrics.speaking_time_user_percent);

  // Prefer the evaluator's measured split when the backend sends one.
  const dist = report.speaking_time_distribution;
  if (dist && Object.keys(dist).some((k) => k !== "User")) {
    const rows: BalanceRow[] = [
      { key: "user", name: "You", seat: USER_SEAT, percent: userPct, isUser: true },
    ];
    for (const [name, pct] of Object.entries(dist).sort((a, b) => b[1] - a[1])) {
      if (name === "User") continue;
      rows.push({
        key: name,
        name,
        seat: seatForSpeaker(name, seats),
        percent: clampPct(pct),
        isUser: false,
      });
    }
    return { rows, fairShare, seats, estimated: false };
  }

  const remaining = 100 - userPct;

  const words = new Map<string, number>();
  for (const t of transcript) {
    if (t.speaker === "User") continue;
    words.set(t.speaker, (words.get(t.speaker) ?? 0) + wordCount(t.text));
  }
  const totalAiWords = [...words.values()].reduce((a, b) => a + b, 0);

  const rows: BalanceRow[] = [
    { key: "user", name: "You", seat: USER_SEAT, percent: userPct, isUser: true },
  ];
  if (totalAiWords > 0) {
    for (const [name, w] of [...words].sort((a, b) => b[1] - a[1])) {
      rows.push({
        key: name,
        name,
        seat: seatForSpeaker(name, seats),
        percent: (remaining * w) / totalAiWords,
        isUser: false,
      });
    }
  } else {
    rows.push({ key: "panel", name: "AI panel", seat: null, percent: remaining, isUser: false });
  }
  return { rows, fairShare, seats, estimated: true };
}

function clampPct(n: number) {
  return Math.min(100, Math.max(0, n));
}

function BalanceChart({ rows, fairShare }: { rows: BalanceRow[]; fairShare: number }) {
  const peak = Math.max(fairShare, ...rows.map((r) => r.percent));
  const domain = Math.min(100, Math.ceil((peak * 1.15) / 10) * 10);
  const fairX = (fairShare / domain) * 100;

  return (
    <div className="space-y-1">
      <ul className="space-y-1">
        {rows.map((r) => (
          <li
            key={r.key}
            tabIndex={0}
            className="group relative grid grid-cols-[minmax(0,6.5rem)_1fr_3rem] items-center gap-3 rounded-lg px-2 py-2 hover:bg-surface-raised focus-visible:bg-surface-raised sm:grid-cols-[minmax(0,11rem)_1fr_3.5rem]"
            aria-label={`${r.name}${r.seat && !r.isUser ? ` (${r.seat.label})` : ""}: ${r.percent.toFixed(1)}% of speaking time`}
          >
            <div className="flex min-w-0 items-center gap-2">
              {r.seat && (
                <span className="hidden sm:block">
                  <SeatAvatar seat={r.seat} size="sm" />
                </span>
              )}
              <div className="min-w-0 leading-tight">
                <p className={`truncate text-sm ${r.isUser ? "font-semibold text-foreground" : "text-muted"}`}>
                  {r.name}
                </p>
                {r.seat && !r.isUser && <p className="truncate text-xs text-subtle">{r.seat.label}</p>}
              </div>
            </div>
            <div className="relative h-6" aria-hidden>
              <div className="absolute inset-y-[9px] left-0 right-0 rounded-sm bg-background" />
              <div
                className="absolute inset-y-[5px] left-0 rounded-r-[4px]"
                style={{
                  width: `${(r.percent / domain) * 100}%`,
                  background: r.isUser ? BAR_USER : BAR_PANEL,
                }}
              />
              <div
                className="absolute -inset-y-1 border-l-2 border-dashed border-subtle"
                style={{ left: `${fairX}%` }}
              />
            </div>
            <span className="text-right font-mono text-sm tabular-nums text-foreground" aria-hidden>
              {Math.round(r.percent)}%
            </span>
            <div
              role="tooltip"
              className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 rounded-md border border-border-strong bg-surface-raised px-3 py-1.5 text-xs whitespace-nowrap shadow-lg group-hover:block group-focus-visible:block"
            >
              <span className="font-semibold">{r.name}</span> · {r.percent.toFixed(1)}% ·{" "}
              {r.percent >= fairShare ? "+" : "−"}
              {Math.abs(r.percent - fairShare).toFixed(1)} pts vs fair share
            </div>
          </li>
        ))}
      </ul>
      <div
        className="grid grid-cols-[minmax(0,6.5rem)_1fr_3rem] gap-3 px-2 text-xs text-subtle sm:grid-cols-[minmax(0,11rem)_1fr_3.5rem]"
        aria-hidden
      >
        <span />
        <div className="relative h-4">
          <span className="absolute left-0">0%</span>
          <span className="absolute right-0">{domain}%</span>
        </div>
        <span />
      </div>
      <p className="flex items-center gap-2 px-2 pt-2 text-xs text-subtle">
        <span aria-hidden className="inline-block h-3 border-l-2 border-dashed border-subtle" />
        Fair share: {Math.round(fairShare)}% (equal time for every speaker)
      </p>
    </div>
  );
}

function StatTile({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  hint: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5">
      <div className="flex items-center gap-2 text-sm text-muted">
        {icon}
        {label}
      </div>
      <p className="font-mono text-4xl font-semibold tabular-nums">{value}</p>
      <div className="text-sm text-subtle">{hint}</div>
    </div>
  );
}

function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = (Math.min(max, Math.max(0, value)) / max) * 100;
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className="mt-1 h-2 w-full rounded-full bg-background"
    >
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: BAR_PANEL }} />
    </div>
  );
}
