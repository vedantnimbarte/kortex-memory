import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { AuthShell } from "../components/AuthShell";
import { Banner, Spinner } from "../components/ui";

type Status = "checking" | "ok" | "failed";

export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    if (!token) {
      setStatus("failed");
      return;
    }
    api("/v1/auth/verify-email/confirm", { method: "POST", body: JSON.stringify({ token }) })
      .then(() => setStatus("ok"))
      .catch(() => setStatus("failed"));
  }, [token]);

  return (
    <AuthShell title="Verify email" subtitle="Confirming your address.">
      {status === "checking" && (
        <div className="flex items-center gap-3 text-sm text-muted">
          <Spinner /> Verifying…
        </div>
      )}
      {status === "ok" && (
        <div className="space-y-4">
          <Banner tone="ok">Your email is verified. You're all set.</Banner>
          <Link to="/app" className="block text-center text-sm text-copper hover:text-copper-bright">
            Go to the app
          </Link>
        </div>
      )}
      {status === "failed" && (
        <div className="space-y-4">
          <Banner>This verification link is invalid or has expired.</Banner>
          <Link to="/app" className="block text-center text-sm text-muted hover:text-ink">
            Back to the app
          </Link>
        </div>
      )}
    </AuthShell>
  );
}
