import type { ReactNode } from "react";
import { Link } from "react-router-dom";

/** Split auth layout: brand panel on the left, form card on the right. */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative hidden overflow-hidden border-r border-line bg-surface lg:block">
        <div className="core-lattice absolute inset-0" />
        <div className="relative flex h-full flex-col justify-between p-12">
          <Link to="/" className="font-mono text-sm font-semibold tracking-[0.3em] text-ink">
            KORTEX
          </Link>
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-copper">Core memory</p>
            <p className="mt-4 max-w-sm text-2xl font-medium leading-snug text-ink">
              The memory your agents keep — durable, scoped, and woven to last.
            </p>
          </div>
          <p className="font-mono text-[11px] text-faint">
            short-term · mid-term · long-term — settling into core over time
          </p>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex min-h-screen items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm fade-up">
          <Link to="/" className="mb-8 block font-mono text-sm font-semibold tracking-[0.3em] text-ink lg:hidden">
            KORTEX
          </Link>
          <h1 className="text-2xl font-semibold text-ink">{title}</h1>
          <p className="mt-1 text-sm text-muted">{subtitle}</p>
          <div className="mt-8">{children}</div>
        </div>
      </div>
    </div>
  );
}
