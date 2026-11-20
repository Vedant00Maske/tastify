import type { ReactNode } from "react";

/** Long-form text with readable measure and spacing (privacy notice, terms). */
export function Prose({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: ReactNode;
}) {
  return (
    <article className="text-fg-secondary [&_a]:text-accent [&_a]:underline [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:text-section [&_h2]:font-bold [&_h2]:text-fg [&_li]:mt-1.5 [&_p]:mt-3 [&_strong]:text-fg [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-6">
      <h1 className="text-page font-bold text-fg">{title}</h1>
      <p className="text-meta text-fg-muted">Last updated {updated}</p>
      {children}
    </article>
  );
}
