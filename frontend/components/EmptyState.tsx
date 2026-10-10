import { ArrowLeft } from "lucide-react";
import Link from "next/link";

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-24 text-center">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="max-w-md text-muted">{body}</p>
      <Link
        href="/"
        className="mt-2 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 font-semibold text-primary-foreground"
      >
        <ArrowLeft aria-hidden className="size-4" />
        Go to lobby
      </Link>
    </main>
  );
}
