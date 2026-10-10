"use client";

import { ArrowRight, AudioLines, Briefcase, Lightbulb, Mic, PenLine } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { useGDSession } from "@/components/GDSessionProvider";
import { SeatAvatar } from "@/components/SeatAvatar";
import { MAX_PANEL, MIN_PANEL, panelForSize, USER_SEAT } from "@/lib/personas";
import {
  ABSTRACT_TOPICS,
  DEFAULT_DURATION,
  DURATIONS,
  MAX_MINUTES,
  MIN_MINUTES,
  LANGUAGES,
  PLACEMENT_TOPICS,
  type TopicCategory,
} from "@/lib/topics";

const CATEGORIES = [
  { id: "placement", label: "Placement classics", icon: Briefcase },
  { id: "abstract", label: "Abstract", icon: Lightbulb },
  { id: "custom", label: "Custom", icon: PenLine },
] as const satisfies readonly { id: TopicCategory; label: string; icon: unknown }[];

const CUSTOM_MAX = 120;

export function Lobby() {
  const router = useRouter();
  const { startSession } = useGDSession();
  const ids = useId();

  const [category, setCategory] = useState<TopicCategory>("placement");
  const [preset, setPreset] = useState<string>(PLACEMENT_TOPICS[0]);
  const [custom, setCustom] = useState("");
  const [panelSize, setPanelSize] = useState(3);
  const [language, setLanguage] = useState<string>(LANGUAGES[0].value);
  const [minutes, setMinutesValue] = useState<number>(DEFAULT_DURATION);
  const [minutesText, setMinutesText] = useState(String(DEFAULT_DURATION));
  const setMinutes = (m: number) => {
    setMinutesValue(m);
    setMinutesText(String(m));
  };
  const [field, setField] = useState("");
  const [interests, setInterests] = useState("");

  const topic = (category === "custom" ? custom : preset).trim();
  const panel = panelForSize(panelSize);

  function chooseCategory(next: TopicCategory) {
    setCategory(next);
    if (next === "placement") setPreset(PLACEMENT_TOPICS[0]);
    if (next === "abstract") setPreset(ABSTRACT_TOPICS[0]);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!topic) return;
    // Started inside the click so the browser allows mic + audio playback;
    // the arena renders connecting/error states from shared session state.
    const profile =
      field.trim() || interests.trim()
        ? { field: field.trim(), interests: interests.trim() }
        : undefined;
    void startSession({
      topic,
      panel_size: panelSize,
      language,
      profile,
      duration_seconds: minutes * 60,
    });
    router.push("/arena");
  }

  const topics = category === "abstract" ? ABSTRACT_TOPICS : PLACEMENT_TOPICS;

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 px-4 pt-8 pb-36 sm:px-6 sm:pt-14 lg:pb-16">
      <header className="animate-fade-up mb-10 space-y-4">
        <div className="flex items-center gap-2 text-primary">
          <AudioLines aria-hidden className="size-6" />
          <span className="font-mono text-sm uppercase tracking-widest">GD Arena</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Set up your group discussion
        </h1>
        <p className="max-w-2xl text-lg text-muted">
          Pick a topic and a panel. The AI panelists discuss it live and turn to you with
          questions along the way. Answer by voice, then get a detailed evaluation.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        {/* Topic */}
        <fieldset className="min-w-0 space-y-5 glass-card p-5 sm:p-6">
          <legend className="sr-only">Topic</legend>
          <h2 className="text-lg font-semibold" aria-hidden>
            1. Choose a topic
          </h2>

          <div role="group" aria-label="Topic type" className="flex flex-wrap gap-2">
            {CATEGORIES.map(({ id, label, icon: Icon }) => {
              const selected = category === id;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => chooseCategory(id)}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                    selected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border-strong text-muted hover:border-primary hover:text-foreground"
                  }`}
                >
                  <Icon aria-hidden className="size-4" />
                  {label}
                </button>
              );
            })}
          </div>

          {category === "custom" ? (
            <div className="space-y-2">
              <label htmlFor={`${ids}-custom`} className="block text-sm font-medium text-muted">
                Your topic
              </label>
              <input
                id={`${ids}-custom`}
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                maxLength={CUSTOM_MAX}
                placeholder="e.g. Should coding be taught in primary school?"
                autoFocus
                className="w-full rounded-2xl border border-border bg-background/60 px-4 py-3 text-foreground placeholder:text-subtle focus:border-primary focus:outline-none focus:ring-4 focus:ring-primary/15"
              />
              <p className="text-right text-xs text-subtle" aria-live="polite">
                {custom.length}/{CUSTOM_MAX}
              </p>
            </div>
          ) : (
            <div
              role="radiogroup"
              aria-label={category === "abstract" ? "Abstract topics" : "Placement topics"}
              className="grid gap-2 sm:grid-cols-2"
            >
              {topics.map((t) => (
                <label
                  key={t}
                  className="flex cursor-pointer items-center gap-3 min-h-12 rounded-2xl border border-border bg-background/30 px-4 py-3 text-muted transition-colors hover:border-border-strong has-checked:border-primary has-checked:bg-primary/10 has-checked:text-foreground has-focus-visible:outline-2 has-focus-visible:outline-ring"
                >
                  <input
                    type="radio"
                    name="topic"
                    value={t}
                    checked={preset === t}
                    onChange={() => setPreset(t)}
                    className="size-4 accent-primary focus-visible:outline-none"
                  />
                  <span>{t}</span>
                </label>
              ))}
            </div>
          )}
        </fieldset>

        {/* Panel + start */}
        <div className="space-y-6">
          <fieldset className="space-y-5 glass-card p-5 sm:p-6">
            <legend className="sr-only">Panel</legend>
            <h2 className="text-lg font-semibold" aria-hidden>
              2. Panel
            </h2>

            <div className="space-y-3">
              <div className="flex items-baseline justify-between">
                <label htmlFor={`${ids}-size`} className="text-sm font-medium text-muted">
                  AI panelists
                </label>
                <output htmlFor={`${ids}-size`} className="font-mono text-2xl font-semibold text-primary">
                  {panelSize}
                </output>
              </div>
              <input
                id={`${ids}-size`}
                type="range"
                min={MIN_PANEL}
                max={MAX_PANEL}
                step={1}
                value={panelSize}
                onChange={(e) => setPanelSize(Number(e.target.value))}
                className="w-full accent-primary"
              />
              <div className="flex justify-between font-mono text-xs text-subtle" aria-hidden>
                {Array.from({ length: MAX_PANEL - MIN_PANEL + 1 }, (_, i) => (
                  <span key={i}>{MIN_PANEL + i}</span>
                ))}
              </div>
            </div>

            <ul className="space-y-3" aria-label="Who's at the table">
              {[USER_SEAT, ...panel].map((seat) => (
                <li key={seat.id} className="flex items-center gap-3">
                  <SeatAvatar seat={seat} size="sm" />
                  <div className="min-w-0">
                    <p className="font-medium">
                      {seat.id === "user" ? (
                        seat.label
                      ) : (
                        <>
                          {seat.defaultName} <span className="text-subtle">· {seat.label}</span>
                        </>
                      )}
                    </p>
                    <p className="truncate text-sm text-subtle">{seat.blurb}</p>
                  </div>
                </li>
              ))}
            </ul>

            <div className="space-y-2">
              <label htmlFor={`${ids}-time`} className="block text-sm font-medium text-muted">
                Discussion length
              </label>
              <div role="group" aria-label="Preset lengths" className="flex flex-wrap gap-2">
                {DURATIONS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={minutes === m}
                    onClick={() => setMinutes(m)}
                    className={`min-h-10 min-w-12 rounded-full border px-3 text-sm font-semibold transition-colors ${
                      minutes === m
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border-strong text-muted hover:border-primary hover:text-foreground"
                    }`}
                  >
                    {m} min
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <input
                  id={`${ids}-time`}
                  type="number"
                  inputMode="numeric"
                  min={MIN_MINUTES}
                  max={MAX_MINUTES}
                  value={minutesText}
                  onChange={(e) => {
                    setMinutesText(e.target.value);
                    const n = Math.round(Number(e.target.value));
                    if (n >= MIN_MINUTES && n <= MAX_MINUTES) setMinutes(n);
                  }}
                  onBlur={() => setMinutesText(String(minutes))}
                  className="w-24 rounded-2xl border border-border bg-background/60 px-4 py-2.5 text-foreground focus:border-primary focus:outline-none focus:ring-4 focus:ring-primary/15"
                />
                <span className="text-sm text-muted">minutes (custom, 1 to 60)</span>
              </div>
              <p className="text-xs text-subtle">
                When time is up the moderator cuts in and sums up the discussion.
              </p>
            </div>

            <div className="space-y-2">
              <label htmlFor={`${ids}-lang`} className="block text-sm font-medium text-muted">
                Language
              </label>
              <select
                id={`${ids}-lang`}
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-2xl border border-border bg-background/60 px-4 py-3 text-foreground placeholder:text-subtle focus:border-primary focus:outline-none focus:ring-4 focus:ring-primary/15"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
          </fieldset>

          <fieldset className="space-y-4 glass-card p-5 sm:p-6">
            <legend className="sr-only">About you</legend>
            <div>
              <h2 className="text-lg font-semibold" aria-hidden>
                3. About you <span className="text-sm font-normal text-subtle">(optional)</span>
              </h2>
              <p className="mt-1 text-sm text-subtle">The panel tailors its questions to you.</p>
            </div>
            <div className="space-y-2">
              <label htmlFor={`${ids}-field`} className="block text-sm font-medium text-muted">
                Your tech field
              </label>
              <input
                id={`${ids}-field`}
                value={field}
                onChange={(e) => setField(e.target.value)}
                maxLength={80}
                placeholder="e.g. Backend engineering"
                className="w-full rounded-2xl border border-border bg-background/60 px-4 py-3 text-foreground placeholder:text-subtle focus:border-primary focus:outline-none focus:ring-4 focus:ring-primary/15"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor={`${ids}-interests`} className="block text-sm font-medium text-muted">
                Topics you know well
              </label>
              <input
                id={`${ids}-interests`}
                value={interests}
                onChange={(e) => setInterests(e.target.value)}
                maxLength={200}
                placeholder="e.g. Kafka, system design, fintech"
                className="w-full rounded-2xl border border-border bg-background/60 px-4 py-3 text-foreground placeholder:text-subtle focus:border-primary focus:outline-none focus:ring-4 focus:ring-primary/15"
              />
            </div>
          </fieldset>

          {/* Pinned to the bottom of the screen on phones, inline on desktop. */}
          <div className="max-lg:float-pane max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-30 max-lg:border-t max-lg:px-4 max-lg:pt-3 max-lg:pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
            <button type="submit" disabled={!topic} className="btn-primary w-full py-4 text-lg">
              Enter the arena
              <ArrowRight aria-hidden className="size-5" />
            </button>
          </div>
          <p className="flex items-start gap-2 text-sm text-subtle">
            <Mic aria-hidden className="mt-0.5 size-4 shrink-0" />
            Your browser will ask for microphone access. The panel will turn to you with a
            question when it&apos;s your turn to speak. Say &ldquo;I&apos;d like to continue
            another day&rdquo; anytime you answer to wrap up with a summary.
          </p>
        </div>
      </form>
    </main>
  );
}
