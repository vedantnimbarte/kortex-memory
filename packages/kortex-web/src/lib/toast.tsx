import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Tone = "ok" | "error" | "info";
type Toast = { id: number; message: string; tone: Tone };

const ToastContext = createContext<((message: string, tone?: Tone) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const toast = useCallback((message: string, tone: Tone = "info") => {
    const id = nextId.current++;
    setToasts((cur) => [...cur, { id, message, tone }]);
    setTimeout(() => setToasts((cur) => cur.filter((t) => t.id !== id)), 4000);
  }, []);

  // Global rate-limit feedback (dispatched from the API client).
  useEffect(() => {
    const handler = (e: Event) => toast((e as CustomEvent<string>).detail, "error");
    window.addEventListener("kortex:ratelimited", handler);
    return () => window.removeEventListener("kortex:ratelimited", handler);
  }, [toast]);

  const tones: Record<Tone, string> = {
    ok: "border-ok/40 text-ok",
    error: "border-danger/40 text-danger",
    info: "border-line-bright text-ink",
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto max-w-xs rounded-lg border bg-surface px-4 py-3 text-sm shadow-xl shadow-black/40 fade-up ${tones[t.tone]}`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (message: string, tone?: Tone) => void {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
