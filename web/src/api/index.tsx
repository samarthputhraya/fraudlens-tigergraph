import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { createClient, probeHealth } from "./client";
import { createMock } from "./mock";
import type { Api, Health } from "./types";

interface ApiState {
  api: Api | null;
  health: Health | null;
  // why the mock is in use: "forced" by VITE_USE_MOCK, or "fallback" because /api/health did not answer
  mockReason: "forced" | "fallback" | null;
  online: boolean;
}

const Ctx = createContext<ApiState>({ api: null, health: null, mockReason: null, online: false });

const FORCE_MOCK = import.meta.env.VITE_USE_MOCK === "1" || import.meta.env.VITE_USE_MOCK === "true";

export function ApiProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ApiState>({ api: null, health: null, mockReason: null, online: false });

  useEffect(() => {
    let alive = true;
    (async () => {
      if (FORCE_MOCK) {
        const api = createMock();
        const health = await api.health();
        if (alive) setState({ api, health, mockReason: "forced", online: false });
        return;
      }
      const h = await probeHealth();
      if (!alive) return;
      if (h) setState({ api: createClient(), health: h, mockReason: null, online: true });
      else {
        const api = createMock();
        setState({ api, health: await api.health(), mockReason: "fallback", online: false });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Keep the connection pill honest while the backend is in use.
  useEffect(() => {
    if (!state.api || state.api.mode !== "live") return;
    const t = setInterval(async () => {
      const h = await probeHealth(4000);
      setState((s) => ({ ...s, health: h || s.health, online: !!h }));
    }, 20000);
    return () => clearInterval(t);
  }, [state.api]);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export function useApiState() {
  return useContext(Ctx);
}

export function useApi(): Api {
  const { api } = useContext(Ctx);
  if (!api) throw new Error("API not ready");
  return api;
}

// Small data hook: load once per key, expose reload.
export function useLoad<T>(fn: (api: Api) => Promise<T>, deps: unknown[] = []) {
  const { api } = useContext(Ctx);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!api) return;
    let alive = true;
    setLoading(true);
    fn(api)
      .then((d) => {
        if (alive) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => alive && setError(String(e?.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, tick, ...deps]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}
