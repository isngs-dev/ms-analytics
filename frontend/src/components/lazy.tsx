"use client";
import { useEffect, useRef, useState } from "react";

/**
 * Renders its children (and so starts their data requests) only when the spot is about to scroll into view.
 * A page with a dozen heavy cards then asks the server for the top of the page first instead of everything at once.
 */
export function Lazy({ children, height = 260 }: { children: React.ReactNode; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (shown) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { setShown(true); return; }
    const io = new IntersectionObserver((e) => { if (e.some((x) => x.isIntersecting)) { setShown(true); io.disconnect(); } }, { rootMargin: "600px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [shown]);
  return shown ? <>{children}</> : <div ref={ref} style={{ minHeight: height }} aria-hidden />;
}
