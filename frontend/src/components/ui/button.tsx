import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 font-semibold whitespace-nowrap transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-on-accent hover:bg-accent-hover",
        secondary:
          "bg-surface text-fg hover:bg-surface-hover border border-border",
        ghost: "text-fg-secondary hover:bg-surface hover:text-fg",
        outline:
          "border border-border text-fg hover:border-fg-muted hover:bg-surface",
        danger: "bg-error/90 text-on-accent hover:bg-error",
        link: "text-accent underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 rounded-button-sm px-3 text-[13px]",
        md: "h-10 rounded-button px-4 text-sm",
        lg: "h-12 rounded-button px-6 text-[15px]",
        icon: "size-10 rounded-full",
        "icon-sm": "size-8 rounded-full [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
