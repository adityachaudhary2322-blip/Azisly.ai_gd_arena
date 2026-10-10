"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  AgentName,
  ClientMessage,
  FinalReport,
  ServerMessage,
  Speaker,
  StartSession,
  TranscriptUpdate,
} from "@/types/gd";
import { PERSONAS, personaFromAvatarId } from "@/lib/personas";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

/**
 * Normalizes WebSocket connection URLs: converts http(s) to ws(s) if provided.
 */
export function normalizeWsUrl(rawUrl: string): string {
  let url = rawUrl.trim();
  if (url.startsWith("https://")) {
    url = url.replace(/^https:\/\//i, "wss://");
  } else if (url.startsWith("http://")) {
    url = url.replace(/^http:\/\//i, "ws://");
  }
  url = url.replace(/\/+$/, "");
  if (!url.endsWith("/ws/gd")) {
    url = `${url}/ws/gd`;
  }
  return url;
}

export const DEFAULT_GD_WS_URL =
  process.env.NEXT_PUBLIC_WS_URL && process.env.NEXT_PUBLIC_WS_URL.trim()
    ? normalizeWsUrl(process.env.NEXT_PUBLIC_WS_URL)
    : "ws://localhost:8000/ws/gd";

/**
 * Wire format for outgoing `audio_chunk.data`: base64 of raw PCM,
 * signed 16-bit little-endian, mono, 16 kHz, 100 ms per chunk.
 *
 * Chunks are sent only while the candidate holds the floor (a panelist asked
 * them a question) and the VAD hears them speaking. The backend treats every
 * chunk as speech, so streaming silence or speaker echo would derail turns.
 */
const TARGET_SAMPLE_RATE = 16_000;
const CHUNK_MS = 100;
/** Audio kept from just before speech onset so the first syllable isn't clipped. */
const PRE_ROLL_CHUNKS = 3;

/** VAD tuning. Levels are RMS of float samples in [-1, 1]. */
const VAD_FRAME_MS = 20;
const VAD_MIN_RMS = 0.02;
const VAD_NOISE_RATIO = 3; // speech must be this many × the tracked noise floor
const VAD_ECHO_GUARD = 1.6; // extra headroom while AI audio plays (speaker bleed)
const VAD_ONSET_FRAMES = 3; // ~60 ms of speech before we call it speech
const VAD_HANGOVER_FRAMES = 25; // ~500 ms of silence before we call it silence

/** Pause between different panelists, like people taking turns (randomised in range). */
const SPEAKER_GAP_MS: [number, number] = [250, 450];
/** Clips quieter than this peak are placeholders (mock mode) and get spoken by the browser. */
const SILENT_PEAK = 0.002;
/** Release a held transcript line even if its audio never starts. */
const TRANSCRIPT_HOLD_MAX_MS = 15_000;

/** How long to wait for `final_report` after `end_session` before closing. */
const REPORT_TIMEOUT_MS = 30_000;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

/** Who may speak: the AI panel, or the candidate (after being asked). */
export type Floor = "panel" | "user";

export type StartSessionOptions = Omit<StartSession, "type">;

export interface UseGDSocketOptions {
  url?: string;
}

export interface AudioLevels {
  /** Candidate mic level, 0–1. */
  user: number;
  /** AI playback level, 0–1. */
  agent: number;
}

export interface UseGDSocketResult {
  connectionStatus: ConnectionStatus;
  activeSpeaker: Speaker | null;
  transcriptList: TranscriptUpdate[];
  timeLeft: number | null;
  reportData: FinalReport | null;
  error: string | null;
  /** Who holds the floor; the mic only streams while it is "user". */
  floor: Floor | null;
  /** Panelist whose question the candidate is answering. */
  floorAsker: AgentName | null;
  /** Speaker name -> `avatar_id`, learned from `agent_speaking` events. */
  speakerAvatars: Record<string, string>;
  /** Cheap to call every animation frame; reads live analyser values. */
  getAudioLevels: () => AudioLevels;
  startSession: (options: StartSessionOptions) => Promise<void>;
  endSession: () => void;
}

// ---------------------------------------------------------------------------
// AudioWorklet: downsample to 16 kHz PCM16 and report per-frame RMS for VAD.
// Inlined so it needs no file in /public.
// ---------------------------------------------------------------------------

const CAPTURE_WORKLET = /* js */ `
class GDCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = options.processorOptions;
    this.ratio = sampleRate / o.targetRate;
    this.chunkSamples = o.chunkSamples;
    this.levelWindow = Math.max(1, Math.round((sampleRate * o.levelMs) / 1000));
    this.buf = new Int16Array(this.chunkSamples);
    this.len = 0;
    this.acc = 0;
    this.accN = 0;
    this.pos = 0;
    this.last = 0;
    this.sq = 0;
    this.sqN = 0;
  }

  push(v) {
    const c = v < -1 ? -1 : v > 1 ? 1 : v;
    this.buf[this.len++] = c < 0 ? c * 0x8000 : c * 0x7fff;
    if (this.len === this.chunkSamples) {
      this.port.postMessage({ type: "pcm", buffer: this.buf.buffer }, [this.buf.buffer]);
      this.buf = new Int16Array(this.chunkSamples);
      this.len = 0;
    }
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = ch[i];

      this.sq += s * s;
      if (++this.sqN >= this.levelWindow) {
        this.port.postMessage({ type: "level", rms: Math.sqrt(this.sq / this.sqN) });
        this.sq = 0;
        this.sqN = 0;
      }

      // Box-filter decimation (averaging doubles as a crude anti-alias filter).
      this.acc += s;
      this.accN++;
      this.pos += 1;
      while (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        if (this.accN > 0) {
          this.last = this.acc / this.accN;
          this.acc = 0;
          this.accN = 0;
        }
        this.push(this.last);
      }
    }
    return true;
  }
}
registerProcessor("gd-capture", GDCaptureProcessor);
`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step));
  }
  return btoa(binary);
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function isServerMessage(value: unknown): value is ServerMessage {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

function isSilent(buffer: AudioBuffer): boolean {
  const data = buffer.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / 4000));
  for (let i = 0; i < data.length; i += step) {
    if (Math.abs(data[i]) > SILENT_PEAK) return false;
  }
  return true;
}

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

type VoiceGender = "female" | "male";

const FEMALE_VOICE = /female|woman|zira|heera|neerja|swara|kalpana|veena|lekha|samantha|karen|moira|tessa|susan|hazel|aria|jenny|sonia|libby|natasha|clara|ava|allison|kavya|priya|ananya|aditi|raveena/i;
const MALE_VOICE = /\bmale|\bman\b|david|mark|ravi|hemant|prabhat|madhur|daniel|alex|fred|guy|ryan|george|james|thomas|arthur|rishi|aaron|tom|oliver/i;

/** Browser speech language for a session language (Hinglish is Roman script, so read it as en-IN). */
function voiceLanguage(language: string): string {
  return language === "hinglish" ? "en-IN" : language;
}

/** Female personas get a female browser voice, male personas a male one. */
function genderForSpeaker(speaker: string, avatarId?: string): VoiceGender {
  const byAvatar = avatarId ? personaFromAvatarId(avatarId) : null;
  const persona = PERSONAS.find((p) => p.id === byAvatar) ?? PERSONAS.find((p) => p.defaultName === speaker);
  return persona?.voice ?? "male";
}

/** A stable browser voice per panelist, matching gender and preferring the session language. */
function pickVoice(voices: SpeechSynthesisVoice[], lang: string, speaker: string, gender: VoiceGender) {
  const norm = (l: string) => l.replace("_", "-").toLowerCase();
  let pool = voices.filter((v) => norm(v.lang) === norm(lang));
  if (pool.length === 0) pool = voices.filter((v) => norm(v.lang).startsWith(lang.split("-")[0]));
  if (pool.length === 0) pool = voices.filter((v) => norm(v.lang).startsWith("en"));
  const wanted = gender === "female" ? FEMALE_VOICE : MALE_VOICE;
  const other = gender === "female" ? MALE_VOICE : FEMALE_VOICE;
  const matching = pool.filter((v) => wanted.test(v.name));
  // Unlabelled voices are a fallback; never pick a voice clearly of the other gender if avoidable.
  const neutral = pool.filter((v) => !other.test(v.name));
  const choice = matching.length ? matching : neutral.length ? neutral : pool;
  return choice.length ? choice[hashString(speaker) % choice.length] : null;
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Audio engine: mic capture + VAD + sequential playback queue.
// Plain class so it lives outside React's render cycle.
// ---------------------------------------------------------------------------

interface QueuedClip {
  speaker: AgentName;
  gender: VoiceGender;
  turnId: number | null;
  text: string;
  yieldsFloor: boolean;
  decoded: Promise<AudioBuffer | null>;
}

interface AudioEngineCallbacks {
  onChunk: (base64Pcm: string) => void;
  onSpeechStart: () => void;
  onSpeechEnd: () => void;
  onClipStart: (clip: QueuedClip) => void;
  onClipEnd: (clip: QueuedClip) => void;
  onPlaybackIdle: () => void;
}

class GDAudioEngine {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private sink: GainNode | null = null;
  private playbackGain: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private analyserData: Float32Array<ArrayBuffer> | null = null;
  private micLevel = 0;

  // Playback queue
  private queue: QueuedClip[] = [];
  private pumping = false;
  private generation = 0;
  private stopCurrent: (() => void) | null = null;
  private playingBuffer = false;
  private speakingWithBrowser = false;
  private lastSpeaker: string | null = null;
  private lastEndedAt = 0;

  // VAD
  private noiseFloor = 0.01;
  private speaking = false;
  private aboveCount = 0;
  private belowCount = 0;
  private preRoll: string[] = [];
  /** Outgoing audio gate: open only while the candidate holds the floor. */
  private micOpen = false;

  constructor(
    private readonly cb: AudioEngineCallbacks,
    private readonly language: string,
  ) {}

  /** Must be called from a user gesture so the AudioContext may start. */
  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const ctx = new AudioContext({ latencyHint: "interactive" });
    this.ctx = ctx;
    await ctx.resume();

    const moduleUrl = URL.createObjectURL(
      new Blob([CAPTURE_WORKLET], { type: "application/javascript" }),
    );
    try {
      await ctx.audioWorklet.addModule(moduleUrl);
    } finally {
      URL.revokeObjectURL(moduleUrl);
    }

    this.micSource = ctx.createMediaStreamSource(this.stream);
    this.worklet = new AudioWorkletNode(ctx, "gd-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      channelCountMode: "explicit",
      processorOptions: {
        targetRate: TARGET_SAMPLE_RATE,
        chunkSamples: (TARGET_SAMPLE_RATE * CHUNK_MS) / 1000,
        levelMs: VAD_FRAME_MS,
      },
    });
    this.worklet.port.onmessage = (e: MessageEvent) => this.onWorkletMessage(e.data);

    // Some browsers only pull nodes that reach the destination; route through
    // a muted gain so the mic is never audible.
    this.sink = ctx.createGain();
    this.sink.gain.value = 0;
    this.micSource.connect(this.worklet).connect(this.sink).connect(ctx.destination);

    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyserData = new Float32Array(this.analyser.fftSize);
    this.analyser.connect(ctx.destination);

    this.playbackGain = ctx.createGain();
    this.playbackGain.connect(this.analyser);

    // Browsers load speech voices lazily; ask early so the first fallback line has one.
    window.speechSynthesis?.getVoices();
  }

  setMicOpen(open: boolean): void {
    this.micOpen = open;
    if (!open) this.preRoll = [];
  }

  /** Levels normalised to 0–1 for visualisation (speech RMS rarely exceeds ~0.3). */
  getLevels(): AudioLevels {
    let agent = 0;
    if (this.playingBuffer && this.analyser && this.analyserData) {
      this.analyser.getFloatTimeDomainData(this.analyserData);
      let sq = 0;
      for (const v of this.analyserData) sq += v * v;
      agent = Math.min(1, Math.sqrt(sq / this.analyserData.length) * 4);
    } else if (this.speakingWithBrowser) {
      // Browser speech can't be measured; approximate a speaking rhythm.
      const t = performance.now() / 1000;
      agent = 0.35 + 0.25 * Math.abs(Math.sin(t * 7)) * Math.abs(Math.sin(t * 2.3));
    }
    return { user: this.stream ? Math.min(1, this.micLevel * 4) : 0, agent };
  }

  get agentAudioActive(): boolean {
    return this.pumping || this.queue.length > 0;
  }

  /** Queue a clip; clips play one after another, never overlapping. */
  enqueue(
    audioBase64: string,
    speaker: AgentName,
    turnId: number | null,
    text: string,
    yieldsFloor: boolean,
    avatarId?: string,
  ): void {
    const ctx = this.ctx;
    if (!ctx) return;
    // Decoding starts now so it overlaps whatever is playing.
    const decoded = ctx.decodeAudioData(base64ToArrayBuffer(audioBase64)).catch((err) => {
      console.warn("[useGDSocket] failed to decode agent audio", err);
      return null;
    });
    const gender = genderForSpeaker(speaker, avatarId);
    this.queue.push({ speaker, gender, turnId, text, yieldsFloor, decoded });
    if (!this.pumping) void this.pump();
  }

  private async pump(): Promise<void> {
    this.pumping = true;
    const gen = this.generation;
    try {
      while (this.queue.length > 0 && gen === this.generation) {
        const clip = this.queue.shift()!;
        const buffer = await clip.decoded;
        if (gen !== this.generation) return;

        if (this.lastSpeaker && this.lastSpeaker !== clip.speaker) {
          const [lo, hi] = SPEAKER_GAP_MS;
          const wait = lo + Math.random() * (hi - lo) - (performance.now() - this.lastEndedAt);
          if (wait > 0) await sleep(wait);
          if (gen !== this.generation) return;
        }

        this.cb.onClipStart(clip);
        if (buffer && !isSilent(buffer)) await this.playBuffer(buffer);
        else await this.speakWithBrowser(clip);
        if (gen !== this.generation) return;

        this.lastSpeaker = clip.speaker;
        this.lastEndedAt = performance.now();
        this.cb.onClipEnd(clip);
      }
    } finally {
      if (gen === this.generation) {
        this.pumping = false;
        this.cb.onPlaybackIdle();
      }
    }
  }

  private playBuffer(buffer: AudioBuffer): Promise<void> {
    const ctx = this.ctx;
    const out = this.playbackGain;
    if (!ctx || !out) return Promise.resolve();
    return new Promise((resolve) => {
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(out);
      const done = () => {
        source.onended = null;
        source.disconnect();
        this.playingBuffer = false;
        this.stopCurrent = null;
        resolve();
      };
      source.onended = done;
      this.stopCurrent = () => {
        try {
          source.stop();
        } catch {
          // already stopped
        }
        done();
      };
      this.playingBuffer = true;
      source.start();
    });
  }

  /** Fallback for silent placeholder audio (mock mode) or undecodable clips. */
  private speakWithBrowser(clip: QueuedClip): Promise<void> {
    const text = clip.text.trim();
    const estimateMs = Math.max(1200, text.split(/\s+/).length * 450);
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;

    return new Promise((resolve) => {
      let timer: ReturnType<typeof setTimeout>;
      const finish = () => {
        clearTimeout(timer);
        this.speakingWithBrowser = false;
        this.stopCurrent = null;
        resolve();
      };
      this.stopCurrent = () => {
        synth?.cancel();
        finish();
      };

      if (!synth || !text) {
        timer = setTimeout(finish, text ? estimateMs : 300);
        return;
      }
      // Some browsers never fire `end`; never let one clip stall the queue.
      timer = setTimeout(finish, estimateMs * 2 + 3000);

      const utterance = new SpeechSynthesisUtterance(text);
      const lang = voiceLanguage(this.language);
      utterance.lang = lang;
      const voice = pickVoice(synth.getVoices(), lang, clip.speaker, clip.gender);
      if (voice) utterance.voice = voice;
      // Pitch nudges voices apart, in the persona's register, when few voices are installed.
      const spread = (hashString(clip.speaker) % 3) * 0.06;
      utterance.pitch = clip.gender === "female" ? 1.15 + spread : 0.82 + spread;
      utterance.rate = 1.05;
      utterance.onend = finish;
      utterance.onerror = finish;
      this.speakingWithBrowser = true;
      synth.speak(utterance);
    });
  }

  /** Hard-stop all AI audio immediately and drop anything queued. */
  stopPlayback(): void {
    this.generation++;
    this.queue = [];
    this.pumping = false;
    this.lastSpeaker = null;
    this.stopCurrent?.();
    window.speechSynthesis?.cancel();

    const ctx = this.ctx;
    if (ctx && this.playbackGain && this.analyser) {
      // Mute first so there is no audible tail, then swap in a fresh output.
      this.playbackGain.gain.setValueAtTime(0, ctx.currentTime);
      this.playbackGain.disconnect();
      this.playbackGain = ctx.createGain();
      this.playbackGain.connect(this.analyser);
    }
    this.cb.onPlaybackIdle();
  }

  private onWorkletMessage(
    data: { type: "pcm"; buffer: ArrayBuffer } | { type: "level"; rms: number },
  ): void {
    if (data.type === "level") {
      this.runVad(data.rms);
      return;
    }
    if (!this.micOpen) return;
    const chunk = bytesToBase64(new Uint8Array(data.buffer));
    if (this.speaking) {
      this.cb.onChunk(chunk);
    } else {
      this.preRoll.push(chunk);
      if (this.preRoll.length > PRE_ROLL_CHUNKS) this.preRoll.shift();
    }
  }

  private runVad(rms: number): void {
    this.micLevel = rms;
    const agentActive = this.agentAudioActive;
    let threshold = Math.max(VAD_MIN_RMS, this.noiseFloor * VAD_NOISE_RATIO);
    if (agentActive) threshold *= VAD_ECHO_GUARD;

    if (rms >= threshold) {
      this.belowCount = 0;
      if (!this.speaking && ++this.aboveCount >= VAD_ONSET_FRAMES) {
        this.speaking = true;
        this.cb.onSpeechStart();
        // Send the buffered lead-in so the first syllable reaches the server.
        if (this.micOpen) for (const chunk of this.preRoll) this.cb.onChunk(chunk);
        this.preRoll = [];
      }
      return;
    }

    this.aboveCount = 0;
    // Track ambient noise only in genuine silence (not during AI playback bleed).
    if (!this.speaking && !agentActive) {
      this.noiseFloor = this.noiseFloor * 0.95 + rms * 0.05;
    }
    if (this.speaking && ++this.belowCount >= VAD_HANGOVER_FRAMES) {
      this.speaking = false;
      this.belowCount = 0;
      this.cb.onSpeechEnd();
    }
  }

  /** Stop the microphone but keep the context alive (e.g. awaiting report). */
  stopCapture(): void {
    this.micOpen = false;
    this.preRoll = [];
    if (this.worklet) {
      this.worklet.port.onmessage = null;
      this.worklet.disconnect();
      this.worklet = null;
    }
    this.micSource?.disconnect();
    this.micSource = null;
    this.sink?.disconnect();
    this.sink = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.micLevel = 0;
    if (this.speaking) {
      this.speaking = false;
      this.cb.onSpeechEnd();
    }
  }

  dispose(): void {
    this.stopCapture();
    this.stopPlayback();
    void this.ctx?.close();
    this.ctx = null;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGDSocket({
  url = DEFAULT_GD_WS_URL,
}: UseGDSocketOptions = {}): UseGDSocketResult {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("idle");
  const [activeSpeaker, setActiveSpeaker] = useState<Speaker | null>(null);
  const [transcriptList, setTranscriptList] = useState<TranscriptUpdate[]>([]);
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [reportData, setReportData] = useState<FinalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [floor, setFloor] = useState<Floor | null>(null);
  const [floorAsker, setFloorAsker] = useState<AgentName | null>(null);
  const [speakerAvatars, setSpeakerAvatars] = useState<Record<string, string>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const engineRef = useRef<GDAudioEngine | null>(null);
  const reportTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const floorRef = useRef<Floor | null>(null);
  /** Panelist lines wait here until their audio starts, so text and voice stay in sync. */
  const heldLinesRef = useRef(
    new Map<number, { entry: TranscriptUpdate; timer: ReturnType<typeof setTimeout> }>(),
  );
  const startedTurnsRef = useRef(new Set<number>());
  /** Bumped on every start/teardown so stale async work can bail out. */
  const sessionRef = useRef(0);

  const send = useCallback((msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  const appendLine = useCallback((entry: TranscriptUpdate) => {
    setTranscriptList((list) => [...list, entry]);
  }, []);

  const releaseLine = useCallback(
    (turnId: number) => {
      const held = heldLinesRef.current.get(turnId);
      if (!held) return;
      clearTimeout(held.timer);
      heldLinesRef.current.delete(turnId);
      appendLine(held.entry);
    },
    [appendLine],
  );

  const releaseAllLines = useCallback(() => {
    const ids = [...heldLinesRef.current.keys()].sort((a, b) => a - b);
    ids.forEach(releaseLine);
  }, [releaseLine]);

  const applyFloor = useCallback((next: Floor | null, asker: AgentName | null = null) => {
    floorRef.current = next;
    setFloor(next);
    setFloorAsker(next === "user" ? asker : null);
    engineRef.current?.setMicOpen(next === "user");
    if (next !== "user") setActiveSpeaker((s) => (s === "User" ? null : s));
  }, []);

  const teardown = useCallback(() => {
    sessionRef.current++;
    if (reportTimerRef.current) {
      clearTimeout(reportTimerRef.current);
      reportTimerRef.current = null;
    }
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
      if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) {
        ws.close(1000, "client teardown");
      }
    }
    engineRef.current?.dispose();
    engineRef.current = null;
    for (const { timer } of heldLinesRef.current.values()) clearTimeout(timer);
    heldLinesRef.current.clear();
    startedTurnsRef.current.clear();
    floorRef.current = null;
  }, []);

  useEffect(() => teardown, [teardown]);

  const startSession = useCallback(
    async (options: StartSessionOptions) => {
      teardown();
      const session = sessionRef.current;

      setError(null);
      setTranscriptList([]);
      setReportData(null);
      setTimeLeft(null);
      setActiveSpeaker(null);
      setSpeakerAvatars({});
      setFloor(null);
      setFloorAsker(null);
      setConnectionStatus("connecting");

      const engine = new GDAudioEngine(
        {
          onChunk: (data) => send({ type: "audio_chunk", data }),
          onSpeechStart: () => {
            if (floorRef.current === "user") setActiveSpeaker("User");
          },
          onSpeechEnd: () => setActiveSpeaker((s) => (s === "User" ? null : s)),
          onClipStart: (clip) => {
            setActiveSpeaker(clip.speaker);
            if (clip.turnId !== null) {
              startedTurnsRef.current.add(clip.turnId);
              releaseLine(clip.turnId);
            }
          },
          onClipEnd: (clip) => {
            send(
              clip.turnId !== null
                ? { type: "playback_finished", turn_id: clip.turnId }
                : { type: "playback_finished" },
            );
            // Open the mic the moment the question ends; the server confirms with turn_update.
            if (clip.yieldsFloor) applyFloor("user", clip.speaker);
          },
          onPlaybackIdle: () =>
            setActiveSpeaker((s) => (s !== null && s !== "User" ? null : s)),
        },
        options.language,
      );
      engineRef.current = engine;

      try {
        await engine.start();
      } catch (err) {
        if (session !== sessionRef.current) return;
        teardown();
        setConnectionStatus("error");
        setError(
          err instanceof DOMException && err.name === "NotAllowedError"
            ? "Microphone permission was denied."
            : `Could not start audio: ${err instanceof Error ? err.message : String(err)}`,
        );
        return;
      }
      if (session !== sessionRef.current) return; // torn down while awaiting

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        send({ type: "start_session", ...options });
        applyFloor("panel");
        setConnectionStatus("connected");
      };

      ws.onmessage = (event: MessageEvent) => {
        let msg: unknown;
        try {
          msg = JSON.parse(event.data as string);
        } catch {
          console.warn("[useGDSocket] non-JSON message ignored");
          return;
        }
        if (!isServerMessage(msg)) return;

        switch (msg.type) {
          case "transcript_update": {
            const turnId = msg.turn_id;
            if (msg.speaker === "User" || turnId == null || startedTurnsRef.current.has(turnId)) {
              appendLine(msg);
            } else {
              heldLinesRef.current.set(turnId, {
                entry: msg,
                timer: setTimeout(() => releaseLine(turnId), TRANSCRIPT_HOLD_MAX_MS),
              });
            }
            break;
          }
          case "agent_speaking":
            setSpeakerAvatars((m) =>
              m[msg.speaker] === msg.avatar_id ? m : { ...m, [msg.speaker]: msg.avatar_id },
            );
            engine.enqueue(
              msg.audio_base64,
              msg.speaker,
              msg.turn_id ?? null,
              msg.text ?? "",
              msg.yields_floor === true,
              msg.avatar_id,
            );
            break;
          case "agent_interrupted":
            engine.stopPlayback();
            releaseAllLines();
            break;
          case "turn_update":
            applyFloor(msg.floor, msg.speaker ?? null);
            break;
          case "timer_tick":
            setTimeLeft(msg.seconds_left);
            break;
          case "final_report":
            releaseAllLines();
            setReportData(msg);
            setTimeLeft(0);
            teardown();
            setFloor(null);
            setFloorAsker(null);
            setConnectionStatus("disconnected");
            break;
          default:
            console.warn("[useGDSocket] unknown message type", msg);
        }
      };

      ws.onerror = () => {
        setError(`WebSocket error (${url}).`);
        setConnectionStatus("error");
      };

      ws.onclose = (event: CloseEvent) => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        engineRef.current?.dispose();
        engineRef.current = null;
        setActiveSpeaker(null);
        setFloor(null);
        setConnectionStatus((s) => (s === "error" ? s : "disconnected"));
        if (!event.wasClean && event.code !== 1000) {
          setError((e) => e ?? `Connection closed unexpectedly (code ${event.code}).`);
        }
      };
    },
    [appendLine, applyFloor, releaseAllLines, releaseLine, send, teardown, url],
  );

  const endSession = useCallback(() => {
    const engine = engineRef.current;
    engine?.stopCapture();
    engine?.stopPlayback();
    setActiveSpeaker(null);
    applyFloor(null);

    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      teardown();
      setConnectionStatus("disconnected");
      return;
    }

    // Keep the socket open so the server can deliver `final_report`.
    send({ type: "end_session" });
    if (reportTimerRef.current) clearTimeout(reportTimerRef.current);
    reportTimerRef.current = setTimeout(() => {
      teardown();
      setConnectionStatus("disconnected");
      setError((e) => e ?? "Timed out waiting for the final report.");
    }, REPORT_TIMEOUT_MS);
  }, [applyFloor, send, teardown]);

  const getAudioLevels = useCallback(
    (): AudioLevels => engineRef.current?.getLevels() ?? { user: 0, agent: 0 },
    [],
  );

  return {
    connectionStatus,
    activeSpeaker,
    transcriptList,
    timeLeft,
    reportData,
    error,
    floor,
    floorAsker,
    speakerAvatars,
    getAudioLevels,
    startSession,
    endSession,
  };
}
