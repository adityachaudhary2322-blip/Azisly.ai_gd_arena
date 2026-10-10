import { useSyncExternalStore } from "react";

import type { StartSessionOptions } from "@/hooks/useGDSocket";
import type { FinalReport, TranscriptUpdate } from "@/types/gd";

export interface StoredSession {
  config: StartSessionOptions;
  report: FinalReport;
  transcript: TranscriptUpdate[];
  speakerAvatars: Record<string, string>;
}

const KEY = "gd-arena:last-session";
const listeners = new Set<() => void>();

let cachedRaw: string | null = null;
let cachedValue: StoredSession | null = null;

function read(): StoredSession | null {
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedValue = raw ? (JSON.parse(raw) as StoredSession) : null;
    } catch {
      cachedValue = null;
    }
  }
  return cachedValue;
}

export function saveLastSession(session: StoredSession): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // storage unavailable (private mode, quota) — report still works in-memory
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Last finished session from sessionStorage; null on the server and if absent. */
export function useLastSession(): StoredSession | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
