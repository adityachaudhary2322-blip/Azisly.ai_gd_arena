import type { Ref } from "react";

import type { Seat } from "@/lib/personas";

const SIZES = {
  sm: "size-10 [&_svg]:size-5",
  md: "size-14 [&_svg]:size-6",
  lg: "size-16 sm:size-20 [&_svg]:size-7 sm:[&_svg]:size-8",
} as const;

interface SeatAvatarProps {
  seat: Seat;
  size?: keyof typeof SIZES;
  active?: boolean;
  /** Pulse gently to show this seat is expected to speak next. */
  awaiting?: boolean;
  /** Receives the ring element so callers can drive `--level` (0–1) per frame. */
  ringRef?: Ref<HTMLDivElement>;
}

/** Circular persona avatar; when `active`, its ring glows in proportion to `--level`. */
export function SeatAvatar({
  seat,
  size = "md",
  active = false,
  awaiting = false,
  ringRef,
}: SeatAvatarProps) {
  const Icon = seat.icon;
  return (
    <div
      ref={ringRef}
      className={`seat-ring ${SIZES[size]} flex shrink-0 items-center justify-center rounded-full bg-surface-raised`}
      data-active={active || undefined}
      data-awaiting={awaiting || undefined}
      style={{ "--seat": seat.color } as React.CSSProperties}
      aria-hidden
    >
      <Icon style={{ color: seat.color }} strokeWidth={2} />
    </div>
  );
}
