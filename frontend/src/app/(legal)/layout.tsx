import Link from "next/link";
import type { ReactNode } from "react";

import { BrandLogo } from "@/components/layout/navigation";

/** Public reading layout for the privacy notice and terms. */
export default function LegalLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-4 py-6 sm:px-8">
        <BrandLogo href="/" />
        <nav aria-label="Legal" className="flex gap-4 text-support">
          <Link href="/privacy" className="text-fg-secondary hover:text-fg">
            Privacy
          </Link>
          <Link href="/terms" className="text-fg-secondary hover:text-fg">
            Terms
          </Link>
        </nav>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-20 sm:px-8">{children}</main>
    </div>
  );
}
