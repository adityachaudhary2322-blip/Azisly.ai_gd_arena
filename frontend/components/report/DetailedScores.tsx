import {
  Brain,
  CheckCircle2,
  Ear,
  Gauge,
  Lightbulb,
  type LucideIcon,
  MessageCircle,
  Mic2,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";

import type { CategoryScore, FinalReport } from "@/types/gd";

const ICONS: Record<string, LucideIcon> = {
  fluency: MessageCircle,
  clarity: Mic2,
  logic: Brain,
  knowledge: Lightbulb,
  confidence: Zap,
  engagement: Ear,
};

/** Words, not just colour, carry the band. */
function band(score: number): string {
  if (score >= 8.5) return "Excellent";
  if (score >= 7) return "Strong";
  if (score >= 5.5) return "Good";
  if (score >= 4) return "Developing";
  return "Needs work";
}

/** Overall score, per-category scores with reasons and tips, strengths and improvements. */
export function DetailedScores({ report }: { report: FinalReport }) {
  const { scores, overall_score: overall, strengths, improvements, delivery } = report;
  if (!scores?.length || overall == null) return null;

  const chips = [
    delivery?.words_per_minute != null && `${delivery.words_per_minute} words/min`,
    delivery && `${delivery.filler_words} filler word${delivery.filler_words === 1 ? "" : "s"}`,
    delivery?.questions_asked
      ? `Answered ${delivery.questions_answered}/${delivery.questions_asked} questions`
      : null,
    delivery?.avg_response_seconds != null && `${delivery.avg_response_seconds}s to respond`,
  ].filter(Boolean) as string[];

  return (
    <section aria-labelledby="detail-h" className="space-y-4">
      <h2 id="detail-h" className="text-lg font-semibold">
        Detailed report
      </h2>

      <div className="glass-card flex flex-col items-center gap-5 p-5 text-center sm:flex-row sm:p-6 sm:text-left">
        <ScoreRing score={overall} />
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <p className="eyebrow">Overall</p>
            <p className="text-2xl font-bold tracking-tight">{band(overall)}</p>
            <p className="text-sm text-muted">
              Average of six categories, each scored out of 10.
            </p>
          </div>
          {chips.length > 0 && (
            <ul className="flex flex-wrap justify-center gap-2 sm:justify-start" aria-label="Measured delivery">
              {chips.map((c) => (
                <li
                  key={c}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted"
                >
                  <Gauge aria-hidden className="size-3.5 text-primary" />
                  {c}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {scores.map((s) => (
          <CategoryCard key={s.key} item={s} />
        ))}
      </ul>

      <div className="grid gap-3 md:grid-cols-2">
        {strengths && strengths.length > 0 && (
          <div className="glass-card p-5">
            <h3 className="flex items-center gap-2 font-semibold">
              <Sparkles aria-hidden className="size-4 text-primary" />
              What went well
            </h3>
            <ul className="mt-3 space-y-2.5">
              {strengths.map((t) => (
                <li key={t} className="flex gap-2.5 text-sm leading-relaxed text-muted">
                  <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {improvements && improvements.length > 0 && (
          <div className={`glass-card p-5 ${strengths?.length ? "" : "md:col-span-2"}`}>
            <h3 className="flex items-center gap-2 font-semibold">
              <TrendingUp aria-hidden className="size-4 text-accent" />
              What to improve
            </h3>
            <ol className="mt-3 space-y-2.5">
              {improvements.map((t, i) => (
                <li key={t} className="flex gap-2.5 text-sm leading-relaxed text-foreground">
                  <span
                    aria-hidden
                    className="flex size-5 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[11px] font-bold text-accent"
                  >
                    {i + 1}
                  </span>
                  <span>{t}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </section>
  );
}

function CategoryCard({ item }: { item: CategoryScore }) {
  const Icon = ICONS[item.key] ?? Gauge;
  const pct = Math.max(0, Math.min(10, item.score)) * 10;
  return (
    <li className="glass-card flex flex-col gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <span className="flex size-8 items-center justify-center rounded-xl bg-primary/15 text-primary">
            <Icon aria-hidden className="size-4" />
          </span>
          {item.label}
        </h3>
        <p className="shrink-0 font-mono text-xl font-semibold tabular-nums">
          {item.score.toFixed(1)}
          <span className="text-sm font-medium text-subtle">/10</span>
        </p>
      </div>
      <div
        role="meter"
        aria-label={`${item.label} score`}
        aria-valuemin={0}
        aria-valuemax={10}
        aria-valuenow={item.score}
        aria-valuetext={`${item.score.toFixed(1)} out of 10, ${band(item.score)}`}
        className="h-2 w-full rounded-full bg-background/70"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs font-medium text-muted">{band(item.score)}</p>
      <p className="text-sm leading-relaxed text-muted">{item.summary}</p>
      <p className="mt-auto rounded-2xl bg-background/40 px-3 py-2 text-sm leading-relaxed">
        <span className="font-semibold text-accent">Try this: </span>
        {item.tip}
      </p>
    </li>
  );
}

function ScoreRing({ score }: { score: number }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const filled = (Math.max(0, Math.min(10, score)) / 10) * c;
  return (
    <div className="relative size-32 shrink-0">
      <svg viewBox="0 0 100 100" className="size-full -rotate-90" aria-hidden>
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgb(255 255 255 / 0.1)" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${c}`}
        />
      </svg>
      <p className="absolute inset-0 flex flex-col items-center justify-center" aria-label={`Overall ${score} out of 10`}>
        <span className="font-mono text-3xl font-bold tabular-nums">{score.toFixed(1)}</span>
        <span className="text-xs text-subtle">out of 10</span>
      </p>
    </div>
  );
}
