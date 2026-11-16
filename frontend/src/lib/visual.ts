"use client";
import { useEffect, useState } from "react";
import { create } from "zustand";

/**
 * 3D is an accent, never required. Auto mode shows 3D only when the device can carry it:
 * WebGL works, no prefers-reduced-motion, no save-data, and not an obviously low-end machine
 * (<= 2 cores or <= 2 GB). A running frame-rate monitor can also demote the session to 2D.
 */
export type VisualMode = "auto" | "on" | "off";

const KEY = "visual-mode";
const DEGRADED_KEY = "visual-degraded";

interface VisualState {
  mode: VisualMode;
  degraded: boolean; // frame rate was poor this session -> stay 2D in auto mode
  setMode: (m: VisualMode) => void;
  degrade: () => void;
  hydrate: () => void;
}

export const useVisualStore = create<VisualState>((set) => ({
  mode: "auto",
  degraded: false,
  setMode: (mode) => {
    try { localStorage.setItem(KEY, mode); sessionStorage.removeItem(DEGRADED_KEY); } catch {}
    set({ mode, degraded: false });
  },
  degrade: () => {
    try { sessionStorage.setItem(DEGRADED_KEY, "1"); } catch {}
    set({ degraded: true });
  },
  hydrate: () => {
    try {
      const m = localStorage.getItem(KEY);
      set({
        mode: m === "on" || m === "off" || m === "auto" ? m : "auto",
        degraded: sessionStorage.getItem(DEGRADED_KEY) === "1",
      });
    } catch {}
  },
}));

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export interface Capability { ok: boolean; reason?: string }

export function detectCapability(): Capability {
  if (!webglAvailable()) return { ok: false, reason: "WebGL is not available" };
  const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } };
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return { ok: false, reason: "reduced motion is on" };
  if (nav.connection?.saveData) return { ok: false, reason: "data saver is on" };
  if (nav.hardwareConcurrency && nav.hardwareConcurrency <= 2) return { ok: false, reason: "low CPU core count" };
  if (nav.deviceMemory && nav.deviceMemory <= 2) return { ok: false, reason: "low device memory" };
  return { ok: true };
}

/** Width gate: wide hero scenes only make sense from tablet size up. */
export function useWide(min = 768): boolean {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${min}px)`);
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [min]);
  return wide;
}

/** true => render the 3D variant. Always false on the server and on first paint. */
export function useUse3D(): { use3D: boolean; reason?: string } {
  const { mode, degraded, hydrate } = useVisualStore();
  const [cap, setCap] = useState<Capability | null>(null);

  useEffect(() => {
    hydrate();
    setCap(detectCapability());
    // react to the user toggling reduced motion while the page is open
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setCap(detectCapability());
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [hydrate]);

  if (cap === null) return { use3D: false };
  if (mode === "off") return { use3D: false, reason: "turned off" };
  if (mode === "on") return cap.reason === "WebGL is not available" ? { use3D: false, reason: cap.reason } : { use3D: true };
  if (!cap.ok) return { use3D: false, reason: cap.reason };
  if (degraded) return { use3D: false, reason: "low frame rate" };
  return { use3D: true };
}
