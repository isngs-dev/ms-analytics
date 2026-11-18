"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Input } from "@/components/ui/primitives";
import { post } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await post("/auth/login", { email, password });
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="glass w-full max-w-sm space-y-4 p-6 animate-fade-up">
      <div className="flex items-center gap-3">
        <div className="bg-brand grid h-10 w-10 place-items-center rounded-xl font-bold shadow-glow">MS</div>
        <div><h1 className="text-lg font-semibold">MS Analytics</h1><p className="text-sm text-muted-foreground">Sign in to continue</p></div>
      </div>
      <label className="block space-y-1 text-sm">Email
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="block space-y-1 text-sm">Password
        <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <Button type="submit" variant="brand" className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
      {DEMO && (
        <div className="rounded-xl border bg-card/50 p-3 text-xs" aria-label="Demo logins">
          <p className="mb-2 font-medium uppercase tracking-wider text-muted-foreground">Demo logins · click to fill</p>
          <ul className="space-y-1">
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.email}>
                <button type="button" onClick={() => { setEmail(a.email); setPassword(DEMO_PASSWORD); }}
                  className="flex w-full flex-col rounded-lg px-2 py-1.5 text-left hover:bg-muted">
                  <span><b>{a.role}</b> · {a.email}</span>
                  <span className="text-muted-foreground">Password: <span className="tabular">{DEMO_PASSWORD}</span></span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-muted-foreground">Local demo only. Replace these accounts before sharing the site.</p>
        </div>
      )}
    </form>
  );
}

// Shown only when NEXT_PUBLIC_DEMO_LOGINS=1: in frontend/.env.local locally, or as a build-time env var on a test deployment.
const DEMO = process.env.NEXT_PUBLIC_DEMO_LOGINS === "1";
const DEMO_PASSWORD = process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "";
const DEMO_ACCOUNTS = [
  { role: "Admin", email: "admin@example.com" },
  { role: "Manager", email: "manager@example.com" },
  { role: "Viewer", email: "viewer@example.com" },
];

export default function LoginPage() {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <Suspense><LoginForm /></Suspense>
    </main>
  );
}
