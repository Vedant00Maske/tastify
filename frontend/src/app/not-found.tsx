import Link from "next/link";

import { BrandLogo } from "@/components/layout/navigation";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 text-center">
      <BrandLogo />
      <div>
        <p className="font-display text-hero font-bold text-accent">404</p>
        <h1 className="mt-2 text-page font-bold">
          This page is off the record
        </h1>
        <p className="mt-2 text-fg-secondary">
          The link may be old, or the page has moved.
        </p>
      </div>
      <Button asChild>
        <Link href="/home">Back to TASTIFY</Link>
      </Button>
    </main>
  );
}
