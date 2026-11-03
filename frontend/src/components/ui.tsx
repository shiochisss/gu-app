"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { cartCount } from "@/lib/cart";
import { formatTime } from "@/lib/format";
import type { StoreSummary } from "@/lib/types";
import { Icon } from "./icons";
import { useCartStore, useSession } from "./runtime";

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [logoutError, setLogoutError] = useState(false);
  const { user, signOut, stores } = useSession();
  const { cart, selectedStoreId } = useCartStore();
  const store = stores.data?.items.find(value => value.storeId === selectedStoreId);
  const staff = path.startsWith("/staff");
  const home = selectedStoreId ? `/stores/${selectedStoreId}/products` : "/";
  return <div className="min-h-dvh bg-white">
    <header className="sticky top-0 z-30 border-b border-[#D9E2EC] bg-white/95 backdrop-blur-sm">
      <div className={`mx-auto flex h-[72px] items-center justify-between px-5 ${staff ? "max-w-5xl" : "max-w-[480px]"}`}>
        <Link href="/" className="flex min-h-11 flex-col justify-center" aria-label="Pickup App ホーム"><span className="text-[22px] font-extrabold tracking-[-0.7px] text-[#1F4E8C]">Pickup App<span className="text-[#1F2933]">.</span></span><span className="text-[10px] font-semibold tracking-[0.18em] text-[#627589]">STORE PICKUP</span></Link>
        {staff ? <span className="text-sm font-semibold">{user?.storeName ?? "店員ログイン"}</span> : <div className="flex items-center gap-3"><Link href="/" className="flex min-h-11 max-w-[155px] items-center gap-1 text-xs font-medium text-[#526778]"><Icon name="pin" className="h-4 w-4 shrink-0"/><span className="truncate">{store?.name ?? "受取店舗を選択"}</span><span aria-hidden="true">⌄</span></Link><Link href="/cart" aria-label={`カート ${cartCount(cart)}点`} className="relative flex size-11 items-center justify-center rounded-full bg-[#F5F7FA]"><Icon name="bag" className="size-5"/>{cartCount(cart) > 0 && <span className="absolute -right-0.5 -top-0.5 flex size-[19px] items-center justify-center rounded-full bg-[#1F4E8C] text-[10px] font-bold text-white">{cartCount(cart)}</span>}</Link></div>}
      </div>
    </header>
    <main className={`mx-auto min-h-[calc(100dvh-153px)] px-5 pb-28 pt-7 ${staff ? "max-w-5xl" : "max-w-[480px]"}`}>{logoutError && <div role="alert" className="mb-4 text-sm text-[#B42318]">ログアウトできませんでした。もう一度お試しください。</div>}{children}</main>
    {!staff && <nav aria-label="メインメニュー" className="fixed inset-x-0 bottom-0 z-30 border-t border-[#D9E2EC] bg-white pb-[env(safe-area-inset-bottom)]"><div className="mx-auto grid max-w-[480px] grid-cols-4">
      <NavItem href={home} icon="home" label="ホーム" active={path === "/" || path.startsWith("/stores/")}/>
      <NavItem href="/cart" icon="bag" label={`カート${cartCount(cart) ? ` (${cartCount(cart)})` : ""}`} active={path === "/cart"}/>
      <Link href="/orders" className="flex min-h-[74px] flex-col items-center justify-center gap-1 text-[11px] text-[#526778]"><Icon name="orders" className="size-[22px]"/><span>注文</span></Link>
      {user ? <button onClick={() => void signOut().then(() => setLogoutError(false)).catch(() => setLogoutError(true))} className="flex min-h-[74px] flex-col items-center justify-center gap-1 text-[11px] text-[#526778]"><Icon name="user" className="size-[22px]"/><span>ログアウト</span></button> : <NavItem href="/login" icon="user" label="ログイン" active={path === "/login" || path === "/register"}/>}
    </div></nav>}
  </div>;
}
function NavItem({ href, label, icon, active }: { href: string; label: string; icon: "home" | "bag" | "user"; active: boolean }) { return <Link href={href} aria-current={active ? "page" : undefined} className={`flex min-h-[74px] flex-col items-center justify-center gap-1 text-[11px] ${active ? "font-bold text-[#1F4E8C]" : "text-[#526778]"}`}><Icon name={icon} className="size-[22px]"/><span>{label}</span></Link>; }
export function PageIntro({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) { return <div className="mb-7"><p className="mb-2 text-[11px] font-bold tracking-[0.14em] text-[#1F4E8C]">{eyebrow}</p><h1 className="whitespace-pre-line text-[24px] font-bold leading-[1.5] tracking-[-0.04em]">{title}</h1>{children && <div className="mt-3 text-sm leading-7 text-[#627589]">{children}</div>}</div>; }
export function Loading({ label = "読み込み中" }: { label?: string }) { return <div role="status" aria-label={label} className="space-y-4 py-2"><span className="sr-only">{label}</span>{[0, 1, 2].map(value => <div key={value} className="h-36 animate-pulse rounded-xl bg-[#F0F3F7]"/>)}</div>; }
export function ErrorPanel({ error, retry }: { error: ApiError | Error; retry?: () => void }) { const message = error instanceof ApiError && error.status === 403 ? "この画面は表示できません" : error.message || "通信できませんでした"; return <div role="alert" className="rounded-xl border border-[#F3C5C1] bg-[#FFF8F7] p-5 text-sm leading-6"><p className="font-semibold text-[#B42318]">{message}</p>{retry && <button className="secondary mt-4" onClick={retry}>再試行</button>}</div>; }
export function Empty({ children }: { children: ReactNode }) { return <div className="rounded-xl border border-dashed border-[#D9E2EC] bg-[#F8FAFC] px-5 py-12 text-center text-sm leading-7 text-[#627589]">{children}</div>; }
export function ProductImage({ name, color, large = false }: { name: string; color: string; large?: boolean }) { const safe = /^#[0-9a-f]{6}$/i.test(color) ? color : "#E8EDF3"; return <div aria-label={`${name}の仮画像`} className={`relative flex aspect-square items-center justify-center overflow-hidden ${large ? "rounded-2xl" : "rounded-lg"}`} style={{ backgroundColor: safe }}><div className="absolute inset-0 bg-gradient-to-br from-white/50 to-black/5"/><div className="relative flex aspect-[0.82] w-[53%] items-center justify-center rounded-[20%_20%_8%_8%] border border-black/5 bg-white/45 shadow-sm"><span className={`${large ? "text-8xl" : "text-5xl"} font-light text-[#1F2933]/30`}>{name.charAt(0)}</span></div></div>; }
export function StoreStatus({ store }: { store: StoreSummary }) { const message = !store.acceptingOrders ? "受付停止中" : store.today.closed ? "本日休業" : store.canOrderNow ? `注文受付中（${formatTime(store.orderCutoffAt)}まで）` : "本日の受付は終了しました"; return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${store.canOrderNow ? "bg-[#EAF6F0] text-[#067647]" : "bg-[#F0F3F7] text-[#627589]"}`}><span className={`size-1.5 rounded-full ${store.canOrderNow ? "bg-[#067647]" : "bg-[#8B9BAB]"}`}/>{message}</span>; }
