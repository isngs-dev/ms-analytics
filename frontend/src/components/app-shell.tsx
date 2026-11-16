"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, Building2, CalendarRange, FileSpreadsheet, HeartPulse, LayoutDashboard, LogOut, Menu, Settings,
  Table2, Users, X,
} from "lucide-react";
import { DrillHost } from "./drill-host";
import { FilterBar } from "./filter-bar";
import { FilterSync } from "./filter-sync";
import { PageTransition } from "./page-transition";
import { SyncChip } from "./sync-chip";
import { ThemeToggle } from "./theme";
import { VisualToggle } from "./visual-toggle";
import { Button } from "./ui/primitives";
import { useMe } from "@/lib/hooks";
import { post } from "@/lib/api";
import { serializeFilters } from "@/lib/filters";
import { useFilterStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overall", icon: LayoutDashboard },
  { href: "/clients", label: "Clients & Projects", icon: Building2 },
  { href: "/editors", label: "Editors", icon: Users },
  { href: "/escalations", label: "Escalations", icon: AlertTriangle },
  { href: "/time", label: "Time & Comparisons", icon: CalendarRange },
  { href: "/explorer", label: "Data Explorer", icon: Table2 },
  { href: "/documents", label: "Drive Documents", icon: FileSpreadsheet },
  { href: "/health", label: "Data Health", icon: HeartPulse },
  { href: "/admin", label: "Admin", icon: Settings, admin: true },
];

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const filters = useFilterStore((s) => s.filters);
  const { data: me } = useMe();
  const qs = serializeFilters(filters); // carry the filters along when moving between pages
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV.filter((n) => !n.admin || me?.role === "admin").map((n) => {
        const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
        return (
          <Link
            key={n.href}
            href={qs ? `${n.href}?${qs}` : n.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition",
              active ? "bg-brand font-medium shadow-glow" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <n.icon className="h-4 w-4 shrink-0" aria-hidden /> {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [menu, setMenu] = useState(false);
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();

  const logout = async () => {
    await post("/auth/logout");
    qc.clear();
    router.push("/login");
  };

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <Suspense><FilterSync /></Suspense>
      <aside className="sticky top-0 hidden h-screen flex-col gap-6 border-r bg-card/40 p-4 backdrop-blur-xl lg:flex">
        <Brand />
        <Nav />
        <div className="mt-auto text-xs text-muted-foreground">
          <p className="truncate font-medium text-foreground">{me?.name}</p>
          <p className="capitalize">{me?.role}</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="flex items-center justify-between gap-2 border-b bg-background/60 px-3 py-2 backdrop-blur-xl sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMenu(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="lg:hidden"><Brand compact /></div>
          <div className="ml-auto flex items-center gap-1">
            <SyncChip />
            <VisualToggle />
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={logout} aria-label="Sign out"><LogOut className="h-4 w-4" /> <span className="hidden sm:inline">Sign out</span></Button>
          </div>
        </header>
        <FilterBar />
        <main className="mx-auto w-full max-w-[1500px] px-3 py-5 sm:px-6"><PageTransition>{children}</PageTransition></main>
        <DrillHost />
      </div>

      {menu && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMenu(false)} />
          <div className="glass absolute left-0 top-0 flex h-full w-72 flex-col gap-6 rounded-none p-4">
            <div className="flex items-center justify-between">
              <Brand />
              <Button variant="ghost" size="icon" onClick={() => setMenu(false)} aria-label="Close menu"><X className="h-5 w-5" /></Button>
            </div>
            <Nav onNavigate={() => setMenu(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="bg-brand grid h-8 w-8 place-items-center rounded-xl text-sm font-bold shadow-glow">MS</div>
      {!compact && <div className="leading-tight"><p className="text-sm font-semibold">MS Analytics</p><p className="text-[11px] text-muted-foreground">Operations dashboard</p></div>}
    </div>
  );
}
