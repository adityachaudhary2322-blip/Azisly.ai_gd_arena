import type { Metadata } from "next";

import { Arena } from "@/components/arena/Arena";

export const metadata: Metadata = { title: "Arena · GD Arena" };

export default function ArenaPage() {
  return <Arena />;
}
