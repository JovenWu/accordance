import { useState } from "react";
import { LogIn } from "lucide-react";

import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";

export function LoginPage({
  onSubmit,
}: {
  onSubmit: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(username, password);
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? "Invalid username or password."
          : "Sign-in failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-page p-4">
      <form
        onSubmit={submit}
        className="flex w-full max-w-[400px] flex-col gap-5 rounded-3xl bg-surface p-6 shadow-modal sm:p-8"
      >
        <div className="flex items-center gap-3">
          <BrandMark className="size-10 rounded-xl" />
          <span className="flex flex-col gap-px">
            <span className="text-lg font-semibold text-ink">Accordance</span>
            <span className="text-xs text-muted-ink">
              GRI disclosure analysis
            </span>
          </span>
        </div>

        <div className="flex flex-col gap-1.5">
          <h1 className="text-2xl font-semibold text-ink">Sign in</h1>
          <p className="text-sm/6 text-muted-ink">
            Grade a sustainability report against the GRI Standards.
          </p>
        </div>

        <div className="flex flex-col gap-3.5">
          <Field label="Username">
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
        </div>

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}

        <Button
          type="submit"
          size="lg"
          className="h-10 w-full text-base"
          disabled={busy}
        >
          <LogIn aria-hidden />
          {busy ? "Signing in…" : "Sign in"}
        </Button>

        <p className="text-center text-xs text-muted-ink">
          Private deployment · ask an admin for an account
        </p>
      </form>
    </div>
  );
}
