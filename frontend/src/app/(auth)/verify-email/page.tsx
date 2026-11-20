import type { Metadata } from "next";
import { Suspense } from "react";

import { VerifyEmail } from "@/features/auth/recovery-forms";

export const metadata: Metadata = { title: "Confirm e-mail address" };

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmail />
    </Suspense>
  );
}
