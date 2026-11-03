"use client";
import Link from "next/link";
import { useState } from "react";
import { addCartItem, changeStore } from "@/lib/cart";
import { formatMoney } from "@/lib/format";
import { updateSnapshot } from "@/lib/store";
import type { ProductDetail as Detail } from "@/lib/types";
import { Icon } from "./icons";
import { useApi, useCartStore } from "./runtime";
import { ErrorPanel, Loading, ProductImage } from "./ui";

export function ProductDetail({ storeId, productId }: { storeId: string; productId: string }) {
  const api = useApi<Detail>(`/api/v1/stores/${storeId}/products/${productId}`);
  const { cart } = useCartStore(); const [color, setColor] = useState<string | null>(null); const [size, setSize] = useState<string | null>(null); const [quantity, setQuantity] = useState(1); const [message, setMessage] = useState<string | null>(null); const [added, setAdded] = useState(false);
  if (api.loading) return <Loading label="商品詳細を読み込んでいます"/>;
  if (api.error) return <ErrorPanel error={api.error} retry={api.retry}/>;
  if (!api.data) return null;
  const product = api.data;
  const colors = [...new Map(product.variants.map(value => [value.colorName, { name: value.colorName, hex: value.colorHex }])).values()];
  const sizes = [...new Set(product.variants.map(value => value.size))];
  const selected = product.variants.find(value => value.colorName === color && value.size === size);
  const price = selected?.priceYen ?? Math.min(...product.variants.map(value => value.priceYen));
  function add() {
    if (!selected) { setMessage("色とサイズを選んでください"); setAdded(false); return; }
    let current = cart;
    if (cart.items.length > 0 && cart.storeId !== storeId) {
      if (!window.confirm("店舗を変更するとカートが空になります。よろしいですか？")) return;
      current = changeStore(cart, storeId, true);
    }
    try {
      updateSnapshot({ selectedStoreId: storeId, storageNotice: null, cart: addCartItem(current, storeId, { productId, productVariantId: selected.productVariantId, quantity }, selected.maxSelectableQuantity) });
      setMessage("カートに追加しました"); setAdded(true);
    } catch (error) { setAdded(false); setMessage((error as Error).message); }
  }
  return <>
    <Link href={`/stores/${storeId}/products`} className="mb-4 inline-flex min-h-11 items-center gap-1 text-xs text-[#627589]"><Icon name="back" className="size-4"/>商品一覧に戻る</Link>
    <ProductImage name={product.name} color={colors.find(value => value.name === color)?.hex ?? product.imageColor} large/>
    <div className="mb-6 mt-6"><p className="mb-2 text-xs text-[#627589]">{product.categoryLabel}</p><h1 className="text-xl font-bold leading-8">{product.name}</h1><p className="mt-3 text-[26px] font-bold tracking-tight">{formatMoney(price)}<span className="ml-2 text-xs font-normal text-[#627589]">税込</span></p><p className="mt-4 text-sm leading-7 text-[#627589]">{product.description}</p></div>
    <fieldset className="mb-6 border-t border-[#E7EDF3] pt-5"><legend className="pt-5 text-sm font-bold">カラー <span className="ml-2 text-xs font-normal text-[#627589]">{color ?? "選択してください"}</span></legend><div className="mt-3 flex flex-wrap gap-3">{colors.map(value => <button key={value.name} aria-pressed={color === value.name} onClick={() => { setColor(value.name); setSize(null); setQuantity(1); setMessage(null); setAdded(false); }} className={`flex min-h-12 items-center gap-2 rounded-lg border px-3 text-xs ${color === value.name ? "border-[#1F4E8C] bg-[#F0F5FC] font-bold" : "border-[#D9E2EC]"}`}><span className="size-5 rounded-full border border-black/10" style={{ backgroundColor: value.hex }}/>{value.name}</button>)}</div></fieldset>
    <fieldset className="mb-6"><legend className="text-sm font-bold">サイズ <span className="ml-2 text-xs font-normal text-[#627589]">{size ?? "選択してください"}</span></legend><div className="mt-3 grid grid-cols-4 gap-2">{sizes.map(value => { const variant = product.variants.find(item => item.colorName === color && item.size === value); const unavailable = !!color && (!variant || !variant.inStock); return <button key={value} disabled={!color || unavailable} aria-pressed={size === value} onClick={() => { setSize(value); setQuantity(1); setMessage(null); setAdded(false); }} className={`min-h-14 rounded-lg border text-sm font-semibold ${size === value ? "border-[#1F4E8C] bg-[#F0F5FC] text-[#1F4E8C]" : "border-[#D9E2EC]"} disabled:bg-[#F5F7FA] disabled:text-[#8B9BAB]`}>{value}{unavailable && <span className="mt-0.5 block text-[9px] font-normal">在庫なし</span>}</button>; })}</div>{!color && <p className="mt-2 text-xs text-[#627589]">先にカラーを選択してください。</p>}</fieldset>
    <div className="mb-6 flex items-center justify-between"><label htmlFor="quantity" className="text-sm font-bold">数量</label><select id="quantity" className="field max-w-[110px]" disabled={!selected?.inStock} value={quantity} onChange={event => setQuantity(Number(event.target.value))}>{Array.from({ length: selected?.maxSelectableQuantity || 1 }, (_, index) => <option key={index + 1}>{index + 1}</option>)}</select></div>
    {message && <p role={added ? "status" : "alert"} className={`mb-4 rounded-lg px-4 py-3 text-sm ${added ? "bg-[#EAF6F0] text-[#067647]" : "bg-[#FFF2F0] text-[#B42318]"}`}>{message}</p>}
    <button onClick={add} className="primary w-full"><Icon name="bag" className="size-5"/>カートに入れる</button>
    {added && <Link href="/cart" className="secondary mt-3 w-full">カートを見る<Icon name="arrow" className="size-4"/></Link>}
    <p className="mt-4 text-center text-[11px] leading-6 text-[#627589]">1回の注文は合計10点までです。<br/>価格と在庫は注文時にあらためて確認します。</p>
  </>;
}
