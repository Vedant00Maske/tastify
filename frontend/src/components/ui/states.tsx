import { AlertTriangle, RotateCw } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton rounded-card", className)} />;
}

export function Pill({
  children,
  active = false,
  className,
}: {
  children: ReactNode;
  active?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-meta font-medium",
        active
          ? "border-accent/40 bg-accent-muted text-accent"
          : "border-border bg-surface text-fg-secondary",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-card-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {Icon ? (
        <div className="grid size-12 place-items-center rounded-full bg-surface text-fg-secondary">
          <Icon className="size-5" />
        </div>
      ) : null}
      <div className="max-w-sm">
        <p className="font-display text-card font-semibold">{title}</p>
        {description ? (
          <p className="mt-1 text-support text-fg-secondary">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  message = "Something went wrong while loading this.",
  onRetry,
  className,
}: {
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-3 rounded-card-lg border border-error/30 bg-error/5 px-6 py-8 text-center sm:flex-row sm:text-left",
        className,
      )}
    >
      <AlertTriangle className="size-5 shrink-0 text-error" aria-hidden />
      <p className="flex-1 text-support text-fg-secondary">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RotateCw /> Retry
        </Button>
      ) : null}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block size-4 animate-spin rounded-full border-2 border-current border-r-transparent",
        className,
      )}
    />
  );
}
