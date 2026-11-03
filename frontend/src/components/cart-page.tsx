"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import { cartCount, changeQuantity } from "@/lib/cart";
import { formatMoney } from "@/lib/format";
import { updateSnapshot } from "@/lib/store";
import type { ProductDetail, Variant } from "@/lib/types";
import { Icon } from "./icons";
import { useCartStore, useSession } from "./runtime";
import { Empty, ErrorPanel, Loading, PageIntro, ProductImage } from "./ui";

type Line = { productId: string; product: ProductDetail | null; variant: Variant | null };
export function CartPage() {
  const { cart, selectedStoreId, storageNotice } = useCartStore(); const { stores } = useSession();
  const [revision, setRevision] = useState(0); const [error, setError] = useState<string | null>(null);
  const lookup = `${cart.storeId}:${[...new Set(cart.items.map(value => value.productId))].sort().join(",")}:${revision}`;
  const [loaded, setLoaded] = useState<{ key: string; lines: Line[]; error: ApiError | null }>({ key: "", lines: [], error: null });
  useEffect(() => {
    let active = true;
    const ids = [...new Set(cart.items.map(value => value.productId))];
    if (!cart.storeId || !ids.length) return;
    Promise.all(ids.map(async productId => {
      try { const product = await apiFetch<ProductDetail>(`/api/v1/stores/${cart.storeId}/products/${productId}`); return { productId, product }; }
      catch (failure) { if (failure instanceof ApiError && failure.status === 404) return { productId, product: null }; throw failure; }
    })).then(values => { if (active) setLoaded({ key: lookup, error: null, lines: values.map(value => ({ ...value, variant: null })) }); }).catch(failure => { if (active) setLoaded({ key: lookup, lines: [], error: failure }); });
    return () => { active = false; };
  // Cart quantities do not affect the product lookup; every initial visit fetches current values.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lookup]);
  const store = stores.data?.items.find(value => value.storeId === cart.storeId);
  const itemCount = cartCount(cart); const loading = !!cart.items.length && loaded.key !== lookup;
  const lines = cart.items.map(item => { const product = loaded.lines.find(value => value.productId === item.productId)?.product; return { ...item, product, variant: product?.variants.find(value => value.productVariantId === item.productVariantId) }; });
  const total = lines.reduce((sum, item) => sum + (item.variant?.priceYen ?? 0) * item.quantity, 0);
  function quantity(id: string, value: number, max: number) { try { updateSnapshot({ cart: changeQuantity(cart, id, value, max) }); setError(null); } catch (failure) { setError((failure as Error).message); } }
  const home = selectedStoreId ? `/stores/${selectedStoreId}/products` : "/";
  return <>
    <PageIntro eyebrow="YOUR CART" title="カート">{store?.name ? `${store.name}でお受け取り` : "気になる商品をカートに追加してください。"}</PageIntro>
    {storageNotice && <p role="alert" className="mb-5 text-sm leading-6 text-[#B54708]">{storageNotice}</p>}
    {!cart.items.length ? <Empty><div className="mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-white"><Icon name="bag" className="size-7 text-[#8B9BAB]"/></div><p>カートに商品が入っていません。</p><Link href={home} className="primary mt-6">商品を探す<Icon name="arrow" className="size-4"/></Link></Empty> : loading ? <Loading label="カートの商品を確認しています"/> : loaded.error ? <ErrorPanel error={loaded.error} retry={() => setRevision(value => value + 1)}/> : <>
      <div className="divide-y divide-[#E7EDF3]">{lines.map(item => { const unavailable = !item.variant || item.quantity > item.variant.maxSelectableQuantity; return <article key={item.productVariantId} className="flex gap-4 py-5 first:pt-0"><div className="w-24 shrink-0"><ProductImage name={item.product?.name ?? "商品"} color={item.product?.imageColor ?? "#E8EDF3"}/></div><div className="min-w-0 flex-1"><Link href={`/stores/${cart.storeId}/products/${item.productId}`} className="text-sm font-semibold leading-6">{item.product?.name ?? "現在ご利用いただけない商品です"}</Link>{item.variant && <><p className="mt-1 text-xs text-[#627589]">{item.variant.colorName} / {item.variant.size}</p><p className="mt-2 text-sm font-bold">{formatMoney(item.variant.priceYen)}</p></>}
      {unavailable && <p className="mt-2 text-xs text-[#B42318]">在庫が足りません（残り{item.variant?.maxSelectableQuantity ?? 0}点）</p>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2"><div className="flex overflow-hidden rounded-lg border border-[#D9E2EC]"><button aria-label={`${item.product?.name ?? "商品"}を1点減らす`} disabled={item.quantity <= 1} className="min-h-11 min-w-10 bg-[#F8FAFC] disabled:text-[#AAB6C3]" onClick={() => quantity(item.productVariantId, item.quantity - 1, item.variant?.maxSelectableQuantity ?? 0)}>−</button><span className="flex min-w-9 items-center justify-center text-sm">{item.quantity}</span><button aria-label={`${item.product?.name ?? "商品"}を1点増やす`} disabled={item.quantity >= (item.variant?.maxSelectableQuantity ?? 0) || itemCount >= 10} className="min-h-11 min-w-10 bg-[#F8FAFC] disabled:text-[#AAB6C3]" onClick={() => quantity(item.productVariantId, item.quantity + 1, item.variant?.maxSelectableQuantity ?? 0)}>＋</button></div><button onClick={() => updateSnapshot({ cart: { ...cart, items: cart.items.filter(value => value.productVariantId !== item.productVariantId) } })} className="min-h-11 px-1 text-xs text-[#627589] underline underline-offset-4">削除</button></div><p className="mt-2 text-right text-xs text-[#627589]">小計 <strong className="ml-1 text-sm text-[#1F2933]">{item.variant ? formatMoney(item.variant.priceYen * item.quantity) : "—"}</strong></p></div></article>; })}</div>
      {error && <p role="alert" className="mt-3 text-sm text-[#B42318]">{error}</p>}
      <div className="mt-5 rounded-xl bg-[#F5F7FA] p-5"><div className="flex justify-between text-sm"><span>合計{itemCount}点<span className="ml-1 text-xs text-[#627589]">（上限10点）</span></span><strong className="text-xl">{formatMoney(total)}</strong></div><p className="mt-3 text-[11px] leading-6 text-[#627589]">金額は注文確認画面で確定します。</p></div>
      <Link className="primary mt-5 w-full" href="/checkout">注文手続きへ</Link><Link href={home} className="secondary mt-4 w-full">お買い物を続ける</Link>
    </>}
  </>;
}
