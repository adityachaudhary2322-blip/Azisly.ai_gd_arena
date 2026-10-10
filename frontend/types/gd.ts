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
  /** BCP-47 tag, e.g. "en-IN". */
  language: string;
}

export interface AudioChunk {
  type: "audio_chunk";
  /** Base64-encoded audio. */
  data: string;
}

export interface UserInterrupted {
  type: "user_interrupted";
}

export interface EndSession {
  type: "end_session";
}

export type ClientMessage =
  | StartSession
  | AudioChunk
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
}

export interface AgentSpeaking {
  type: "agent_speaking";
  speaker: AgentName;
  /** Persona identifier; normally one of `AvatarId`. */
  avatar_id: AvatarId | (string & {});
  /** Base64-encoded WAV or MP3. */
  audio_base64: string;
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
  /**
   * Speaker name ("User" for the candidate) -> percent of speaking time.
   * Confirmed by the backend but not yet in SCHEMA.md; shape assumed.
   */
  speaking_time_distribution?: Record<string, number>;
}

export type ServerMessage =
  | TranscriptUpdate
  | AgentSpeaking
  | AgentInterrupted
  | TimerTick
  | FinalReport;
