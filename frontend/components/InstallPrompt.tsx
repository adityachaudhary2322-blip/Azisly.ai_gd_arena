"use client";

import { Download, PlusSquare, Share, X } from "lucide-react";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type InstallEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const SNOOZE_KEY = "gd-arena:install-snoozed-until";
const SNOOZE_DAYS = 7;
const SHOW_AFTER_MS = 4000;

// `beforeinstallprompt` fires once, early, and only to listeners that exist at
// that moment, so capture it when this module loads rather than in an effect.
let deferredInstall: InstallEvent | null = null;
const listeners = new Set<() => void>();
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); // we show our own, better-timed prompt
    deferredInstall = e as InstallEvent;
    listeners.forEach((l) => l());
  });
  window.addEventListener("appinstalled", () => {
    deferredInstall = null;
    listeners.forEach((l) => l());
  });
}

function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/** iOS Safari never fires beforeinstallprompt; it needs Share -> Add to Home Screen. */
function isIOS() {
  return (
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

function snoozed() {
  try {
    return Number(localStorage.getItem(SNOOZE_KEY) || 0) > Date.now();
  } catch {
    return false;
  }
}

/** "Install GD Arena" card: offered a few seconds after load, never mid-discussion. */
export function InstallPrompt() {
  const pathname = usePathname();
  const [mode, setMode] = useState<"install" | "ios" | null>(null);
  const [iosSteps, setIosSteps] = useState(false);

  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Installation still works where the browser allows it without one.
      });
    }
  }, []);

  useEffect(() => {
    if (isStandalone() || snoozed()) return;
    let ready = false;
    const decide = () => {
      if (!ready) return;
      setMode(deferredInstall ? "install" : isIOS() ? "ios" : null);
    };
    const timer = setTimeout(() => {
      ready = true;
      decide();
    }, SHOW_AFTER_MS);
    listeners.add(decide);
    return () => {
      clearTimeout(timer);
      listeners.delete(decide);
    };
  }, []);

  if (!mode || pathname.startsWith("/arena")) return null;

  function snooze() {
    setMode(null);
    try {
      localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_DAYS * 864e5));
    } catch {
      // private mode: the card simply comes back next visit
    }
  }

  async function install() {
    if (mode === "ios") {
      setIosSteps(true);
      return;
    }
    const event = deferredInstall;
    if (!event) return;
    await event.prompt();
    await event.userChoice;
    deferredInstall = null;
    setMode(null);
  }

  // On the lobby the phone layout has a pinned "Enter the arena" bar; sit above it.
  const bottom =
    pathname === "/"
      ? "bottom-[calc(6rem+env(safe-area-inset-bottom))] lg:bottom-6"
      : "bottom-[calc(1rem+env(safe-area-inset-bottom))] lg:bottom-6";

  return (
    <div
      role="dialog"
      aria-labelledby="install-title"
      className={`float-pane animate-fade-up fixed inset-x-3 z-40 rounded-3xl border p-4 shadow-2xl sm:left-6 sm:right-auto sm:w-[22rem] ${bottom}`}
    >
      <div className="flex items-start gap-3">
        <Image src="/icon-192.png" alt="" width={44} height={44} className="rounded-xl" />
        <div className="min-w-0 flex-1">
          <p id="install-title" className="text-lg font-bold leading-tight tracking-tight">
            Install GD Arena
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Practice anytime from your home screen. Opens full screen, like an app.
          </p>
        </div>
        <button
          type="button"
          onClick={snooze}
          aria-label="Not now"
          className="-m-1 flex size-9 shrink-0 items-center justify-center rounded-full text-muted hover:text-foreground"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>

      {iosSteps ? (
        <ol className="mt-3 space-y-2 rounded-2xl bg-surface-raised p-3 text-sm">
          <li className="flex items-center gap-2">
            1. Tap <Share aria-label="Share" className="size-4 text-primary" /> Share in Safari
          </li>
          <li className="flex items-center gap-2">
            2. Choose <PlusSquare aria-hidden className="size-4 text-primary" /> Add to Home Screen
          </li>
          <li>3. Tap Add</li>
        </ol>
      ) : (
        <div className="mt-3 flex gap-2">
          <button type="button" onClick={install} className="btn-primary flex-1 py-2.5 text-sm">
            <Download aria-hidden className="size-4" />
            Install app
          </button>
          <button type="button" onClick={snooze} className="btn-quiet py-2.5 text-sm">
            Not now
          </button>
        </div>
      )}
    </div>
  );
}
