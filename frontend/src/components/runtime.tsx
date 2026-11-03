"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import { getSnapshot, getServerSnapshot, subscribe } from "@/lib/store";
import type { StoreList, UserInfo } from "@/lib/types";

export function useApi<T>(path: string | null) {
  const [revision, setRevision] = useState(0);
  const key = `${path}:${revision}`;
  const [state, setState] = useState<{ key: string; data: T | null; error: ApiError | null }>({ key: "", data: null, error: null });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController(); let active = true;
    apiFetch<T>(path, { signal: controller.signal }).then(data => { if (active) setState({ key, data, error: null }); }).catch(error => { if (active && error?.name !== "AbortError") setState({ key, data: null, error }); });
    return () => { active = false; controller.abort(); };
  }, [path, key]);
  const retry = useCallback(() => setRevision(value => value + 1), []);
  return { data: state.key === key ? state.data : null, error: state.key === key ? state.error : null, loading: !!path && state.key !== key, retry };
}

type Session = { user: UserInfo | null; checking: boolean; setUser: (user: UserInfo | null) => void; signOut: () => Promise<void>; stores: ReturnType<typeof useApi<StoreList>> };
const SessionContext = createContext<Session | null>(null);
export function AppProvider({ children }: { children: ReactNode }) {
  const [user, updateUser] = useState<UserInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const generation = useRef(0);
  const setUser = useCallback((value: UserInfo | null) => { generation.current++; updateUser(value); setChecking(false); }, []);
  const stores = useApi<StoreList>("/api/v1/stores");
  useEffect(() => { let active = true; const started = generation.current; apiFetch<UserInfo>("/api/v1/auth/me").then(value => { if (active && generation.current === started) updateUser(value); }).catch(() => {}).finally(() => { if (active) setChecking(false); }); return () => { active = false; }; }, []);
  const signOut = useCallback(async () => { generation.current++; await apiFetch<void>("/api/v1/auth/logout", { method: "POST" }); setUser(null); }, [setUser]);
  return <SessionContext.Provider value={{ user, checking, setUser, signOut, stores }}>{children}</SessionContext.Provider>;
}
export function useSession() { const value = useContext(SessionContext); if (!value) throw new Error("AppProvider is required"); return value; }
export function useCartStore() { return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot); }
