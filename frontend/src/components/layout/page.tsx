"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "motion/react";
import { useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Standard page frame: fade and a 6px rise on navigation (180 ms, §7). */
export function PageContainer({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "mx-auto flex w-full max-w-[1440px] flex-col gap-10 px-4 pt-6 pb-10 sm:px-6 lg:px-10",
        className,
      )}
    >
      {children}
    </motion.div>
  );
}

export function PageHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-2xl">
        <h1 className="text-page font-bold">{title}</h1>
        {description ? (
          <p className="mt-2 text-fg-secondary">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

export function SectionHeader({
  title,
  description,
  action,
  id,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  id?: string;
}) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div className="min-w-0">
        <h2 id={id} className="text-section font-bold">
          {title}
        </h2>
        {description ? (
          <p className="mt-0.5 text-support text-fg-secondary">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const id = `section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={id}>
      <SectionHeader
        id={id}
        title={title}
        description={description}
        action={action}
      />
      {children}
    </section>
  );
}

/** A horizontal row that scrolls with touch, trackpad or the arrow buttons. */
export function Carousel({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const scroll = (direction: number) =>
    ref.current?.scrollBy({
      left: direction * ref.current.clientWidth * 0.8,
      behavior: "smooth",
    });
  return (
    <div className="group/carousel relative">
      <div
        ref={ref}
        role="region"
        aria-label={label}
        tabIndex={0}
        className="-mx-4 scrollbar-none flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-2 sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10 [&>*]:w-[44vw] [&>*]:max-w-[220px] [&>*]:shrink-0 [&>*]:snap-start sm:[&>*]:w-[210px]"
      >
        {children}
      </div>
      <div className="pointer-events-none absolute -top-12 right-0 hidden gap-1 sm:flex">
        <Button
          variant="secondary"
          size="icon-sm"
          aria-label={`Scroll ${label} left`}
          className="pointer-events-auto"
          onClick={() => scroll(-1)}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="secondary"
          size="icon-sm"
          aria-label={`Scroll ${label} right`}
          className="pointer-events-auto"
          onClick={() => scroll(1)}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
