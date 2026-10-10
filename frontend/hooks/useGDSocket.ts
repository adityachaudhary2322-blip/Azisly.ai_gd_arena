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

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const DEFAULT_GD_WS_URL = "ws://localhost:8000/ws/gd";

/**
 * Wire format for outgoing `audio_chunk.data`: base64 of raw PCM,
 * signed 16-bit little-endian, mono, 16 kHz, 100 ms per chunk.
 */
const TARGET_SAMPLE_RATE = 16_000;
const CHUNK_MS = 100;

/** VAD tuning. Levels are RMS of float samples in [-1, 1]. */
const VAD_FRAME_MS = 20;
const VAD_MIN_RMS = 0.02;
const VAD_NOISE_RATIO = 3; // speech must be this many × the tracked noise floor
const VAD_ECHO_GUARD = 1.6; // extra headroom while AI audio plays (speaker bleed)
const VAD_ONSET_FRAMES = 3; // ~60 ms of speech before we call it speech
const VAD_HANGOVER_FRAMES = 25; // ~500 ms of silence before we call it silence

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

// ---------------------------------------------------------------------------
// Audio engine: mic capture + VAD + gapless playback queue.
// Plain class so it lives outside React's render cycle.
// ---------------------------------------------------------------------------

interface AudioEngineCallbacks {
  onChunk: (base64Pcm: string) => void;
  /** Speech onset detected. `agentAudioActive` = AI audio was playing or queued. */
  onSpeechStart: (agentAudioActive: boolean) => void;
  onSpeechEnd: () => void;
  onAgentAudioStart: (speaker: AgentName) => void;
  onAgentAudioIdle: () => void;
}

interface ScheduledClip {
  source: AudioBufferSourceNode;
  startTimer: ReturnType<typeof setTimeout>;
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
  private scheduled: ScheduledClip[] = [];
  private playheadEnd = 0;
  private decodeChain: Promise<void> = Promise.resolve();
  private pendingDecodes = 0;
  private generation = 0;

  // VAD
  private noiseFloor = 0.01;
  private speaking = false;
  private aboveCount = 0;
  private belowCount = 0;

  /** Gate for outgoing audio; enabled once the server session is live. */
  streaming = false;

  constructor(private readonly cb: AudioEngineCallbacks) {}

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
  }

  /** Levels normalised to 0–1 for visualisation (speech RMS rarely exceeds ~0.3). */
  getLevels(): AudioLevels {
    let agent = 0;
    if (this.analyser && this.analyserData && this.scheduled.length > 0) {
      this.analyser.getFloatTimeDomainData(this.analyserData);
      let sq = 0;
      for (const v of this.analyserData) sq += v * v;
      agent = Math.sqrt(sq / this.analyserData.length);
    }
    const norm = (rms: number) => Math.min(1, rms * 4);
    return { user: this.stream ? norm(this.micLevel) : 0, agent: norm(agent) };
  }

  get agentAudioActive(): boolean {
    return this.scheduled.length > 0 || this.pendingDecodes > 0;
  }

  /** Queue base64 WAV/MP3 to play strictly after everything already queued. */
  enqueue(audioBase64: string, speaker: AgentName): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const gen = this.generation;
    this.pendingDecodes++;

    // Decode in arrival order so clips can never be reordered.
    this.decodeChain = this.decodeChain.then(async () => {
      try {
        if (gen !== this.generation) return;
        const buffer = await ctx.decodeAudioData(base64ToArrayBuffer(audioBase64));
        if (gen !== this.generation) return;
        this.schedule(buffer, speaker);
      } catch (err) {
        console.warn("[useGDSocket] failed to decode agent audio", err);
      } finally {
        if (gen === this.generation) {
          this.pendingDecodes--;
          if (!this.agentAudioActive) this.cb.onAgentAudioIdle();
        }
      }
    });
  }

  private schedule(buffer: AudioBuffer, speaker: AgentName): void {
    const ctx = this.ctx;
    const out = this.playbackGain;
    if (!ctx || !out) return;

    // Start exactly where the previous clip ends: no overlap, no gap.
    const startAt = Math.max(ctx.currentTime, this.playheadEnd);
    this.playheadEnd = startAt + buffer.duration;

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(out);
    source.start(startAt);

    const clip: ScheduledClip = {
      source,
      startTimer: setTimeout(
        () => this.cb.onAgentAudioStart(speaker),
        Math.max(0, (startAt - ctx.currentTime) * 1000),
      ),
    };
    this.scheduled.push(clip);

    source.onended = () => {
      this.scheduled = this.scheduled.filter((c) => c !== clip);
      source.disconnect();
      if (!this.agentAudioActive) this.cb.onAgentAudioIdle();
    };
  }

  /** Hard-stop all AI audio immediately and drop anything queued or decoding. */
  stopPlayback(): void {
    this.generation++;
    this.pendingDecodes = 0;
    this.playheadEnd = 0;

    const ctx = this.ctx;
    if (ctx && this.playbackGain && this.analyser) {
      // Mute first so there is no audible tail, then swap in a fresh output.
      this.playbackGain.gain.setValueAtTime(0, ctx.currentTime);
      this.playbackGain.disconnect();
      this.playbackGain = ctx.createGain();
      this.playbackGain.connect(this.analyser);
    }

    for (const clip of this.scheduled) {
      clearTimeout(clip.startTimer);
      clip.source.onended = null;
      try {
        clip.source.stop();
      } catch {
        // already stopped
      }
      clip.source.disconnect();
    }
    this.scheduled = [];
    this.cb.onAgentAudioIdle();
  }

  private onWorkletMessage(
    data: { type: "pcm"; buffer: ArrayBuffer } | { type: "level"; rms: number },
  ): void {
    if (data.type === "pcm") {
      if (this.streaming) this.cb.onChunk(bytesToBase64(new Uint8Array(data.buffer)));
    } else {
      this.runVad(data.rms);
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
        this.cb.onSpeechStart(agentActive);
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
    this.streaming = false;
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
  const [speakerAvatars, setSpeakerAvatars] = useState<Record<string, string>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const engineRef = useRef<GDAudioEngine | null>(null);
  const reportTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Bumped on every start/teardown so stale async work can bail out. */
  const sessionRef = useRef(0);

  const send = useCallback((msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
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
      setConnectionStatus("connecting");

      const engine = new GDAudioEngine({
        onChunk: (data) => send({ type: "audio_chunk", data }),
        onSpeechStart: (agentAudioActive) => {
          if (agentAudioActive) {
            // Barge-in: kill AI audio locally first, then tell the server.
            engine.stopPlayback();
            send({ type: "user_interrupted" });
          }
          setActiveSpeaker("User");
        },
        onSpeechEnd: () => setActiveSpeaker((s) => (s === "User" ? null : s)),
        onAgentAudioStart: (speaker) => setActiveSpeaker(speaker),
        onAgentAudioIdle: () =>
          setActiveSpeaker((s) => (s !== null && s !== "User" ? null : s)),
      });
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
        engine.streaming = true;
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
          case "transcript_update":
            setTranscriptList((list) => [...list, msg]);
            break;
          case "agent_speaking":
            setSpeakerAvatars((m) =>
              m[msg.speaker] === msg.avatar_id ? m : { ...m, [msg.speaker]: msg.avatar_id },
            );
            engine.enqueue(msg.audio_base64, msg.speaker);
            break;
          case "agent_interrupted":
            engine.stopPlayback();
            break;
          case "timer_tick":
            setTimeLeft(msg.seconds_left);
            break;
          case "final_report":
            setReportData(msg);
            setTimeLeft(0);
            teardown();
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
        setConnectionStatus((s) => (s === "error" ? s : "disconnected"));
        if (!event.wasClean && event.code !== 1000) {
          setError((e) => e ?? `Connection closed unexpectedly (code ${event.code}).`);
        }
      };
    },
    [send, teardown, url],
  );

  const endSession = useCallback(() => {
    const engine = engineRef.current;
    engine?.stopCapture();
    engine?.stopPlayback();
    setActiveSpeaker(null);

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
  }, [send, teardown]);

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
    speakerAvatars,
    getAudioLevels,
    startSession,
    endSession,
  };
}
