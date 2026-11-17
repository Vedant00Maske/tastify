"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { BrandLogo } from "@/components/layout/navigation";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Spinner } from "@/components/ui/states";
import { hardNavigate } from "@/lib/navigation";
import { ApiError } from "@/services/api-client";

import { useLogin, useRegister } from "./queries";

const email = z.email("Enter a valid e-mail address").max(254);

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password").max(128),
});

export const registerSchema = z
  .object({
    display_name: z.string().max(80).optional(),
    email,
    password: z
      .string()
      .min(10, "Use at least 10 characters")
      .max(128, "Use at most 128 characters")
      .refine((v) => v.trim() === v, "No spaces at the start or end"),
    confirm: z.string(),
    accept_terms: z.boolean().refine((v) => v, "Accept the terms to continue"),
  })
  .refine((data) => data.password === data.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });

/** Only same-site paths are followed after login (no open redirects). */
export function safeNext(next: string | null, fallback = "/home"): string {
  return next && next.startsWith("/") && !next.startsWith("//")
    ? next
    : fallback;
}

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    error instanceof ApiError
      ? error.status === 429
        ? "Too many attempts. Wait a few minutes and try again."
        : error.message
      : "Could not reach TASTIFY. Check your connection and try again.";
  return (
    <p
      role="alert"
      className="rounded-button border border-error/30 bg-error/10 px-3 py-2 text-support text-error"
    >
      {message}
    </p>
  );
}

function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="w-full max-w-sm">
      <BrandLogo className="mb-10" href="/" />
      <h1 className="text-page font-bold">{title}</h1>
      <p className="mt-2 mb-8 text-fg-secondary">{subtitle}</p>
      {children}
    </div>
  );
}

export function LoginForm() {
  const next = safeNext(useSearchParams().get("next"));
  const login = useLogin();
  const form = useForm<z.infer<typeof loginSchema>>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });
  const { errors } = form.formState;
  return (
    <AuthCard
      title="Welcome back"
      subtitle="Sign in to pick up where your taste left off."
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit((values) =>
          login.mutate(values, {
            onSuccess: (me) =>
              hardNavigate(me.onboarding_completed ? next : "/onboarding", {
                replace: true,
              }),
          }),
        )}
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
        <Field id="password" label="Password" error={errors.password?.message}>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            {...form.register("password")}
          />
        </Field>
        <FormError error={login.error} />
        <Button
          type="submit"
          size="lg"
          disabled={login.isPending}
          className="mt-2"
        >
          {login.isPending ? <Spinner /> : null} Sign in
        </Button>
      </form>
      <p className="mt-6 text-support text-fg-secondary">
        New to TASTIFY?{" "}
        <Link
          href="/register"
          className="font-semibold text-accent hover:underline"
        >
          Create an account
        </Link>
      </p>
    </AuthCard>
  );
}

export function RegisterForm() {
  const register = useRegister();
  const form = useForm<z.infer<typeof registerSchema>>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      display_name: "",
      email: "",
      password: "",
      confirm: "",
      accept_terms: false,
    },
  });
  const { errors } = form.formState;
  return (
    <AuthCard
      title="Create your account"
      subtitle="A minute now, and every recommendation gets more personal."
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit(
          ({ display_name, email, password, accept_terms }) =>
            register.mutate(
              {
                email,
                password,
                accept_terms,
                display_name: display_name?.trim() || undefined,
              },
              {
                onSuccess: () => hardNavigate("/onboarding", { replace: true }),
              },
            ),
        )}
      >
        <Field
          id="display_name"
          label="Name (optional)"
          error={errors.display_name?.message}
        >
          <Input
            id="display_name"
            autoComplete="nickname"
            {...form.register("display_name")}
          />
        </Field>
        <Field id="email" label="E-mail" error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            aria-invalid={!!errors.email}
            {...form.register("email")}
          />
        </Field>
        <Field
          id="password"
          label="Password"
          error={errors.password?.message}
          hint="At least 10 characters."
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
          label="Confirm password"
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
        <label className="flex items-start gap-3 text-support text-fg-secondary">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-[var(--color-accent)]"
            aria-invalid={!!errors.accept_terms}
            {...form.register("accept_terms")}
          />
          <span>
            I accept the terms and the privacy notice: TASTIFY stores what I
            play, like and skip to personalize my recommendations, and I can
            export or delete it at any time.
          </span>
        </label>
        {errors.accept_terms ? (
          <p role="alert" className="-mt-2 text-support text-error">
            {errors.accept_terms.message}
          </p>
        ) : null}
        <FormError error={register.error} />
        <Button
          type="submit"
          size="lg"
          disabled={register.isPending}
          className="mt-2"
        >
          {register.isPending ? <Spinner /> : null} Create account
        </Button>
      </form>
      <p className="mt-6 text-support text-fg-secondary">
        Already have an account?{" "}
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
