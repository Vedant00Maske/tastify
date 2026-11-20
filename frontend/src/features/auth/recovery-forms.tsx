"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, MailCheck, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Spinner } from "@/components/ui/states";
import { ApiError } from "@/services/api-client";
import { auth } from "@/services/api";

import { AuthCard, FormError } from "./auth-forms";

const emailSchema = z.object({
  email: z.email("Enter a valid e-mail address").max(254),
});

const resetSchema = z
  .object({
    password: z
      .string()
      .min(10, "Use at least 10 characters")
      .max(128, "Use at most 128 characters")
      .refine((v) => v.trim() === v, "No spaces at the start or end"),
    confirm: z.string(),
  })
  .refine((data) => data.password === data.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

/**
 * The single-use token from an e-mailed link. It is read once and removed from the address bar,
 * so it does not linger in the history or get shared by copying the URL.
 */
function useLinkToken(): string | null {
  const params = useSearchParams();
  const [token] = useState(() => params.get("token"));
  useEffect(() => {
    if (token && typeof window !== "undefined") {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [token]);
  return token;
}

function mailMessage(error: unknown): unknown {
  if (error instanceof ApiError && error.status === 503) {
    return new ApiError(
      503,
      "E-mail is not available right now, so we cannot send a reset link. Try again later.",
    );
  }
  return error;
}

export function ForgotPasswordForm() {
  const request = useMutation({ mutationFn: auth.forgotPassword });
  const form = useForm<z.infer<typeof emailSchema>>({
    resolver: zodResolver(emailSchema),
    defaultValues: { email: "" },
  });
  const { errors } = form.formState;

  if (request.isSuccess) {
    return (
      <AuthCard
        title="Check your inbox"
        subtitle="If an account uses that address, we sent it a link to choose a new password. The link works once, for an hour."
      >
        <div className="flex items-start gap-3 rounded-card border border-border bg-surface p-4 text-fg-secondary">
          <MailCheck
            className="mt-0.5 size-5 shrink-0 text-accent"
            aria-hidden
          />
          <p className="text-support">
            Nothing arrived? Check the spam folder, or request a new link in a
            few minutes.
          </p>
        </div>
        <p className="mt-6 text-support text-fg-secondary">
          <Link
            href="/login"
            className="font-semibold text-accent hover:underline"
          >
            Back to sign in
          </Link>
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Forgot your password?"
      subtitle="Enter your account's e-mail address and we will send you a link to choose a new one."
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit(({ email }) => request.mutate(email))}
      >
        <Field id="email" label="E-mail" error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            aria-invalid={!!errors.email}
            {...form.register("email")}
          />
        </Field>
        <FormError error={mailMessage(request.error)} />
        <Button
          type="submit"
          size="lg"
          disabled={request.isPending}
          className="mt-2"
        >
          {request.isPending ? <Spinner /> : null} Send reset link
        </Button>
      </form>
      <p className="mt-6 text-support text-fg-secondary">
        Remembered it?{" "}
        <Link
          href="/login"
          className="font-semibold text-accent hover:underline"
        >
          Sign in
        </Link>
      </p>
    </AuthCard>
  );
}

export function ResetPasswordForm() {
  const token = useLinkToken();
  const reset = useMutation({ mutationFn: auth.resetPassword });
  const form = useForm<z.infer<typeof resetSchema>>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: "", confirm: "" },
  });
  const { errors } = form.formState;

  if (!token) {
    return <InvalidLink kind="reset" />;
  }
  if (reset.isSuccess) {
    return (
      <AuthCard
        title="Password changed"
        subtitle="Your new password is set, and every device was signed out. Sign in with the new password."
      >
        <Button asChild size="lg" className="w-full">
          <Link href="/login">Sign in</Link>
        </Button>
      </AuthCard>
    );
  }
  if (reset.error instanceof ApiError && reset.error.status === 400) {
    return <InvalidLink kind="reset" />;
  }

  return (
    <AuthCard
      title="Choose a new password"
      subtitle="At least 10 characters. A few unrelated words make a strong one."
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit(({ password }) =>
          reset.mutate({ token, new_password: password }),
        )}
      >
        <Field
          id="password"
          label="New password"
          error={errors.password?.message}
        >
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            aria-invalid={!!errors.password}
            {...form.register("password")}
          />
        </Field>
        <Field
          id="confirm"
          label="Confirm new password"
          error={errors.confirm?.message}
        >
          <Input
            id="confirm"
            type="password"
            autoComplete="new-password"
            aria-invalid={!!errors.confirm}
            {...form.register("confirm")}
          />
        </Field>
        <FormError error={reset.error} />
        <Button
          type="submit"
          size="lg"
          disabled={reset.isPending}
          className="mt-2"
        >
          {reset.isPending ? <Spinner /> : null} Set new password
        </Button>
      </form>
    </AuthCard>
  );
}

function InvalidLink({ kind }: { kind: "reset" | "verify" }) {
  return (
    <AuthCard
      title="This link no longer works"
      subtitle={
        kind === "reset"
          ? "Reset links work once and expire after an hour. Request a new one."
          : "Verification links work once and expire after two days. Send a new one from Settings."
      }
    >
      <div className="flex items-start gap-3 rounded-card border border-border bg-surface p-4">
        <XCircle className="mt-0.5 size-5 shrink-0 text-error" aria-hidden />
        <p className="text-support text-fg-secondary">
          If you requested several links, only the newest one works.
        </p>
      </div>
      <Button asChild size="lg" className="mt-6 w-full">
        <Link href={kind === "reset" ? "/forgot-password" : "/settings"}>
          {kind === "reset" ? "Request a new link" : "Go to Settings"}
        </Link>
      </Button>
    </AuthCard>
  );
}

export function VerifyEmail() {
  const token = useLinkToken();
  const verify = useMutation({ mutationFn: auth.verifyEmail });
  const sent = useRef(false);
  const { mutate } = verify;

  useEffect(() => {
    // Exactly once, even when React runs effects twice in development.
    if (token && !sent.current) {
      sent.current = true;
      mutate(token);
    }
  }, [token, mutate]);

  if (!token || verify.isError) {
    return <InvalidLink kind="verify" />;
  }
  if (verify.isSuccess) {
    return (
      <AuthCard
        title="E-mail address confirmed"
        subtitle="Thanks. You can always recover your account through this address."
      >
        <div className="flex items-center gap-3 text-fg-secondary">
          <CheckCircle2 className="size-5 text-accent" aria-hidden />
          <span role="status">Your address is verified.</span>
        </div>
        <Button asChild size="lg" className="mt-6 w-full">
          <Link href="/home">Continue to SONIQUEO</Link>
        </Button>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Confirming your address" subtitle="One moment…">
      <div role="status" className="flex items-center gap-3 text-fg-secondary">
        <Spinner /> Checking the link
      </div>
    </AuthCard>
  );
}
