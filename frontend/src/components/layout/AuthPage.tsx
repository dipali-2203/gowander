import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, Mail, LockKeyhole, Moon, Sun } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import heroImage from "@/assets/udaipur-hero.jpg";
import { Logo } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTheme } from "@/hooks/use-theme";
import {
  confirmPasswordReset,
  googleSignInStartUrl,
  requestPasswordReset,
  signIn,
  signUp,
} from "@/lib/api";

type AuthMode = "login" | "signup" | "reset";

export function AuthPage({ mode }: { mode: AuthMode }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState("");
  const [resetMessage, setResetMessage] = useState("");
  const isLogin = mode === "login";
  const isSignup = mode === "signup";
  const isReset = mode === "reset";
  const { theme, toggle } = useTheme();
  const googleEnabled = import.meta.env["VITE_GOOGLE_SIGN_IN_ENABLED"] === "true";

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const token = hash.get("token");
    if (token) {
      setResetToken(token);
    }
    if (new URLSearchParams(window.location.search).get("auth_error") === "google") {
      setError(
        "Google sign-in could not be completed. Please try again or use your email and password.",
      );
    }
    if (new URLSearchParams(window.location.search).get("auth_error") === "google_account_exists") {
      setError(
        "An account with this email already exists. Please sign in using your email and password, then connect your Google account from Account Settings.",
      );
    }
    if (new URLSearchParams(window.location.search).get("auth_error") === "google_link_session") {
      setError(
        "Your session expired during Google account linking. Sign in and try connecting Google again.",
      );
    }
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const data = new FormData(event.currentTarget);
    setBusy(true);
    try {
      if (isReset && !resetToken) {
        const result = await requestPasswordReset(email);
        setResetMessage(result.message);
      } else if (isReset) {
        const password = String(data.get("password") ?? "");
        const confirmation = String(data.get("confirmPassword") ?? "");
        if (password !== confirmation) throw new Error("The passwords do not match.");
        await confirmPasswordReset(resetToken, password);
        setResetMessage("Your password has been updated. You can now sign in.");
        window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}`);
      } else {
        const password = String(data.get("password") ?? "");
        if (isSignup) {
          await signUp({ name: String(data.get("name") ?? "").trim(), email, password });
        } else {
          await signIn({ email, password });
        }
        await navigate({ to: "/app/dashboard" });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Authentication failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative isolate flex min-h-dvh items-center justify-center overflow-hidden bg-background px-4 py-8">
      <img
        src={theme === "dark" ? "/landing-dark.png" : heroImage}
        alt=""
        aria-hidden="true"
        className="absolute inset-0 -z-20 h-full w-full scale-105 object-cover blur-[10px]"
      />
      <div className="absolute inset-0 -z-10 bg-photo-overlay/75 backdrop-blur-[1px]" />

      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center justify-between">
          <Logo textClassName="font-bold text-white" />
          <div className="flex items-center gap-1.5">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggle}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              className="text-photo-foreground hover:bg-white/10 hover:text-white"
            >
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <Button
              asChild
              variant="ghost"
              className="h-9 text-photo-foreground hover:bg-white/10 hover:text-white"
            >
              <Link to="/">
                <ArrowLeft className="h-4 w-4" /> Back home
              </Link>
            </Button>
          </div>
        </div>

        <section className="rounded-2xl border border-white/20 bg-card/90 p-6 text-card-foreground shadow-lift backdrop-blur-xl sm:p-8">
          <div className="mb-7 space-y-2 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">
              {isLogin ? "Welcome back" : isSignup ? "Create your account" : "Reset your password"}
            </h1>
            <p className="text-sm text-muted-foreground">
              {isLogin
                ? "Sign in to continue planning your next Indian journey."
                : isSignup
                  ? "Start building thoughtful trips across India with AI."
                  : resetToken
                    ? "Choose a new password for your account."
                    : "Enter your email and we’ll send a secure reset link."}
            </p>
          </div>

          {!isReset && googleEnabled && (
            <>
              <Button
                asChild
                type="button"
                variant="outline"
                className="h-10 w-full bg-background/70"
              >
                <a href={googleSignInStartUrl}>
                  <img src="/google-icon.png" alt="" className="mr-2 h-5 w-5 object-contain" />
                  Continue with Google
                </a>
              </Button>
              <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
                <span className="h-px flex-1 bg-border" />
                <span>or continue with email</span>
                <span className="h-px flex-1 bg-border" />
              </div>
            </>
          )}

          <form className="space-y-4" onSubmit={handleSubmit}>
            {isSignup && (
              <Field label="Full name" htmlFor="name">
                <Input
                  id="name"
                  name="name"
                  placeholder="Aarav Sharma"
                  autoComplete="name"
                  required
                />
              </Field>
            )}
            {(!isReset || !resetToken) && (
              <Field label="Email address" htmlFor="email">
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="email"
                    name="email"
                    type="email"
                    placeholder="you@example.com"
                    autoComplete="email"
                    className="pl-9"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                  />
                </div>
              </Field>
            )}
            {(!isReset || resetToken) && (
              <Field label={isReset ? "New password" : "Password"} htmlFor="password">
                <div className="relative">
                  <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="password"
                    name="password"
                    type="password"
                    placeholder={isLogin ? "Enter your password" : "At least 12 characters"}
                    autoComplete={isLogin ? "current-password" : "new-password"}
                    minLength={12}
                    className="pl-9"
                    required
                  />
                </div>
              </Field>
            )}
            {isReset && resetToken && (
              <Field label="Confirm new password" htmlFor="confirmPassword">
                <Input
                  id="confirmPassword"
                  name="confirmPassword"
                  type="password"
                  autoComplete="new-password"
                  minLength={12}
                  required
                />
              </Field>
            )}
            {isLogin && (
              <div className="flex justify-end">
                <Link
                  to="/forgot-password"
                  className="text-xs font-semibold text-primary hover:underline"
                >
                  Forgot password?
                </Link>
              </div>
            )}
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
            {resetMessage ? (
              <p role="status" className="text-sm text-muted-foreground">
                {resetMessage}
              </p>
            ) : null}
            <Button
              type="submit"
              disabled={
                busy ||
                (isReset &&
                  !!resetToken &&
                  resetMessage.startsWith("Your password has been updated"))
              }
              className="h-11 w-full"
            >
              {busy
                ? "Please wait…"
                : isReset
                  ? resetToken
                    ? "Update password"
                    : "Send reset link"
                  : isLogin
                    ? "Sign in"
                    : "Create account"}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            {isLogin
              ? "Don't have an account?"
              : isSignup
                ? "Already have an account?"
                : "Remember your password?"}{" "}
            <Link
              to={isLogin ? "/signup" : "/login"}
              className="font-bold text-primary hover:underline"
            >
              {isLogin ? "Sign up" : "Log in"}
            </Link>
          </p>
        </section>

        <p className="mt-5 text-center text-xs text-white/70">
          By continuing, you agree to GoWander&apos;s terms and privacy policy.
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}
