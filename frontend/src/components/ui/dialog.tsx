"use client";
import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function Modal({
  open, onOpenChange, title, description, children, wide,
}: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string;
  children: React.ReactNode; wide?: boolean;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <D.Content
          className={cn(
            "glass fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-1.5rem)] -translate-x-1/2 -translate-y-1/2 overflow-auto p-5",
            wide ? "max-w-5xl" : "max-w-lg",
          )}
        >
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <D.Title className="text-lg font-semibold">{title}</D.Title>
              <D.Description className={cn("text-sm text-muted-foreground", !description && "sr-only")}>
                {description ?? title}
              </D.Description>
            </div>
            <D.Close className="rounded-lg p-1.5 hover:bg-muted" aria-label="Close">
              <X className="h-4 w-4" />
            </D.Close>
          </div>
          {children}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
