import * as LabelPrimitive from "@radix-ui/react-label";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Label({
  className,
  ...props
}: ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      className={cn("text-support font-medium text-fg-secondary", className)}
      {...props}
    />
  );
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-button border border-border bg-background-secondary px-3.5 text-body text-fg transition-colors duration-150 placeholder:text-fg-muted hover:border-fg-muted focus:border-accent focus:outline-none aria-invalid:border-error",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "min-h-24 w-full resize-y rounded-button border border-border bg-background-secondary px-3.5 py-2.5 text-body text-fg placeholder:text-fg-muted focus:border-accent focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}

/** A labelled control with an optional hint and a field error, wired for screen readers. */
export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-support text-error">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-support text-fg-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
