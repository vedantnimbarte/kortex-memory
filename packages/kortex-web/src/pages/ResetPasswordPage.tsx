import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { AuthShell } from "../components/AuthShell";
import { Banner, Button, Input, Label, Spinner } from "../components/ui";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api("/v1/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      navigate("/login?reset=1", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "reset failed");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthShell title="Reset password" subtitle="This link looks incomplete.">
        <Banner>Missing or invalid reset token. Request a new link.</Banner>
        <Link to="/forgot-password" className="mt-4 block text-center text-sm text-copper hover:text-copper-bright">
          Request a new link
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Set a new password" subtitle="Choose something you'll remember.">
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Banner>{error}</Banner>}
        <div>
          <Label>New password</Label>
          <Input
            type="password"
            required
            minLength={8}
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
          />
        </div>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? <Spinner /> : "Update password"}
        </Button>
      </form>
    </AuthShell>
  );
}
