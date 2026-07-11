import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ── Button ────────────────────────────────────────────────────────────────
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "outline" | "danger";
  size?: "sm" | "md";
};
export function Button({ variant = "primary", size = "md", className, ...rest }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none whitespace-nowrap";
  const sizes = { sm: "px-2.5 py-1.5 text-xs", md: "px-3.5 py-2 text-sm" };
  const variants = {
    primary: "bg-copper text-[#1a0e02] hover:bg-copper-bright",
    ghost: "text-muted hover:text-ink hover:bg-surface-2",
    outline: "border border-line-bright text-ink hover:border-copper hover:text-copper",
    danger: "border border-danger/40 text-danger hover:bg-danger/10",
  };
  return <button className={cx(base, sizes[size], variants[variant], className)} {...rest} />;
}

// ── Surfaces ────────────────────────────────────────────────────────────────
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("rounded-xl border border-line bg-surface", className)}>{children}</div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-copper">{children}</span>
  );
}

// ── Form controls ───────────────────────────────────────────────────────────
export function Label({ children }: { children: ReactNode }) {
  return (
    <span className="mb-1.5 block font-mono text-[11px] uppercase tracking-wider text-faint">
      {children}
    </span>
  );
}

const fieldClass =
  "w-full rounded-md border border-line bg-bg px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-copper focus:outline-none";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(fieldClass, props.className)} />;
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(fieldClass, "resize-y font-mono leading-relaxed", props.className)} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldClass, "appearance-none pr-8", props.className)} />;
}

// ── Feedback ────────────────────────────────────────────────────────────────
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx(
        "inline-block h-4 w-4 animate-spin rounded-full border-2 border-line-bright border-t-copper",
        className,
      )}
      aria-label="Loading"
    />
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 py-16 text-center">
      <p className="text-sm text-muted">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-xs text-faint">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Banner({ tone = "error", children }: { tone?: "error" | "ok"; children: ReactNode }) {
  const tones = {
    error: "border-danger/30 bg-danger/10 text-danger",
    ok: "border-ok/30 bg-ok/10 text-ok",
  };
  return <div className={cx("rounded-md border px-3 py-2 text-sm", tones[tone])}>{children}</div>;
}

// ── Domain: the memory data language ────────────────────────────────────────
const TIER_META: Record<string, { label: string; color: string }> = {
  short: { label: "Short-term", color: "var(--color-tier-short)" },
  mid: { label: "Mid-term", color: "var(--color-tier-mid)" },
  long: { label: "Long-term", color: "var(--color-tier-long)" },
};

export function TierChip({ tier }: { tier: string }) {
  const m = TIER_META[tier] ?? { label: tier, color: "var(--color-muted)" };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider"
      style={{ borderColor: `${m.color}55`, color: m.color }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: m.color }} />
      {m.label}
    </span>
  );
}

const SENS_COLOR: Record<string, string> = {
  public: "var(--color-tier-short)",
  internal: "var(--color-muted)",
  confidential: "var(--color-tier-mid)",
  secret: "var(--color-danger)",
};
export function SensitivityChip({ level }: { level: string }) {
  const color = SENS_COLOR[level] ?? "var(--color-muted)";
  return (
    <span className="font-mono text-[10px] uppercase tracking-wider" style={{ color }}>
      {level}
    </span>
  );
}

/** The signature element: a ferrite-thread meter reading decay (0..1). */
export function DecayMeter({ value, label = true }: { value: number; label?: boolean }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, var(--color-copper-dim), var(--color-copper-bright))",
          }}
        />
      </div>
      {label && <span className="font-mono text-[10px] tabular-nums text-faint">{value.toFixed(2)}</span>}
    </div>
  );
}

export function MonoId({ id, full = false }: { id: string; full?: boolean }) {
  if (full) {
    return (
      <button
        onClick={() => void navigator.clipboard.writeText(id)}
        title="Copy ID"
        className="font-mono text-[11px] text-faint transition-colors hover:text-copper"
      >
        {id}
      </button>
    );
  }
  return <span className="font-mono text-[11px] text-faint">{id.slice(0, 8)}</span>;
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-40 grid place-items-center bg-black/60 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-xl border border-line bg-surface p-6 shadow-2xl shadow-black/50 fade-up"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <button onClick={onClose} className="text-muted hover:text-ink" aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
