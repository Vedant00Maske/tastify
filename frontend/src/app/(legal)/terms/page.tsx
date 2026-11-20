import type { Metadata } from "next";
import Link from "next/link";

import { Prose } from "@/features/legal/prose";

export const metadata: Metadata = { title: "Terms of use" };

/** Plain terms for the beta. The operator must review them before a public launch (RUNBOOK.md). */
export default function TermsPage() {
  return (
    <Prose title="Terms of use" updated="19 November 2026">
      <p>
        SONIQUEO is a personal music discovery service, offered as a free,
        non-commercial beta. By creating an account you agree to these terms and
        to the <Link href="/privacy">privacy notice</Link>.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>
          Keep your password to yourself; you are responsible for your account.
        </li>
        <li>
          One account per person. You must be old enough to agree to these terms
          where you live.
        </li>
        <li>You can delete your account at any time in Settings.</li>
      </ul>

      <h2>Fair use</h2>
      <ul>
        <li>
          Do not try to access other people&apos;s data, break or overload the
          service, or get around its limits.
        </li>
        <li>
          Do not use SONIQUEO to collect data at scale or to build another
          service.
        </li>
      </ul>

      <h2>Music and data</h2>
      <p>
        SONIQUEO shows information about music; it does not host or stream
        audio. Catalogue data comes from open sources such as MusicBrainz and
        ListenBrainz under their licences, some of which allow non-commercial
        use only. Artwork belongs to its owners. Connected music services apply
        their own terms.
      </p>

      <h2>The beta</h2>
      <p>
        Recommendations are produced automatically and can be wrong. Features
        may change or stop, and the service may be unavailable at times. It is
        provided as it is, without guarantees, as far as the law allows.
      </p>

      <h2>Changes</h2>
      <p>
        If these terms change in a way that matters, we will tell you before the
        change applies. You can always delete your account instead.
      </p>
    </Prose>
  );
}
