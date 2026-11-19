"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, ShieldCheck, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { PageContainer, PageHeading } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Dialog, DialogContent, Switch } from "@/components/ui/primitives";
import { ErrorState, Pill, Skeleton, Spinner } from "@/components/ui/states";
import { useMe, useUpdateAccount } from "@/features/auth/queries";
import {
  ArtistPicker,
  FEATURED_GENRES,
} from "@/features/onboarding/onboarding-flow";
import { ConnectionsPanel } from "@/features/integrations/connections-panel";
import { useGenres, useMoods } from "@/features/recommendations/queries";
import {
  toUpdate,
  usePreferences,
  useUpdatePreferences,
} from "@/features/taste-profile/queries";
import { hardNavigate } from "@/lib/navigation";
import { API_BASE_URL, ApiError } from "@/services/api-client";
import { account, auth } from "@/services/api";
import type { Preferences, PreferencesUpdate } from "@/types/api";

import { ExplorationPicker } from "./exploration-picker";

function Card({
  id,
  title,
  description,
  children,
}: {
  id?: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  const headingId = `${id ?? title.toLowerCase().replace(/\W+/g, "-")}-title`;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className="scroll-mt-20 rounded-card-lg border border-border bg-surface p-5 sm:p-6"
    >
      <h2 id={headingId} className="text-section font-bold">
        {title}
      </h2>
      {description ? (
        <p className="mt-1 text-support text-fg-secondary">{description}</p>
      ) : null}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function errorText(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Could not reach TASTIFY. Try again.";
}

// --- account ---------------------------------------------------------------------------------

const nameSchema = z.object({
  display_name: z.string().trim().max(80, "Use at most 80 characters"),
});

function AccountCard() {
  const me = useMe();
  const update = useUpdateAccount();
  const form = useForm<z.infer<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    values: { display_name: me.data?.display_name ?? "" },
  });
  const { errors, isDirty } = form.formState;
  return (
    <Card title="Account">
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit(({ display_name }) =>
          update.mutate(
            { display_name: display_name || null },
            {
              onSuccess: () => toast.success("Name saved"),
              onError: (e) => toast.error(errorText(e)),
            },
          ),
        )}
      >
        <Field
          id="account-email"
          label="E-mail"
          hint="Your sign-in address. It cannot be changed yet."
        >
          <Input
            id="account-email"
            value={me.data?.email ?? ""}
            readOnly
            disabled
          />
        </Field>
        <Field
          id="account-name"
          label="Name"
          error={errors.display_name?.message}
        >
          <Input
            id="account-name"
            autoComplete="nickname"
            {...form.register("display_name")}
          />
        </Field>
        <div>
          <Button type="submit" disabled={!isDirty || update.isPending}>
            {update.isPending ? <Spinner /> : null} Save
          </Button>
        </div>
      </form>
    </Card>
  );
}

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password"),
    new_password: z
      .string()
      .min(10, "Use at least 10 characters")
      .max(128, "Use at most 128 characters")
      .refine((v) => v.trim() === v, "No spaces at the start or end"),
    confirm: z.string(),
  })
  .refine((d) => d.new_password === d.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

function PasswordCard() {
  const change = useMutation({ mutationFn: auth.changePassword });
  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });
  const { errors } = form.formState;
  return (
    <Card
      title="Password"
      description="Changing it signs you out everywhere else."
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit(({ current_password, new_password }) =>
          change.mutate(
            { current_password, new_password },
            {
              onSuccess: () => {
                form.reset();
                toast.success("Password changed");
              },
            },
          ),
        )}
      >
        <Field
          id="current-password"
          label="Current password"
          error={errors.current_password?.message}
        >
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            {...form.register("current_password")}
          />
        </Field>
        <Field
          id="new-password"
          label="New password"
          error={errors.new_password?.message}
          hint="At least 10 characters."
        >
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            {...form.register("new_password")}
          />
        </Field>
        <Field
          id="confirm-password"
          label="Confirm new password"
          error={errors.confirm?.message}
        >
          <Input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            {...form.register("confirm")}
          />
        </Field>
        {change.error ? (
          <p role="alert" className="text-support text-error">
            {errorText(change.error)}
          </p>
        ) : null}
        <div>
          <Button type="submit" disabled={change.isPending}>
            {change.isPending ? <Spinner /> : null} Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}

// --- music preferences -----------------------------------------------------------------------

function toggle(list: string[], item: string): string[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

function ArtistList({
  label,
  artists,
  onRemove,
}: {
  label: string;
  artists: { artist_id: string; name: string }[];
  onRemove: (id: string) => void;
}) {
  if (!artists.length)
    return <p className="text-support text-fg-muted">None.</p>;
  return (
    <ul aria-label={label} className="flex flex-wrap gap-2">
      {artists.map((artist) => (
        <li key={artist.artist_id}>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background-secondary py-1 pr-1.5 pl-3 text-support">
            {artist.name}
            <button
              type="button"
              aria-label={`Remove ${artist.name}`}
              onClick={() => onRemove(artist.artist_id)}
              className="rounded-full p-0.5 text-fg-muted hover:bg-surface-hover hover:text-fg"
            >
              <X className="size-3.5" />
            </button>
          </span>
        </li>
      ))}
    </ul>
  );
}

function PreferencesCard({ preferences }: { preferences: Preferences }) {
  const save = useUpdatePreferences();
  const moods = useMoods();
  const genres = useGenres();
  const [adding, setAdding] = useState<"preferred" | "excluded" | null>(null);
  const current = toUpdate(preferences);
  const apply = (
    patch: Partial<PreferencesUpdate>,
    message = "Preferences saved",
  ) =>
    save.mutate(
      { ...current, ...patch },
      {
        onSuccess: () => toast.success(message),
        onError: (e) => toast.error(errorText(e)),
      },
    );

  const genreOptions = [
    ...new Set([
      ...FEATURED_GENRES.map((g) => g.genre),
      ...(genres.data?.genres ?? []).map((g) => g.name).slice(0, 30),
      ...current.preferred_genres,
    ]),
  ];

  return (
    <Card
      id="preferences"
      title="Music preferences"
      description="These shape every recommendation, starting with the next one."
    >
      <div className="flex flex-col gap-8">
        <div>
          <h3 className="mb-3 font-display text-card font-semibold">
            Familiar versus new
          </h3>
          <ExplorationPicker
            value={current.exploration_mode}
            onChange={(exploration_mode) => apply({ exploration_mode })}
          />
        </div>

        <div>
          <h3 className="mb-3 font-display text-card font-semibold">
            Favourite moods
          </h3>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="Favourite moods"
          >
            {(moods.data?.moods ?? []).map((mood) => {
              const active = current.preferred_moods.includes(mood.key);
              return (
                <button
                  key={mood.key}
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    apply({
                      preferred_moods: toggle(
                        current.preferred_moods,
                        mood.key,
                      ),
                    })
                  }
                >
                  <Pill active={active} className="px-3 py-1 text-support">
                    {mood.title}
                  </Pill>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <h3 className="mb-3 font-display text-card font-semibold">
            Favourite genres
          </h3>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="Favourite genres"
          >
            {genreOptions.map((genre) => {
              const active = current.preferred_genres.includes(genre);
              const excluded = current.excluded_genres.includes(genre);
              return (
                <button
                  key={genre}
                  type="button"
                  aria-pressed={active}
                  disabled={excluded}
                  onClick={() =>
                    apply({
                      preferred_genres: toggle(current.preferred_genres, genre),
                    })
                  }
                  className="disabled:opacity-40"
                >
                  <Pill
                    active={active}
                    className="px-3 py-1 text-support capitalize"
                  >
                    {genre}
                  </Pill>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <h3 className="mb-3 font-display text-card font-semibold">
            Genres to avoid
          </h3>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="Genres to avoid"
          >
            {genreOptions.map((genre) => {
              const active = current.excluded_genres.includes(genre);
              return (
                <button
                  key={genre}
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    apply({
                      excluded_genres: toggle(current.excluded_genres, genre),
                      preferred_genres: current.preferred_genres.filter(
                        (g) => g !== genre,
                      ),
                    })
                  }
                >
                  <Pill
                    active={active}
                    className={
                      active
                        ? "border-error/40 bg-error/10 px-3 py-1 text-support text-error capitalize"
                        : "px-3 py-1 text-support capitalize"
                    }
                  >
                    {genre}
                  </Pill>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-display text-card font-semibold">
              Favourite artists
            </h3>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setAdding("preferred")}
            >
              Add artists
            </Button>
          </div>
          <ArtistList
            label="Favourite artists"
            artists={preferences.preferred_artists}
            onRemove={(id) =>
              apply({
                preferred_artists: current.preferred_artists.filter(
                  (a) => a !== id,
                ),
              })
            }
          />
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-display text-card font-semibold">
              Excluded artists
            </h3>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setAdding("excluded")}
            >
              Exclude artists
            </Button>
          </div>
          <p className="mb-3 text-support text-fg-secondary">
            Never recommended, in any mix.
          </p>
          <ArtistList
            label="Excluded artists"
            artists={preferences.excluded_artists}
            onRemove={(id) =>
              apply({
                excluded_artists: current.excluded_artists.filter(
                  (a) => a !== id,
                ),
              })
            }
          />
        </div>
      </div>

      <Dialog
        open={adding !== null}
        onOpenChange={(open) => !open && setAdding(null)}
      >
        <DialogContent
          title={
            adding === "excluded" ? "Exclude artists" : "Add favourite artists"
          }
          description="Search and select; changes save immediately."
          className="max-w-2xl"
        >
          <div className="max-h-[60vh] overflow-y-auto">
            <ArtistPicker
              suggestions={[]}
              selected={(adding === "excluded"
                ? preferences.excluded_artists
                : preferences.preferred_artists
              ).map((a) => ({
                id: a.artist_id,
                name: a.name,
              }))}
              onToggle={(artist) => {
                const field =
                  adding === "excluded"
                    ? "excluded_artists"
                    : "preferred_artists";
                const other =
                  adding === "excluded"
                    ? "preferred_artists"
                    : "excluded_artists";
                apply({
                  [field]: toggle(current[field], artist.id),
                  [other]: current[other].filter((a) => a !== artist.id),
                });
              }}
            />
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// --- privacy, data and deletion --------------------------------------------------------------

function PrivacyCard({ preferences }: { preferences: Preferences }) {
  const save = useUpdatePreferences();
  return (
    <Card
      id="privacy"
      title="Privacy and your data"
      description="TASTIFY uses only your own activity to personalize, and never sells or shares it."
    >
      <div className="flex flex-col gap-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <label htmlFor="personalization" className="font-semibold">
              Personalized recommendations
            </label>
            <p className="text-support text-fg-secondary">
              When off, recommendations ignore your history and taste profile
              (they only avoid repeating tracks you have heard). Your likes and
              saves are still kept, so turning it back on picks up where you
              left off.
            </p>
          </div>
          <Switch
            id="personalization"
            checked={preferences.personalization_enabled}
            disabled={save.isPending}
            onCheckedChange={(personalization_enabled) =>
              save.mutate(
                { ...toUpdate(preferences), personalization_enabled },
                {
                  onSuccess: () =>
                    toast.success(
                      personalization_enabled
                        ? "Personalization on"
                        : "Personalization off",
                    ),
                  onError: (e) => toast.error(errorText(e)),
                },
              )
            }
          />
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">Export your data</p>
            <p className="text-support text-fg-secondary">
              Account, preferences, listening history, taste profile and
              playlists as one JSON file.
            </p>
          </div>
          <Button asChild variant="secondary">
            <a href={`${API_BASE_URL}${account.exportUrl}`} download>
              <Download /> Download
            </a>
          </Button>
        </div>
      </div>
    </Card>
  );
}

const deleteSchema = z.object({
  password: z.string().min(1, "Enter your password"),
});

function DeleteAccountCard() {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: account.remove,
    onSuccess: () => {
      client.clear();
      hardNavigate("/register", { replace: true });
    },
  });
  const form = useForm<z.infer<typeof deleteSchema>>({
    resolver: zodResolver(deleteSchema),
    defaultValues: { password: "" },
  });
  return (
    <Card
      title="Delete account"
      description="Deletes your account, history, taste profile and playlists immediately. This cannot be undone."
    >
      <Button variant="danger" onClick={() => setOpen(true)}>
        <Trash2 /> Delete my account
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          title="Delete your account?"
          description="Everything is deleted for good. Download your data first if you want a copy."
        >
          <form
            noValidate
            className="flex flex-col gap-4"
            onSubmit={form.handleSubmit(({ password }) =>
              remove.mutate(password),
            )}
          >
            <Field
              id="delete-password"
              label="Confirm with your password"
              error={form.formState.errors.password?.message}
            >
              <Input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                {...form.register("password")}
              />
            </Field>
            {remove.error ? (
              <p role="alert" className="text-support text-error">
                {errorText(remove.error)}
              </p>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="danger"
                disabled={remove.isPending}
              >
                {remove.isPending ? <Spinner /> : <Trash2 />} Delete forever
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

export function SettingsPage() {
  const preferences = usePreferences();
  return (
    <PageContainer className="max-w-3xl">
      <PageHeading title="Settings" />
      <AccountCard />
      {preferences.isPending ? (
        <Skeleton className="h-96" />
      ) : preferences.isError ? (
        <ErrorState onRetry={() => void preferences.refetch()} />
      ) : (
        <PreferencesCard preferences={preferences.data} />
      )}
      <Card
        id="connections"
        title="Connected services"
        description="Bring in your listening history and send playlists to other services."
      >
        <ConnectionsPanel />
      </Card>
      {preferences.data ? <PrivacyCard preferences={preferences.data} /> : null}
      <PasswordCard />
      <DeleteAccountCard />
      <p className="flex items-center gap-2 text-meta text-fg-muted">
        <ShieldCheck className="size-4" aria-hidden /> Your session is kept in a
        secure, HTTP-only cookie; TASTIFY never stores passwords in your
        browser.
      </p>
    </PageContainer>
  );
}
