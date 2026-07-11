import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { AuthShell } from "../components/AuthShell";
import { Banner, Button, Input, Label, Spinner } from "../components/ui";

export default function SignupPage() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signup(email, password, orgName);
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "sign up failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Create your workspace" subtitle="Spin up an org, a default workspace, and you're in.">
      <form onSubmit={onSubmit} className="space-y-4">
        {error && <Banner>{error}</Banner>}
        <div>
          <Label>Organization name</Label>
          <Input
            required
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            placeholder="Acme AI"
            autoFocus
          />
        </div>
        <div>
          <Label>Work email</Label>
          <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <Label>Password</Label>
          <Input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
          />
        </div>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? <Spinner /> : "Create workspace"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link to="/login" className="text-copper hover:text-copper-bright">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
