import { Suspense, type ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { Spinner } from "@/components/ui/states";

/** Every signed-in page: sidebar, header, persistent player. */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell>
      <Suspense
        fallback={
          <div className="grid h-64 place-items-center text-fg-secondary">
            <Spinner className="size-6" />
          </div>
        }
      >
        {children}
      </Suspense>
    </AppShell>
  );
}
