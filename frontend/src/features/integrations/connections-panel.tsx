"use client";

import {
  ExternalLink,
  History,
  Link2,
  Plug,
  RefreshCw,
  Unplug,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import {
  EmptyState,
  ErrorState,
  Pill,
  Skeleton,
  Spinner,
} from "@/components/ui/states";
import { ApiError } from "@/services/api-client";
import type { ImportRun, Provider } from "@/types/api";

import {
  useAuthorize,
  useConnectToken,
  useDisconnect,
  useImportHistory,
  useIntegrations,
} from "./queries";

const REASONS: Record<string, string> = {
  invalid_state: "The sign-in took too long or was already used. Try again.",
  invalid_credentials: "The provider did not accept the sign-in.",
  not_configured: "This service is not configured on this server.",
  access_denied: "You cancelled the sign-in.",
};

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not reach SONIQUEO. Try again.";
}

function describeImport(run: ImportRun): string {
  if (run.status === "failed")
    return `Last import failed: ${run.error ?? "unknown error"}`;
  if (run.status === "running") return "Import in progress…";
  const when = new Date(run.finished_at ?? run.started_at).toLocaleString();
  return `Last import ${when}: ${run.imported} new, ${run.fetched - run.matched} not in the catalogue.`;
}

/** Shows the result of an OAuth round trip once (?integration=…&status=…), then cleans the URL. */
function useOAuthResult() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const shown = useRef(false);
  useEffect(() => {
    const provider = params.get("integration");
    const status = params.get("status");
    if (!provider || !status || shown.current) return;
    shown.current = true;
    const name = provider.charAt(0).toUpperCase() + provider.slice(1);
    if (status === "connected") toast.success(`${name} connected`);
    else if (status === "cancelled") toast(`${name} was not connected`);
    else
      toast.error(
        REASONS[params.get("reason") ?? ""] ?? `Could not connect ${name}.`,
      );
    router.replace(`${pathname}#connections`, { scroll: false });
  }, [params, router, pathname]);
}

function TokenForm({ provider }: { provider: Provider }) {
  const [token, setToken] = useState("");
  const connect = useConnectToken(provider.provider);
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        connect.mutate(token, {
          onSuccess: () => {
            setToken("");
            toast.success(`${provider.name} connected`);
          },
        });
      }}
    >
      <Field
        id={`${provider.provider}-token`}
        label={`${provider.name} user token`}
        hint="Find it on your ListenBrainz settings page. SONIQUEO stores it encrypted."
        error={connect.error ? errorText(connect.error) : undefined}
      >
        <Input
          id={`${provider.provider}-token`}
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={token.trim().length < 8 || connect.isPending}
        >
          {connect.isPending ? <Spinner /> : <Link2 />} Connect
        </Button>
        <a
          href="https://listenbrainz.org/settings/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-support text-fg-secondary hover:text-fg"
        >
          Get your token <ExternalLink className="size-3.5" aria-hidden />
          <span className="sr-only">(opens ListenBrainz in a new tab)</span>
        </a>
      </div>
    </form>
  );
}

function ImportControl({ provider }: { provider: Provider }) {
  const [open, setOpen] = useState(false);
  const run = useImportHistory(provider.provider);
  const what =
    provider.provider === "spotify"
      ? "saved and recently played tracks"
      : "listening history";
  return (
    <>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => setOpen(true)}
        disabled={run.isPending}
      >
        {run.isPending ? <Spinner /> : <History />} Import {what}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          title={`Import from ${provider.name}?`}
          description={`SONIQUEO copies your ${what} from ${provider.name} into your history and uses it to personalize your recommendations. Only tracks in the SONIQUEO catalogue are kept. You can delete the imported history again when you disconnect.`}
        >
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setOpen(false);
                run.mutate(undefined, {
                  onSuccess: (result) =>
                    toast.success(
                      result.imported
                        ? `Imported ${result.imported} new ${result.imported === 1 ? "item" : "items"} from ${provider.name}`
                        : `Nothing new to import from ${provider.name}`,
                    ),
                  onError: (error) => toast.error(errorText(error)),
                });
              }}
            >
              I agree, import
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function DisconnectControl({ provider }: { provider: Provider }) {
  const [open, setOpen] = useState(false);
  const [purge, setPurge] = useState(false);
  const disconnect = useDisconnect(provider.provider);
  const imports = provider.capabilities.includes("import_history");
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        <Unplug /> Disconnect
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          title={`Disconnect ${provider.name}?`}
          description="SONIQUEO deletes its access to your account. Playlists already exported stay where they are."
        >
          {imports ? (
            <label className="mb-4 flex items-start gap-3 text-support text-fg-secondary">
              <input
                type="checkbox"
                checked={purge}
                onChange={(event) => setPurge(event.target.checked)}
                className="mt-0.5 size-4 accent-[var(--color-accent)]"
              />
              Also delete the history imported from {provider.name}
            </label>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={disconnect.isPending}
              onClick={() =>
                disconnect.mutate(purge, {
                  onSuccess: () => {
                    setOpen(false);
                    toast.success(`${provider.name} disconnected`);
                  },
                  onError: (error) => toast.error(errorText(error)),
                })
              }
            >
              {disconnect.isPending ? <Spinner /> : <Unplug />} Disconnect
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ProviderCard({
  provider,
  keysReady,
}: {
  provider: Provider;
  keysReady: boolean;
}) {
  const authorize = useAuthorize();
  const connection = provider.connection;
  const needsAccount = provider.auth !== "none";
  const usable = provider.available && (!needsAccount || keysReady);
  return (
    <li className="flex flex-col gap-4 rounded-card border border-border bg-background-secondary p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-display text-card font-semibold">
            {provider.name}
            {connection?.status === "active" ? (
              <Pill active>Connected</Pill>
            ) : null}
            {connection?.status === "reauth_required" ? (
              <Pill className="border-warning/40 text-warning">
                Reconnect needed
              </Pill>
            ) : null}
          </p>
          <p className="mt-1 max-w-xl text-support text-fg-secondary">
            {provider.description}
          </p>
          {connection ? (
            <p className="mt-1 text-meta text-fg-muted">
              Signed in as {connection.external_name ?? "your account"}
              {connection.last_import
                ? ` · ${describeImport(connection.last_import)}`
                : ""}
            </p>
          ) : null}
        </div>
      </div>

      {!usable ? (
        <p className="text-support text-fg-muted">
          Not available on this server yet: an administrator has to configure{" "}
          {provider.available
            ? "token encryption"
            : `${provider.name} credentials`}{" "}
          first.
        </p>
      ) : !needsAccount ? (
        <p className="text-support text-fg-muted">
          Always on. No account needed.
        </p>
      ) : connection && connection.status === "active" ? (
        <div className="flex flex-wrap gap-2">
          {provider.capabilities.includes("import_history") ? (
            <ImportControl provider={provider} />
          ) : null}
          <DisconnectControl provider={provider} />
        </div>
      ) : provider.auth === "token" ? (
        <>
          <TokenForm provider={provider} />
          {connection ? <DisconnectControl provider={provider} /> : null}
        </>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() =>
              authorize.mutate(provider.provider, {
                onError: (error) => toast.error(errorText(error)),
              })
            }
            disabled={authorize.isPending}
          >
            {authorize.isPending ? (
              <Spinner />
            ) : connection ? (
              <RefreshCw />
            ) : (
              <Link2 />
            )}
            {connection ? "Reconnect" : "Connect"} {provider.name}
          </Button>
          {connection ? <DisconnectControl provider={provider} /> : null}
        </div>
      )}
      {provider.provider === "spotify" && usable && !connection ? (
        <p className="text-meta text-fg-muted">
          Spotify only lets apps in development mode serve accounts the app
          owner has added to its allow-list.
        </p>
      ) : null}
    </li>
  );
}

export function ConnectionsPanel() {
  useOAuthResult();
  const list = useIntegrations();
  if (list.isPending) return <Skeleton className="h-48" />;
  if (list.isError) return <ErrorState onRetry={() => void list.refetch()} />;
  if (!list.data.providers.length) {
    return <EmptyState icon={Plug} title="No integrations available" />;
  }
  return (
    <ul className="flex flex-col gap-3" aria-label="Music services">
      {list.data.providers.map((provider) => (
        <ProviderCard
          key={provider.provider}
          provider={provider}
          keysReady={list.data.tokens_configured}
        />
      ))}
    </ul>
  );
}
