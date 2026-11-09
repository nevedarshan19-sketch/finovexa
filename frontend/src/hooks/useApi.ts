import { useCallback, useEffect, useRef, useState } from "react";
import { api, getErrorMessage } from "../lib/api";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useApi<T>(
  path: string | null,
  options: { pollMs?: number } = {},
): ApiState<T> {
  const { pollMs } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const pathRef = useRef(path);
  pathRef.current = path;

  useEffect(() => {
    if (!path) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    let alive = true;
    setLoading(true);
    setError(null);

    const load = async (background: boolean) => {
      try {
        const result = await api<T>(path, { signal: controller.signal });
        if (!alive) return;
        setData(result);
        setError(null);
      } catch (err: unknown) {
        if (!alive || (err instanceof DOMException && err.name === "AbortError")) return;
        // Background polls stay quiet; the last good snapshot remains on screen.
        if (!background || !pathRef.current) setError(getErrorMessage(err));
      } finally {
        if (alive && !background) setLoading(false);
      }
    };

    void load(false);
    const timer = pollMs ? window.setInterval(() => void load(true), pollMs) : undefined;
    return () => {
      alive = false;
      if (timer) window.clearInterval(timer);
      controller.abort();
    };
  }, [path, nonce, pollMs]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, loading, error, reload };
}
