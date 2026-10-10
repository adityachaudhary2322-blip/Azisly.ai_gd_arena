"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  type StartSessionOptions,
  type UseGDSocketResult,
  useGDSocket,
} from "@/hooks/useGDSocket";
import { assignSeats, panelForSize, type Seat, type SeatId } from "@/lib/personas";
import { saveLastSession } from "@/lib/sessionStore";

interface GDSessionContextValue extends UseGDSocketResult {
  /** What the current/last session was started with. */
  config: StartSessionOptions | null;
  panel: Seat[];
  /** AI speaker name -> seat on the panel. */
  seats: Map<string, SeatId>;
}

const GDSessionContext = createContext<GDSessionContextValue | null>(null);

/** Keeps one live GD session alive across lobby -> arena -> report navigation. */
export function GDSessionProvider({ children }: { children: React.ReactNode }) {
  const socket = useGDSocket();
  const [config, setConfig] = useState<StartSessionOptions | null>(null);

  const { startSession: start, reportData, transcriptList, speakerAvatars } = socket;

  const startSession = useCallback(
    (options: StartSessionOptions) => {
      setConfig(options);
      return start(options);
    },
    [start],
  );

  const panel = useMemo(() => panelForSize(config?.panel_size ?? 3), [config]);
  const seats = useMemo(() => assignSeats(panel, speakerAvatars), [panel, speakerAvatars]);

  // Persist the finished session so /report survives a refresh.
  useEffect(() => {
    if (reportData && config) {
      saveLastSession({ config, report: reportData, transcript: transcriptList, speakerAvatars });
    }
  }, [reportData, config, transcriptList, speakerAvatars]);

  const value = useMemo(
    () => ({ ...socket, startSession, config, panel, seats }),
    [socket, startSession, config, panel, seats],
  );

  return <GDSessionContext.Provider value={value}>{children}</GDSessionContext.Provider>;
}

export function useGDSession(): GDSessionContextValue {
  const ctx = useContext(GDSessionContext);
  if (!ctx) throw new Error("useGDSession must be used inside <GDSessionProvider>");
  return ctx;
}
