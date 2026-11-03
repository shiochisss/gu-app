"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import { useSession } from "./runtime";
import { ErrorPanel, Loading } from "./ui";

export function StaffOnly({ children }: { children: ReactNode }) {
  const { user, checking, signOut } = useSession();
  const router = useRouter();
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => { if (!checking && user?.role !== "STAFF") router.replace("/staff/login"); }, [checking, user, router]);
  if (checking || user?.role !== "STAFF") return <Loading/>;
  return <><div className="mb-7 space-y-3 border-b pb-5"><p className="font-bold">{user.storeName}</p><p className="break-all text-sm">{user.email}</p><div className="flex flex-wrap gap-4"><Link href="/staff/orders">注文</Link><Link href="/staff/pickup">受取</Link><Link href="/staff/pos">POS</Link><Link href="/staff/pos/sales">売上履歴</Link><Link href="/staff/inventory">在庫</Link><Link href="/staff/store">受付</Link><button onClick={() => void signOut().catch(setError)}>ログアウト</button></div></div>{error && <ErrorPanel error={error}/ >}{children}</>;
}

// Keep the same key when a request's outcome is unknown. Editing the payload
// naturally creates a fresh key; synchronous ref guard also prevents rapid clicks.
export function useMutation() {
  const attempt = useRef<{ signature: string; key: string } | null>(null);
  const active = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function send<T>(path: string, body: unknown): Promise<T | undefined> {
    if (active.current) return;
    const signature = JSON.stringify([path, body]);
    if (attempt.current?.signature !== signature) attempt.current = { signature, key: crypto.randomUUID() };
    active.current = true; setPending(true); setError(null);
    try {
      const result = await apiFetch<T>(path, { method: "POST", body, idempotencyKey: attempt.current.key });
      attempt.current = null;
      return result;
    } catch (failure) {
      const value = failure instanceof ApiError ? failure : new ApiError(0, "NETWORK_ERROR", "通信できませんでした");
      if (value.status > 0 && value.status < 500 && value.code !== "IDEMPOTENCY_IN_PROGRESS") attempt.current = null;
      setError(value);
    } finally { active.current = false; setPending(false); }
  }
  async function retry<T>() {
    if (!attempt.current) return;
    const [path, body] = JSON.parse(attempt.current.signature) as [string, unknown];
    return send<T>(path, body);
  }
  return { send, retry, pending, error };
}
export function Pager({ page, total, change }: { page: number; total: number; change: (page: number) => void }) {
  return <div className="my-5 flex items-center gap-5"><button className="secondary" disabled={page <= 1} onClick={() => change(page - 1)}>前へ</button><span>{page} / {Math.max(1, Math.ceil(total / 20))}</span><button className="secondary" disabled={page * 20 >= total} onClick={() => change(page + 1)}>次へ</button></div>;
}
