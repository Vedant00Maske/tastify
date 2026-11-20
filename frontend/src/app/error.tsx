"use client";

import { RotateCw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { reportError } from "@/lib/report-error";

/** Last-resort boundary: an unexpected rendering error anywhere below the root layout. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
    reportError(error, "render");
  }, [error]);
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-5 px-4 text-center">
      <h1 className="text-page font-bold">Something went wrong</h1>
      <p className="max-w-md text-fg-secondary">
        SONIQUEO hit an unexpected problem showing this page. Try again, or go
        back home.
        {error.digest ? (
          <span className="mt-2 block text-meta text-fg-muted">
            Reference: {error.digest}
          </span>
        ) : null}
      </p>
      <div className="flex gap-2">
        <Button onClick={reset}>
          <RotateCw /> Try again
        </Button>
        <Button asChild variant="secondary">
          <Link href="/home">Home</Link>
        </Button>
      </div>
    </main>
  );
}
