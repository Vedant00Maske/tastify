"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { X } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

// --- dialog ----------------------------------------------------------------------------------

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[2px] data-[state=open]:animate-[fade-in_200ms_ease-out]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-modal border border-border bg-surface-elevated p-6 shadow-modal data-[state=open]:animate-[dialog-in_200ms_var(--ease-out-soft)]",
          className,
        )}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <DialogPrimitive.Title className="text-section font-bold">
              {title}
            </DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-1 text-support text-fg-secondary">
                {description}
              </DialogPrimitive.Description>
            ) : null}
          </div>
          <DialogPrimitive.Close
            aria-label="Close"
            className="rounded-full p-1.5 text-fg-secondary transition-colors hover:bg-surface-hover hover:text-fg"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

// --- dropdown menu ---------------------------------------------------------------------------

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;
export const DropdownMenuSub = DropdownPrimitive.Sub;

export function DropdownMenuContent({
  className,
  align = "end",
  ...props
}: ComponentProps<typeof DropdownPrimitive.Content>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={6}
        className={cn(
          "z-50 min-w-48 rounded-card border border-border bg-surface-elevated p-1.5 shadow-elevated",
          className,
        )}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

const itemClass =
  "flex cursor-pointer items-center gap-2.5 rounded-button-sm px-2.5 py-2 text-sm text-fg-secondary outline-none select-none data-[highlighted]:bg-surface-hover data-[highlighted]:text-fg data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4";

export function DropdownMenuItem({
  className,
  ...props
}: ComponentProps<typeof DropdownPrimitive.Item>) {
  return (
    <DropdownPrimitive.Item className={cn(itemClass, className)} {...props} />
  );
}

export function DropdownMenuSubTrigger({
  className,
  ...props
}: ComponentProps<typeof DropdownPrimitive.SubTrigger>) {
  return (
    <DropdownPrimitive.SubTrigger
      className={cn(itemClass, className)}
      {...props}
    />
  );
}

export function DropdownMenuSubContent({
  className,
  ...props
}: ComponentProps<typeof DropdownPrimitive.SubContent>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.SubContent
        className={cn(
          "z-50 max-h-72 min-w-48 overflow-y-auto rounded-card border border-border bg-surface-elevated p-1.5 shadow-elevated",
          className,
        )}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuSeparator() {
  return <DropdownPrimitive.Separator className="my-1 h-px bg-border" />;
}

export function DropdownMenuLabel({ children }: { children: ReactNode }) {
  return (
    <DropdownPrimitive.Label className="px-2.5 py-1.5 text-meta font-medium text-fg-muted">
      {children}
    </DropdownPrimitive.Label>
  );
}

// --- slider, switch, tabs --------------------------------------------------------------------

/**
 * A single-thumb slider. The accessible name and value text belong on the thumb (the element with
 * role="slider"), so they are props here rather than ARIA attributes on the root.
 */
export function Slider({
  className,
  label,
  valueText,
  ...props
}: ComponentProps<typeof SliderPrimitive.Root> & {
  label: string;
  valueText?: string;
}) {
  return (
    <SliderPrimitive.Root
      className={cn(
        "relative flex h-6 w-full touch-none items-center select-none",
        className,
      )}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-surface-hover">
        <SliderPrimitive.Range className="absolute h-full bg-accent" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb
        aria-label={label}
        aria-valuetext={valueText}
        className="block size-5 rounded-full border-2 border-accent bg-background shadow-glow transition-transform duration-150 hover:scale-110 focus-visible:outline-2 focus-visible:outline-accent"
      />
    </SliderPrimitive.Root>
  );
}

export function Switch({
  className,
  ...props
}: ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border border-border bg-surface-hover transition-colors data-[state=checked]:border-accent data-[state=checked]:bg-accent-muted",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-4.5 translate-x-0.5 rounded-full bg-fg-secondary transition-transform duration-150 data-[state=checked]:translate-x-5.5 data-[state=checked]:bg-accent" />
    </SwitchPrimitive.Root>
  );
}

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        "inline-flex gap-1 rounded-full border border-border bg-background-secondary p-1",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "rounded-full px-4 py-1.5 text-sm font-semibold text-fg-secondary transition-colors duration-150 hover:text-fg data-[state=active]:bg-surface-hover data-[state=active]:text-fg",
        className,
      )}
      {...props}
    />
  );
}
