"use client";
import dynamic from "next/dynamic";
import { Skeleton } from "./ui/primitives";
import { Boundary } from "./three/boundary";
import { KpiCard } from "./widgets";
import { useUse3D } from "@/lib/visual";
import type { HeroItem } from "./three/hero-scene";

// three.js is only downloaded when the 3D variant is actually shown
const HeroScene = dynamic(() => import("./three/hero-scene"), { ssr: false, loading: () => <Skeleton className="h-[250px] w-full" /> });

export interface KpiDef extends Omit<HeroItem, "color"> { tone: "brand" | "good" | "warn" | "bad"; color: string }

function Grid({ items, loading }: { items: KpiDef[]; loading?: boolean }) {
  return (
    <section aria-label="Key figures" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {items.map((k) => (
        <KpiCard key={k.key} label={k.label} tone={k.tone} hint={k.hint} loading={loading} value={k.value} onClick={k.onClick} />
      ))}
    </section>
  );
}

/** 3D floating tiles on wide screens that can handle it; the regular KPI cards everywhere else. */
export function KpiHero({ items, loading, wide }: { items: KpiDef[]; loading?: boolean; wide: boolean }) {
  const { use3D } = useUse3D();
  if (!use3D || !wide) return <Grid items={items} loading={loading} />;
  return (
    <Boundary fallback={<Grid items={items} loading={loading} />}>
      <section aria-label="Key figures" className="glass overflow-hidden p-0">
        <HeroScene items={items.slice(0, 5)} />
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t px-5 py-2 text-xs text-muted-foreground">
          {items.slice(5).map((k) => (
            <button key={k.key} onClick={k.onClick} className="hover:text-foreground">
              {k.label}: <strong className="tabular-nums text-foreground">{k.value ?? "–"}</strong>
            </button>
          ))}
          <span className="ml-auto">Move the mouse over the tiles · click a tile for its records</span>
        </div>
      </section>
    </Boundary>
  );
}
