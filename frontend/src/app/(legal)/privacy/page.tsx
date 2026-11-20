import type { Metadata } from "next";
import Link from "next/link";

import { Prose } from "@/features/legal/prose";

export const metadata: Metadata = { title: "Privacy notice" };

/**
 * What SONIQUEO stores and why, written from what the code actually does (docs/SECURITY.md).
 * The operator of a deployment must add their identity and contact details and have this text
 * reviewed for their jurisdiction before opening it to the public (docs/RUNBOOK.md).
 */
export default function PrivacyPage() {
  return (
    <Prose title="Privacy notice" updated="19 November 2026">
      <p>
        SONIQUEO recommends music from your own listening. To do that it keeps a
        record of what you play, like and skip. This notice explains exactly
        what is stored, why, for how long, and how you stay in control.
      </p>

      <h2>What we store</h2>
      <ul>
        <li>
          <strong>Your account:</strong> e-mail address, optional display name,
          a one-way hash of your password (never the password itself), when you
          accepted these terms, and whether you confirmed your e-mail address.
        </li>
        <li>
          <strong>Your listening and feedback:</strong> which track, what
          happened (played, completed, skipped, liked, disliked, saved, added to
          a playlist), when, and where in the app. No location or device data.
        </li>
        <li>
          <strong>What you told us you like:</strong> genres, artists, moods and
          how adventurous your recommendations should be.
        </li>
        <li>
          <strong>Your taste profile:</strong> a summary computed from the
          above, recomputed whenever it changes.
        </li>
        <li>
          <strong>What we recommended to you:</strong> the lists we showed and
          the request that produced them (including what you typed into
          &ldquo;Create&rdquo;), to measure and improve recommendations. Kept
          for 90 days.
        </li>
        <li>
          <strong>Your playlists</strong> and, if you connect a music service,
          its access tokens (encrypted; never shown to anyone, including you)
          and the history you chose to import.
        </li>
        <li>
          <strong>Sign-in sessions:</strong> a random identifier in a cookie
          (only its hash is stored) and your browser&apos;s user agent. Sessions
          end after 30 days without use.
        </li>
      </ul>

      <h2>Why</h2>
      <p>
        Only to run SONIQUEO for you: sign you in, make and explain your
        recommendations, keep your playlists, and keep the service secure and
        working. We do not sell your data, show advertising or build profiles
        for anyone else.
      </p>

      <h2>Who else is involved</h2>
      <ul>
        <li>
          <strong>Album artwork</strong> comes from the Cover Art Archive. Our
          server fetches it, so your browser does not contact the archive.
        </li>
        <li>
          <strong>Music services you connect</strong> (ListenBrainz, Spotify,
          YouTube) receive what you ask us to send them, such as an exported
          playlist, under their own privacy policies.
        </li>
        <li>
          <strong>E-mail</strong> for password resets and address confirmation
          is sent through the operator&apos;s e-mail provider.
        </li>
        <li>
          <strong>Error reports</strong> may be sent to an error-tracking
          service; they never include your password, cookies, or the content of
          your requests.
        </li>
      </ul>

      <h2>How long</h2>
      <p>
        Your account data is kept until you delete your account. Recommendation
        records are deleted after 90 days, expired sessions and used e-mail
        links within a few days. Database backups are kept for up to 14 days, so
        deleted data disappears from them within that time.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>
          <strong>Download everything</strong> we store about you as a file, at
          any time: <Link href="/settings">Settings</Link> &rarr; Privacy.
        </li>
        <li>
          <strong>Turn personalization off:</strong> recommendations then ignore
          your history and profile.
        </li>
        <li>
          <strong>Disconnect a music service</strong> and optionally delete the
          history imported from it.
        </li>
        <li>
          <strong>Delete your account</strong>, which deletes everything listed
          above immediately (and from backups within 14 days).
        </li>
      </ul>

      <h2>Cookies and storage</h2>
      <p>
        One strictly necessary cookie keeps you signed in. Your recent searches
        are kept in your browser only. There are no tracking or advertising
        cookies.
      </p>

      <h2>Contact</h2>
      <p>
        Questions or requests about your data go to the operator of this
        SONIQUEO service.
      </p>
    </Prose>
  );
}
