/**
 * GD Arena WebSocket & state contract.
 * Mirrors SCHEMA.md exactly — field names are snake_case on the wire, so they
 * stay snake_case here. Update both files together.
 */

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

/** AI panelist display name, e.g. "Arjun". Dynamic, so not a closed union. */
export type AgentName = string;
/** `"User"` is reserved for the candidate; anything else is an AI panelist. */
export type Speaker = "User" | AgentName;

/** Agreed persona ids, in panel order (a panel of N takes the first N). */
export type AvatarId =
  | "moderator"
  | "dominator"
  | "data_driven"
  | "bridger"
  | "quiet_analyst";

// ---------------------------------------------------------------------------
// Client -> Server
// ---------------------------------------------------------------------------

export interface StartSession {
  type: "start_session";
  topic: string;
  panel_size: number;
  /** BCP-47 tag, e.g. "en-IN"; "hi-IN" is Hindi + English (Hinglish). */
  language: string;
  /** Optional background used to tailor panel questions. */
  profile?: CandidateProfile;
}

export interface CandidateProfile {
  /** e.g. "Backend engineering". */
  field?: string;
  /** e.g. "Kafka, system design, fintech". */
  interests?: string;
}

export interface AudioChunk {
  type: "audio_chunk";
  /** Base64-encoded audio. */
  data: string;
}

/** Sent when a clip finishes playing (`turn_id` from its `agent_speaking`). */
export interface PlaybackFinished {
  type: "playback_finished";
  turn_id?: number;
}

/** Legacy barge-in; this client no longer sends it (the panel hands over the floor). */
export interface UserInterrupted {
  type: "user_interrupted";
}

export interface EndSession {
  type: "end_session";
}

export type ClientMessage =
  | StartSession
  | AudioChunk
  | PlaybackFinished
  | UserInterrupted
  | EndSession;

// ---------------------------------------------------------------------------
// Server -> Client
// ---------------------------------------------------------------------------

export interface TranscriptUpdate {
  type: "transcript_update";
  speaker: Speaker;
  text: string;
  /** Seconds since session start. */
  timestamp: number;
  /** Pairs a panelist's line with its `agent_speaking` clip; absent for the candidate. */
  turn_id?: number;
}

export interface AgentSpeaking {
  type: "agent_speaking";
  speaker: AgentName;
  /** Persona identifier; normally one of `AvatarId`. */
  avatar_id: AvatarId | (string & {});
  /** Base64-encoded WAV or MP3. */
  audio_base64: string;
  turn_id?: number;
  /** What the clip says; used to speak it if the audio is a silent placeholder. */
  text?: string;
  /** True when this clip ends by handing the floor to the candidate. */
  yields_floor?: boolean;
}

/** Who holds the floor. The candidate may speak only while it is "user". */
export interface TurnUpdate {
  type: "turn_update";
  floor: "user" | "panel";
  /** Panelist who handed over the floor (when floor is "user"). */
  speaker?: AgentName;
}

export interface AgentInterrupted {
  type: "agent_interrupted";
  speaker: AgentName;
}

export interface TimerTick {
  type: "timer_tick";
  seconds_left: number;
}

export interface ReportMetrics {
  speaking_time_user_percent: number;
  interruptions_handled: number;
  initiative_score: number;
  /** Speaker name ("User" for the candidate) -> percent of speaking time. */
  speaking_time_distribution?: Record<string, number>;
}

export interface FeedbackItem {
  criterion: string;
  quote: string;
  analysis: string;
}

export interface FinalReport {
  type: "final_report";
  metrics: ReportMetrics;
  feedback: FeedbackItem[];
}

export type ServerMessage =
  | TranscriptUpdate
  | AgentSpeaking
  | AgentInterrupted
  | TurnUpdate
  | TimerTick
  | FinalReport;
