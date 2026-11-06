import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { Api } from './api/client';

interface Ctx {
  api: Api;
  tick: number;
  bump: () => void;
}
const AppCtx = createContext<Ctx | null>(null);

export function AppProvider({ api, children }: { api: Api; children: ReactNode }) {
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((t) => t + 1), []);
  return <AppCtx.Provider value={{ api, tick, bump }}>{children}</AppCtx.Provider>;
}

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error('AppProvider missing');
  return c;
}

export interface Loaded<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount, on dependency change, and whenever any demo/decision action bumps the global tick. */
export function useData<T>(fn: (api: Api) => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const { api, tick } = useApp();
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({ data: null, error: null, loading: true });
  const [local, setLocal] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    fn(api).then(
      (data) => { if (my === seq.current) setState({ data, error: null, loading: false }); },
      (error: Error) => { if (my === seq.current) setState((s) => ({ data: s.data, error, loading: false })); },
    );
    return () => { seq.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, tick, local, ...deps]);
  return { ...state, reload: () => setLocal((x) => x + 1) };
}
