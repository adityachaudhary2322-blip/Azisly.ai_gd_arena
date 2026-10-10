import {
  ChartColumn,
  Glasses,
  Handshake,
  type LucideIcon,
  Megaphone,
  Scale,
  User,
} from "lucide-react";

import type { AvatarId, Speaker } from "@/types/gd";

export type PersonaId = AvatarId;

export type SeatId = PersonaId | "user";

export interface Seat {
  id: SeatId;
  label: string;
  /** Name the backend uses for this persona; "You" for the candidate. */
  defaultName: string;
  blurb: string;
  icon: LucideIcon;
  /** Identity colour for the avatar ring. Always paired with a text label. */
  color: string;
}

export const USER_SEAT: Seat = {
  id: "user",
  label: "You",
  defaultName: "You",
  blurb: "Candidate",
  icon: User,
  color: "#10b981",
};

/** Ordered: a panel of size N takes the first N personas. */
export const PERSONAS: readonly Seat[] = [
  {
    id: "moderator",
    label: "Moderator",
    defaultName: "Arjun",
    blurb: "Keeps time and steers the discussion",
    icon: Scale,
    color: "#6366f1",
  },
  {
    id: "dominator",
    label: "Dominator",
    defaultName: "Kabir",
    blurb: "Talks over others, pushes hard opinions",
    icon: Megaphone,
    color: "#e11d48",
  },
  {
    id: "data_driven",
    label: "Data-Driven",
    defaultName: "Anushka",
    blurb: "Backs every point with numbers",
    icon: ChartColumn,
    color: "#d97706",
  },
  {
    id: "bridger",
    label: "Bridger",
    defaultName: "Priya",
    blurb: "Connects opposing viewpoints",
    icon: Handshake,
    color: "#0891b2",
  },
  {
    id: "quiet_analyst",
    label: "Quiet Analyst",
    defaultName: "Rohan",
    blurb: "Speaks rarely, with sharp analysis",
    icon: Glasses,
    color: "#c026d3",
  },
];

export const MIN_PANEL = 3;
export const MAX_PANEL = PERSONAS.length;

export function panelForSize(size: number): Seat[] {
  return PERSONAS.slice(0, Math.min(MAX_PANEL, Math.max(MIN_PANEL, size)));
}

const SEATS_BY_ID = new Map<SeatId, Seat>(
  [USER_SEAT, ...PERSONAS].map((s) => [s.id, s]),
);

export function seatById(id: SeatId): Seat {
  return SEATS_BY_ID.get(id)!;
}

/** "Data-Driven", "data_driven", "datadriven" all resolve to `data_driven`. */
export function personaFromAvatarId(avatarId: string): PersonaId | null {
  const key = avatarId.toLowerCase().replace(/[^a-z]/g, "");
  const hit = PERSONAS.find((p) => p.id.replace(/_/g, "") === key);
  return hit ? (hit.id as PersonaId) : null;
}

/**
 * Map each AI speaker name to a seat on the current panel. Known `avatar_id`s
 * win; anything unrecognised (or not on this panel) takes the next free seat so it is still shown.
 */
export function assignSeats(
  panel: readonly Seat[],
  speakerAvatars: Record<string, string>,
): Map<string, SeatId> {
  const out = new Map<string, SeatId>();
  const taken = new Set<SeatId>();
  const onPanel = new Set<SeatId>(panel.map((s) => s.id));
  const unknown: string[] = [];

  for (const [name, avatarId] of Object.entries(speakerAvatars)) {
    const persona = personaFromAvatarId(avatarId);
    if (persona && onPanel.has(persona) && !taken.has(persona)) {
      out.set(name, persona);
      taken.add(persona);
    } else {
      unknown.push(name);
    }
  }
  for (const name of unknown) {
    const free =
      panel.find((s) => s.defaultName === name && !taken.has(s.id)) ??
      panel.find((s) => !taken.has(s.id));
    if (!free) break;
    out.set(name, free.id);
    taken.add(free.id);
  }
  return out;
}

export function seatForSpeaker(
  speaker: Speaker | string,
  seats: Map<string, SeatId>,
): Seat | null {
  if (speaker === "User") return USER_SEAT;
  const id = seats.get(speaker);
  if (id) return seatById(id);
  // Not heard via `agent_speaking` yet (e.g. transcript arrived first).
  return PERSONAS.find((p) => p.defaultName === speaker) ?? null;
}
