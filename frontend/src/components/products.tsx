"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { formatMoney, formatTime } from "@/lib/format";
import { updateSnapshot } from "@/lib/store";
import type { ProductList } from "@/lib/types";
import { Icon } from "./icons";
import { useApi, useCartStore, useSession } from "./runtime";
import { Empty, ErrorPanel, Loading, ProductImage, StoreStatus } from "./ui";

const categories = [["TOPS", "トップス"], ["BOTTOMS", "ボトムス"], ["OUTER", "アウター"], ["DRESS", "ワンピース"], ["INNER", "インナー"], ["ACCESSORY", "小物"]];
export function Products({ storeId }: { storeId: string }) {
  const { stores } = useSession(); const state = useCartStore();
  const store = stores.data?.items.find(value => value.storeId === storeId);
  const [input, setInput] = useState(""); const [query, setQuery] = useState(""); const [category, setCategory] = useState(""); const [color, setColor] = useState(""); const [size, setSize] = useState(""); const [sort, setSort] = useState("new"); const [page, setPage] = useState(1);
  const [previous, setPrevious] = useState<ProductList["items"]>([]);
  useEffect(() => { const timer = setTimeout(() => { setQuery(input.trim()); setPage(1); setPrevious([]); }, 300); return () => clearTimeout(timer); }, [input]);
  const params = new URLSearchParams({ page: String(page), pageSize: "12", sort });
  if (query) params.set("q", query); if (category) params.set("category", category); if (color) params.set("color", color); if (size) params.set("size", size);
  const api = useApi<ProductList>(`/api/v1/stores/${storeId}/products?${params}`);
  function filter(setter: (value: string) => void, value: string) { setter(value); setPage(1); setPrevious([]); }
  function more() { if (api.data) setPrevious([...previous, ...api.data.items]); setPage(value => value + 1); }
  const products = [...previous, ...(api.data?.items ?? [])];
  return <>
    <Link href="/" className="mb-4 inline-flex min-h-11 items-center gap-1 text-xs text-[#627589]"><Icon name="back" className="size-4"/>受取店舗を変更</Link>
    <div className="mb-5"><p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-[#1F4E8C]">PICK UP AT YOUR STORE</p><h1 className="text-xl font-bold">{store?.name ?? "商品を探す"}</h1>{store && <div className="mt-3 flex flex-wrap items-center gap-2"><StoreStatus store={store}/>{store.earliestReadyAt && <span className="text-[11px] text-[#627589]">最短予定 <strong className="text-[#1F4E8C]">{formatTime(store.earliestReadyAt)}</strong></span>}</div>}</div>
    <div className="relative mb-3"><Icon name="search" className="absolute left-3.5 top-3.5 size-5 text-[#627589]"/><input aria-label="商品名で検索" placeholder="商品名で検索" maxLength={100} value={input} onChange={event => setInput(event.target.value)} className="field pl-11"/>{input && <button aria-label="検索をクリア" className="absolute right-0 top-0 flex size-12 items-center justify-center text-[#627589]" onClick={() => setInput("")}><Icon name="close" className="size-4"/></button>}</div>
    <div className="mb-5 grid grid-cols-3 gap-2">
      <select aria-label="カテゴリ" className="field min-w-0 px-2 text-xs" value={category} onChange={event => filter(setCategory, event.target.value)}><option value="">カテゴリ</option>{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <select aria-label="色" className="field min-w-0 px-2 text-xs" value={color} onChange={event => filter(setColor, event.target.value)}><option value="">カラー</option>{["ホワイト", "ブラック", "ネイビー", "ベージュ", "グレー"].map(value => <option key={value}>{value}</option>)}</select>
      <select aria-label="サイズ" className="field min-w-0 px-2 text-xs" value={size} onChange={event => filter(setSize, event.target.value)}><option value="">サイズ</option>{["XS", "S", "M", "L", "XL", "FREE"].map(value => <option key={value}>{value}</option>)}</select>
    </div>
    <div className="mb-4 flex items-center justify-between border-t border-[#E7EDF3] pt-4"><p className="text-xs text-[#627589]">{api.data ? <><strong className="text-base text-[#1F2933]">{api.data.totalCount}</strong> 件の商品</> : "商品を確認しています"}</p><select aria-label="並び順" value={sort} onChange={event => filter(setSort, event.target.value)} className="min-h-11 max-w-[180px] bg-white pl-2 text-xs font-medium"><option value="new">新着順</option><option value="price_asc">価格の安い順</option><option value="price_desc">価格の高い順</option></select></div>
    {api.error ? <ErrorPanel error={api.error} retry={api.retry}/> : api.loading && !previous.length ? <Loading label="商品を読み込んでいます"/> : products.length === 0 ? <Empty>条件に合う在庫のある商品はありません。<button className="secondary mt-5" onClick={() => { setInput(""); setQuery(""); setCategory(""); setColor(""); setSize(""); setPage(1); }}>条件をクリア</button></Empty> : <>
      <div className="grid grid-cols-2 gap-x-4 gap-y-7">{products.map(product => <Link key={product.productId} href={`/stores/${storeId}/products/${product.productId}`} className="group block" onClick={() => { if (!state.cart.items.length || state.cart.storeId === storeId) updateSnapshot({ selectedStoreId: storeId }); }}><ProductImage name={product.name} color={product.imageColor}/><p className="mb-1 mt-3 text-[10px] text-[#627589]">{product.categoryLabel}</p><h2 className="min-h-10 text-[13px] font-semibold leading-5 group-hover:text-[#1F4E8C]">{product.name}</h2><p className="mt-1 text-base font-bold tracking-tight">{formatMoney(product.priceYen)}<span className="ml-1 text-[10px] font-normal text-[#627589]">税込</span></p><div className="mt-2 flex items-center gap-1.5">{product.colors.map(value => <span key={value.name} title={value.name} className="size-3 rounded-full border border-black/10" style={{ backgroundColor: value.hex }}/>)}</div><p className="mt-2 text-[10px] tracking-wide text-[#627589]">{product.availableSizes.join(" / ")}</p></Link>)}</div>
      {api.data && products.length < api.data.totalCount && <button className="secondary mt-8 w-full" disabled={api.loading} onClick={more}>{api.loading ? "読み込み中…" : "もっと見る"}</button>}
    </>}
  </>;
}
