"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { PerformanceMonitor } from "@react-three/drei";
import { useVisualStore } from "@/lib/visual";

const MAX_DPR = 1.5; // retina screens do not need 2-3x pixel work for an accent

/**
 * Canvas wrapper shared by every scene:
 *  - DPR capped at 1.5 and lowered further if the frame rate dips
 *  - renders only while on screen and the tab is visible (frameloop "never" otherwise)
 *  - sustained low FPS demotes the session to 2D (PerformanceMonitor -> store.degrade)
 *  - `overlay` is a plain DOM layer above the canvas (labels, tooltips, buttons)
 */
export function Stage({
  children, height, camera, ariaLabel, className, overlay,
}: {
  children: React.ReactNode; height: number; ariaLabel: string; className?: string; overlay?: React.ReactNode;
  camera?: { position: [number, number, number]; fov?: number };
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);
  const [tabVisible, setTabVisible] = useState(true);
  const [dpr, setDpr] = useState(Math.min(typeof window === "undefined" ? 1 : window.devicePixelRatio, MAX_DPR));
  const degrade = useVisualStore((s) => s.degrade);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { rootMargin: "80px" });
    io.observe(el);
    const vis = () => setTabVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", vis);
    return () => { io.disconnect(); document.removeEventListener("visibilitychange", vis); };
  }, []);

  return (
    <div ref={wrap} className={className} style={{ height, position: "relative", touchAction: "pan-y" }}>
      <div role="img" aria-label={ariaLabel} style={{ height: "100%" }}>
        <Canvas
          dpr={dpr}
          frameloop={visible && tabVisible ? "always" : "never"}
          camera={{ position: camera?.position ?? [0, 0, 8], fov: camera?.fov ?? 40 }}
          gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
          onCreated={({ gl }) => {
            gl.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); degrade(); });
          }}
        >
          <PerformanceMonitor
            bounds={() => [24, 58]}
            flipflops={3}
            onDecline={() => setDpr((d) => Math.max(1, d - 0.25))}
            onFallback={() => degrade()}
          />
          <ambientLight intensity={0.85} />
          <directionalLight position={[4, 6, 5]} intensity={1.4} />
          <pointLight position={[-5, -2, 4]} intensity={16} color="#9be3b8" />
          <pointLight position={[5, 3, 3]} intensity={12} color="#ff9aa0" />
          <Suspense fallback={null}>{children}</Suspense>
        </Canvas>
      </div>
      {overlay && <div className="pointer-events-none absolute inset-0 overflow-hidden">{overlay}</div>}
    </div>
  );
}
