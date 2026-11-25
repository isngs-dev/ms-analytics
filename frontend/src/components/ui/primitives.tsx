"use client";
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------- Button */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-xl text-sm font-medium transition disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        brand: "bg-brand font-semibold shadow-glow hover:brightness-105",
        outline: "border bg-card/60 hover:bg-muted",
        ghost: "hover:bg-muted",
        danger: "bg-bad/15 text-bad hover:bg-bad/25",
      },
      size: { sm: "h-8 px-3", md: "h-10 px-4", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, ...p }, ref) => (
  <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...p} />
));
Button.displayName = "Button";

/* ---------------------------------------------------------------- Card */
export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("glass p-4 sm:p-5", className)} {...p} />
);
export const CardTitle = ({ className, ...p }: React.HTMLAttributes<HTMLHeadingElement>) => (
  <h2 className={cn("text-sm font-semibold tracking-wide text-muted-foreground", className)} {...p} />
);

/* ---------------------------------------------------------------- Badge */
const badgeVariants = cva("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium tabular", {
  variants: {
    tone: {
      neutral: "bg-muted text-foreground",
      good: "bg-good/15 text-good",
      warn: "bg-warn/15 text-warn",
      bad: "bg-bad/15 text-bad",
      brand: "bg-primary/15 text-primary",
    },
  },
  defaultVariants: { tone: "neutral" },
});
export const Badge = ({ className, tone, ...p }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) => (
  <span className={cn(badgeVariants({ tone }), className)} {...p} />
);

/* ---------------------------------------------------------------- Inputs */
const field = "h-10 w-full rounded-xl border bg-card/60 px-3 text-sm placeholder:text-muted-foreground";
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...p }, ref) => <input ref={ref} className={cn(field, className)} {...p} />,
);
Input.displayName = "Input";

export interface Opt { value: string | number; label: string }
export function Select({
  label, value, onChange, options, placeholder = "All", className, disabled,
}: {
  label: string; value: string | number | undefined; onChange: (v: string) => void; options: Opt[];
  placeholder?: string; className?: string; disabled?: boolean;
}) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
      <select
        className={cn(field, "h-9 appearance-none pr-7")}
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

/* ---------------------------------------------------------------- Skeleton / Tabs */
export const Skeleton = ({ className }: { className?: string }) => (
  <div aria-hidden className={cn("animate-pulse rounded-xl bg-muted/70", className)} />
);

export function Tabs<T extends string>({
  value, onChange, items, label,
}: { value: T; onChange: (v: T) => void; items: { value: T; label: string; disabled?: boolean; hint?: string }[]; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-xl border bg-card/60 p-1">
      {items.map((i) => (
        <button
          key={i.value}
          role="tab"
          aria-selected={value === i.value}
          disabled={i.disabled}
          title={i.disabled ? i.hint : undefined}
          onClick={() => onChange(i.value)}
          className={cn(
            "whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition",
            i.disabled ? "cursor-not-allowed text-muted-foreground/40" : value === i.value ? "bg-brand font-medium shadow-glow" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {i.label}
        </button>
      ))}
    </div>
  );
}
