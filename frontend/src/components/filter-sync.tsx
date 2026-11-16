"use client";
import { useEffect, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FILTER_KEYS, parseFilters, serializeFilters } from "@/lib/filters";
import { useFilterStore } from "@/lib/store";

/**
 * Keeps the Zustand filter store and the URL in step, in both directions:
 *  - URL -> store on load / back / forward / shared link
 *  - store -> URL on every change (router.replace, other query params are preserved)
 * Both directions compare serialised strings first, so they can never ping-pong.
 */
export function FilterSync() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const filters = useFilterStore((s) => s.filters);
  const replace = useFilterStore((s) => s.replace);
  const hydrated = useRef(false);

  const urlSerialized = serializeFilters(parseFilters(new URLSearchParams(sp.toString())));

  useEffect(() => {
    if (urlSerialized !== serializeFilters(useFilterStore.getState().filters)) {
      replace(parseFilters(new URLSearchParams(sp.toString())));
    }
    hydrated.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSerialized]);

  useEffect(() => {
    if (!hydrated.current) return;
    // read fresh state: on the first run the effect above has just replaced the store
    const next = serializeFilters(useFilterStore.getState().filters);
    if (next === urlSerialized) return;
    const out = new URLSearchParams(sp.toString());
    FILTER_KEYS.forEach((k) => out.delete(k));
    new URLSearchParams(next).forEach((v, k) => out.set(k, v));
    const qs = out.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  return null;
}
