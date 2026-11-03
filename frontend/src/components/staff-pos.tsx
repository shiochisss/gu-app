"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { components } from "@/types/api";
import { apiFetch, ApiError } from "@/lib/api";
import { useApi } from "./runtime";
import { Pager, useMutation } from "./staff-common";
import { ErrorPanel, Loading, PageIntro } from "./ui";

type Product = components["schemas"]["StaffProduct"];
type Quote = components["schemas"]["PosEstimate"];
type Sale = components["schemas"]["SaleDetail"];
type Item = { productVariantId: string; quantity: number };
const yen = (value: number) => `${value.toLocaleString("ja-JP")}円`;
export function StaffPos() {
  const [sku, setSku] = useState(""); const [q, setQ] = useState(""); const [search, setSearch] = useState(""); const [page, setPage] = useState(1);
  const products = useApi<components["schemas"]["StaffProductList"]>(search ? `/api/v1/staff/products?${search}&page=${page}` : null);
  const [items, setItems] = useState<Item[]>([]); const [method, setMethod] = useState("CASH");
  const [revision, setRevision] = useState(0);
  const signature = JSON.stringify(items) + revision;
  const [quote, setQuote] = useState<{ key: string; value: Quote } | null>(null);
  const [quoteError, setQuoteError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState(""); const mutation = useMutation();
  useEffect(() => {
    if (!items.length) return;
    let active = true;
    apiFetch<Quote>("/api/v1/staff/pos/sales/estimate", { method: "POST", body: { items } }).then(value => { if (active) { setQuote({ key: signature, value }); setQuoteError(null); } }).catch(error => { if (active) { setQuoteError(error); setQuote(null); } });
    return () => { active = false; };
  }, [items, signature]);
  const current = quote?.key === signature ? quote.value : null;
  function add(product: Product) {
    setItems(previous => { const found = previous.find(x => x.productVariantId === product.productVariantId); return found ? previous.map(x => x === found ? { ...x, quantity: Math.min(99, x.quantity + 1) } : x) : [...previous, { productVariantId: product.productVariantId, quantity: 1 }]; });
  }
  async function scan(e: React.FormEvent) {
    e.preventDefault();
    try { const result = await apiFetch<components["schemas"]["StaffProductList"]>(`/api/v1/staff/products?sku=${encodeURIComponent(sku.trim().toUpperCase())}`); if (result.items.length === 1) { add(result.items[0]); setSku(""); setMessage(""); } else setMessage("商品が見つかりません"); } catch (error) { setMessage((error as Error).message); }
  }
  function accepted(result: components["schemas"]["SaleInfo"] | undefined) {
    if (result) { setItems([]); setMessage(`売上を登録しました（${result.saleNumber}）`); }
  }
  async function confirmSale() {
    if (!current?.allOk || !window.confirm(`合計${yen(current.totalAmountYen)}の売上を登録しますか？`)) return;
    const result = await mutation.send<components["schemas"]["SaleInfo"]>("/api/v1/staff/pos/sales", { items, clientTotalAmountYen: current.totalAmountYen, paymentMethod: method });
    if (result) accepted(result);
    else setRevision(x => x + 1);
  }
  return <><PageIntro eyebrow="POS" title="簡易POS"/><Link href="/staff/pos/sales" className="underline">売上履歴へ</Link>{message && <p role="status" className="my-4">{message}</p>}<fieldset disabled={mutation.pending} className="space-y-5"><form onSubmit={scan} className="flex items-end gap-3"><label className="flex-1">商品コード<input className="field" value={sku} maxLength={32} required onChange={e => setSku(e.target.value.toUpperCase())}/></label><button className="secondary">追加</button></form><form onSubmit={e => { e.preventDefault(); setSearch(new URLSearchParams({ q }).toString()); setPage(1); }} className="flex items-end gap-3"><label className="flex-1">商品名検索<input className="field" required maxLength={100} value={q} onChange={e => setQ(e.target.value)}/></label><button className="secondary">検索</button></form>{products.error && <ErrorPanel error={products.error} retry={products.retry}/ >}{products.loading && <Loading/>}{products.data && <><div className="grid gap-2 sm:grid-cols-2">{products.data.items.map(product => <button type="button" key={product.productVariantId} className="rounded-lg border p-3 text-left" onClick={() => add(product)}>{product.productName} / {product.colorName} / {product.size}<br/><small>{product.sku} ・{yen(product.priceYen)} ・販売可能 {product.availableQuantity}</small></button>)}</div>{!products.data.totalCount && <p>商品が見つかりません</p>}<Pager page={page} total={products.data.totalCount} change={setPage}/></>}
    {items.length > 0 && !current && !quoteError && <Loading label="金額を計算中"/>}{quoteError && <ErrorPanel error={quoteError} retry={() => setRevision(x => x + 1)}/ >}
    {items.map(item => { const line = current?.lines.find(x => x.productVariantId === item.productVariantId); return <div key={item.productVariantId} className="rounded-lg border p-4"><p className="font-bold">{line?.productName ?? "商品を確認中"}</p>{line && <p>{line.sku} ・{line.colorName} / {line.size} ・単価{yen(line.unitPriceYen)} ・小計{yen(line.lineAmountYen)}</p>}<div className="my-3 flex gap-4"><label>数量<input aria-label={`${line?.sku ?? item.productVariantId}の数量`} className="field w-24" type="number" min={1} max={99} value={item.quantity} onChange={e => { const value = Number(e.target.value); if (Number.isInteger(value) && value >= 1 && value <= 99) setItems(previous => previous.map(x => x === item ? { ...x, quantity: value } : x)); }}/></label><button type="button" onClick={() => setItems(previous => previous.filter(x => x !== item))}>削除</button></div>{line && !line.ok && <p role="alert" className="text-red-700">{line.reasonCode === "RESERVED_FOR_EC" ? `販売できません：EC注文で確保中（販売可能 ${line.availableQuantity}点）` : "在庫不足"}</p>}</div>; })}
    {current && <p className="text-xl font-bold">合計 {current.totalQuantity}点 ・{yen(current.totalAmountYen)}</p>}<label className="block">支払区分<select className="field" value={method} onChange={e => setMethod(e.target.value)}><option value="CASH">現金</option><option value="CARD">カード</option><option value="OTHER">その他</option></select></label><div className="flex gap-4"><button type="button" className="primary" disabled={!items.length || !current?.allOk || mutation.pending} onClick={() => void confirmSale()}>{mutation.pending ? "登録中…" : "売上確定"}</button><button type="button" className="secondary" onClick={() => setItems([])}>クリア</button></div></fieldset>{mutation.error && <ErrorPanel error={mutation.error} retry={mutation.error.status === 0 || mutation.error.status >= 500 || mutation.error.code === "IDEMPOTENCY_IN_PROGRESS" ? () => void mutation.retry<components["schemas"]["SaleInfo"]>().then(accepted) : undefined}/ >}</>;
}
export function StaffSales() {
  const [date, setDate] = useState(() => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date())); const [page, setPage] = useState(1);
  const result = useApi<components["schemas"]["SaleList"]>(`/api/v1/staff/pos/sales?date=${date}&page=${page}`);
  return <><PageIntro eyebrow="SALES" title="POS売上履歴"/><Link className="underline" href="/staff/pos">POSへ</Link><label className="my-5 block">日付<input type="date" className="field max-w-xs" required value={date} onChange={e => { if (e.target.value) { setDate(e.target.value); setPage(1); } }}/></label>{result.error && <ErrorPanel error={result.error} retry={result.retry}/ >}{result.loading && <Loading/>}{result.data && <><p className="my-5">売上 {result.data.summary.completedCount}件 ・{yen(result.data.summary.completedAmountYen)} ・取消 {result.data.summary.voidedCount}件</p>{result.data.items.map(sale => <SaleRow key={`${sale.saleId}:${sale.version}`} sale={sale} refresh={result.retry}/>)}<Pager page={page} total={result.data.totalCount} change={setPage}/></>}</>;
}
function SaleRow({ sale, refresh }: { sale: Sale; refresh: () => void }) {
  const [reason, setReason] = useState(""); const mutation = useMutation();
  return <article className="my-4 rounded-xl border p-5"><h2 className="font-bold">{sale.saleNumber} ・{sale.status === "VOIDED" ? "取消済み" : "売上確定"}</h2><p>{new Date(sale.soldAt).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })} ・{sale.totalQuantity}点 ・{yen(sale.totalAmountYen)} ・{({ CASH: "現金", CARD: "カード", OTHER: "その他" } as Record<string, string>)[sale.paymentMethod]}</p><p className="break-all text-sm">{sale.staffEmail}</p>{sale.voidedAt && <p>取消：{new Date(sale.voidedAt).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })} / {sale.voidReason}</p>}<details className="my-3"><summary>明細</summary>{sale.lines.map(line => <p key={line.productVariantId} className="py-2">{line.productName} / {line.sku} / {line.colorName} / {line.size} ・{line.quantity}点 ・{yen(line.lineAmountYen)}</p>)}</details>{sale.canVoid && <form onSubmit={e => { e.preventDefault(); if (window.confirm(`${sale.saleNumber}を取り消しますか？`)) void mutation.send(`/api/v1/staff/pos/sales/${sale.saleId}/void`, { reason: reason.trim(), version: sale.version }).then(value => { if (value) refresh(); }); }}><fieldset disabled={mutation.pending} className="flex items-end gap-3"><label className="flex-1">取消理由<input className="field" required maxLength={200} value={reason} onChange={e => setReason(e.target.value)}/></label><button className="secondary" disabled={!reason.trim()}>取消</button></fieldset></form>}{mutation.error && <ErrorPanel error={mutation.error} retry={refresh}/ >}</article>;
}
