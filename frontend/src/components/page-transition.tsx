"use client";
import { usePathname } from "next/navigation";
import { motion, useReducedMotion } from "framer-motion";

/** Soft fade/slide between pages. Filter changes keep the same path, so they never retrigger it. */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const reduce = useReducedMotion();
  return (
    <motion.div
      key={path}
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
