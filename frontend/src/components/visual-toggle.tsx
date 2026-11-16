"use client";
import { Box } from "lucide-react";
import { Button } from "./ui/primitives";
import { useUse3D, useVisualStore, VisualMode } from "@/lib/visual";

const NEXT: Record<VisualMode, VisualMode> = { auto: "on", on: "off", off: "auto" };
const LABEL: Record<VisualMode, string> = { auto: "Auto", on: "3D", off: "2D" };

/** Auto / 3D / 2D. Auto picks 3D only on capable devices and drops to 2D if the frame rate is poor. */
export function VisualToggle() {
  const { mode, setMode } = useVisualStore();
  const { use3D, reason } = useUse3D();
  const status = use3D ? "showing 3D" : `showing 2D${reason ? ` (${reason})` : ""}`;
  return (
    <Button
      variant="ghost" size="sm" onClick={() => setMode(NEXT[mode])}
      aria-label={`Visuals: ${LABEL[mode]}, ${status}. Activate to change`} title={`Visuals: ${LABEL[mode]} · ${status}`}
    >
      <Box className="h-4 w-4" /> <span className="hidden sm:inline">{LABEL[mode]}</span>
    </Button>
  );
}
