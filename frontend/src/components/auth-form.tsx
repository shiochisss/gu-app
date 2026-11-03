"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, apiFetch, safeNext } from "@/lib/api";
import type { UserInfo } from "@/lib/types";
import { Icon } from "./icons";
import { useSession } from "./runtime";
import { PageIntro } from "./ui";

export function AuthForm({ kind, next }: { kind: "login" | "register" | "staff"; next?: string }) {
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [visible, setVisible] = useState(false);
  const [pending, setPending] = useState(false); const [error, setError] = useState<ApiError | null>(null);
  const { user, setUser, signOut } = useSession(); const router = useRouter();
  const register = kind === "register"; const staff = kind === "staff";
  async function submit(event: FormEvent) {
    event.preventDefault(); if (pending) return; setPending(true); setError(null);
    try {
      const result = await apiFetch<{ user: UserInfo }>(`/api/v1/auth/${register ? "register" : "login"}`, { method: "POST", body: { email, password } });
      if (staff && result.user.role !== "STAFF") {
        await apiFetch<void>("/api/v1/auth/logout", { method: "POST" }); setUser(null); throw new ApiError(403, "FORBIDDEN", "店員アカウントでログインしてください");
      }
      setPassword(""); setUser(result.user);
      if (result.user.role === "STAFF") router.replace("/staff/orders");
      else router.replace(safeNext(next));
    } catch (failure) { setError(failure instanceof ApiError ? failure : new ApiError(0, "NETWORK_ERROR", "通信できませんでした")); }
    finally { setPending(false); }
  }
  const fields = Object.fromEntries((error?.fieldErrors ?? []).map(value => [value.field, value.message]));
  return <section className="mx-auto max-w-[440px]">
    <Link href="/" className="mb-6 inline-flex min-h-11 items-center gap-1 text-xs text-[#627589]"><Icon name="back" className="size-4"/>店舗選択に戻る</Link>
    <PageIntro eyebrow={staff ? "STAFF LOGIN" : register ? "CREATE ACCOUNT" : "WELCOME BACK"} title={staff ? "店員ログイン" : register ? "会員登録" : "ログイン"}>{staff ? "担当店舗のアカウントでログインしてください。" : register ? "店舗での受け取りを、もっとスムーズに。" : "登録したメールアドレスでログインしてください。"}</PageIntro>
    {error && <div role="alert" className="rounded-lg border border-[#F3C5C1] bg-[#FFF8F7] px-4 py-3 text-sm text-[#B42318]">{error.message}</div>}
    {(user?.role === "STAFF") ? <div className="rounded-xl border border-[#B8DECC] bg-[#F0FAF5] p-6"><div className="mb-3 flex size-11 items-center justify-center rounded-full bg-[#DDF0E6] text-[#067647]"><Icon name="check" className="size-6"/></div><h2 className="font-bold">{user?.storeName}の店員としてログインしました。</h2><p className="mt-2 break-all text-sm text-[#627589]">{user?.email}</p><Link href="/staff/orders" className="primary mt-5">注文を確認する</Link><button className="secondary mt-3 w-full" onClick={() => void signOut().catch(() => setError(new ApiError(0, "NETWORK_ERROR", "ログアウトできませんでした。もう一度お試しください。")))}>ログアウト</button></div> : <form onSubmit={submit} className="space-y-5">
      <div><label htmlFor="email" className="field-label">メールアドレス</label><input id="email" type="email" autoComplete="username" required maxLength={254} value={email} onChange={event => setEmail(event.target.value)} placeholder="example@email.com" className="field" aria-invalid={!!fields.email}/>{fields.email && <p className="field-error">{fields.email}</p>}</div>
      <div><label htmlFor="password" className="field-label">パスワード</label><div className="relative"><input id="password" type={visible ? "text" : "password"} autoComplete={register ? "new-password" : "current-password"} required minLength={12} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} className="field pr-16" aria-describedby="password-help" aria-invalid={!!fields.password}/><button type="button" className="absolute right-1 top-0 min-h-12 px-3 text-xs text-[#627589]" aria-label={visible ? "パスワードを隠す" : "パスワードを表示する"} onClick={() => setVisible(!visible)}>{visible ? "隠す" : "表示"}</button></div><p id="password-help" className="mt-2 text-xs text-[#627589]">{register ? "12〜128文字で入力してください。" : "12文字以上のパスワードを入力してください。"}</p>{fields.password && <p className="field-error">{fields.password}</p>}</div>
      <button disabled={pending} className="primary w-full">{pending ? "確認しています…" : register ? "会員登録する" : "ログインする"}<Icon name="arrow" className="size-4"/></button>
    </form>}
    {!staff && <div className="mt-7 border-t border-[#E7EDF3] pt-6 text-center text-sm text-[#627589]"><p>{register ? "すでにアカウントをお持ちの方" : "はじめてご利用の方"}</p><Link className="inline-flex min-h-11 items-center font-semibold text-[#1F4E8C] underline-offset-4 hover:underline" href={`${register ? "/login" : "/register"}${next ? `?next=${encodeURIComponent(safeNext(next))}` : ""}`}>{register ? "ログインへ" : "新規会員登録"}</Link></div>}
    {!staff && <p className="mt-7 text-center"><Link href="/staff/login" className="inline-flex min-h-11 items-center text-xs text-[#627589]">店舗スタッフの方はこちら</Link></p>}
  </section>;
}
