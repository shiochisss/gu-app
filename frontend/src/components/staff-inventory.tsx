"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { components } from "@/types/api";
import { useApi } from "./runtime";
import { Pager, useMutation } from "./staff-common";
import { ErrorPanel, Loading, PageIntro } from "./ui";

type Inventory = components["schemas"]["InventoryInfo"];
type History = components["schemas"]["TransactionList"];
type Result = components["schemas"]["AdjustmentResult"];
function Numbers({ value }: { value: Inventory }) {
  return <div className="my-4 rounded-xl bg-slate-50 p-4 leading-8"><p>{value.productName} / {value.colorName} / {value.size}</p><p className="text-sm">{value.sku}</p><p>帳簿在庫 {value.onHandQuantity} ・ EC確保 {value.reservedQuantity} ・ 販売可能 {value.availableQuantity}</p>{value.shortageRiskQuantity > 0 && <p className="text-amber-800">⚠ 欠品見込み {value.shortageRiskQuantity}点</p>}</div>;
}
export function StaffInventory() {
  const [q, setQ] = useState(""); const [sku, setSku] = useState(""); const [filter, setFilter] = useState("ALL"); const [page, setPage] = useState(1);
  const result = useApi<components["schemas"]["InventoryList"]>(`/api/v1/staff/inventories?${new URLSearchParams({ q, sku, filter, page: String(page) })}`);
  return <><PageIntro eyebrow="INVENTORY" title="在庫一覧"/><div className="grid gap-3 sm:grid-cols-3"><label>商品名<input className="field" value={q} onChange={e => { setQ(e.target.value); setPage(1); }}/></label><label>SKU<input className="field" value={sku} onChange={e => { setSku(e.target.value); setPage(1); }}/></label><label>絞り込み<select className="field" value={filter} onChange={e => { setFilter(e.target.value); setPage(1); }}><option value="ALL">すべて</option><option value="OUT_OF_STOCK">販売可能0</option><option value="SHORTAGE_RISK">欠品見込みあり</option></select></label></div>{result.error && <ErrorPanel error={result.error} retry={result.retry}/ >}{result.loading && <Loading/>}{result.data && <><p className="my-4">{result.data.totalCount}件</p><div className="overflow-x-auto"><table className="w-full min-w-[850px] text-left text-sm"><thead><tr>{["SKU", "商品名", "色 / サイズ", "帳簿在庫", "EC確保", "販売可能", "欠品見込み"].map(label => <th className="px-3 py-4" key={label}>{label}</th>)}</tr></thead><tbody>{result.data.items.map(inv => <tr className="border-t" key={inv.inventoryId}><td className="px-3 py-4"><Link className="text-[#1F4E8C] underline" href={`/staff/inventory/${inv.inventoryId}`}>{inv.sku}</Link></td><td><Link href={`/staff/inventory/${inv.inventoryId}`}>{inv.productName}</Link></td><td>{inv.colorName} / {inv.size}</td><td>{inv.onHandQuantity}</td><td>{inv.reservedQuantity}</td><td>{inv.availableQuantity}</td><td className={inv.shortageRiskQuantity > 0 ? "font-bold text-amber-800" : ""}>{inv.shortageRiskQuantity > 0 ? `⚠ ${inv.shortageRiskQuantity}` : "0"}</td></tr>)}</tbody></table></div><Pager page={page} total={result.data.totalCount} change={setPage}/></>}</>;
}
export function StaffInventoryDetail({ id, adjust = false }: { id: string; adjust?: boolean }) {
  const [page, setPage] = useState(1);
  const result = useApi<History>(`/api/v1/staff/inventories/${id}/transactions?page=${page}`);
  if (result.error) return <ErrorPanel error={result.error} retry={result.retry}/>;
  if (!result.data) return <Loading/>;
  const { inventory, items, totalCount } = result.data;
  return <><Link href="/staff/inventory" className="text-sm underline">在庫一覧へ</Link><PageIntro eyebrow="INVENTORY" title={adjust ? "入荷・在庫調整" : "在庫詳細・履歴"}/><Numbers value={inventory}/>{adjust ? <Adjustment key={`${id}:${inventory.version}`} inventory={inventory} refresh={result.retry}/> : <><Link className="primary" href={`/staff/inventory/${id}/adjust`}>入荷・在庫調整</Link><div className="overflow-x-auto"><table className="my-5 w-full min-w-[900px] text-left text-sm"><thead><tr>{["日時", "種類", "増減", "更新後", "実数", "参照", "理由", "操作者"].map(x => <th className="p-2" key={x}>{x}</th>)}</tr></thead><tbody>{items.map(tx => <tr className="border-t" key={tx.transactionId}><td className="p-2">{new Date(tx.occurredAt).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}</td><td className="whitespace-nowrap">{tx.typeLabel}</td><td>{tx.quantityDelta > 0 ? "+" : ""}{tx.quantityDelta}</td><td>{tx.onHandAfter}</td><td>{tx.countedQuantity ?? "—"}</td><td>{tx.referenceLabel ?? "—"}</td><td>{tx.reason ?? "—"}</td><td>{tx.actorEmail ?? "システム"}</td></tr>)}</tbody></table></div><Pager page={page} total={totalCount} change={setPage}/></>}</>;
}
function Adjustment({ inventory: inv, refresh }: { inventory: Inventory; refresh: () => void }) {
  const [kind, setKind] = useState("RECEIVE"); const [quantity, setQuantity] = useState(1); const [reason, setReason] = useState("");
  const mutation = useMutation(); const router = useRouter();
  const after = kind === "STOCKTAKE" ? quantity : inv.onHandQuantity + (kind === "DAMAGE" ? -quantity : quantity);
  const required = kind === "DAMAGE" || (kind === "STOCKTAKE" && after !== inv.onHandQuantity);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = { version: inv.version, reason: reason.trim() || null, ...(kind === "RECEIVE" ? { quantity } : kind === "DAMAGE" ? { type: kind, quantity } : { type: kind, countedQuantity: quantity }) };
    const result = await mutation.send<Result>(`/api/v1/staff/inventories/${inv.inventoryId}/${kind === "RECEIVE" ? "receipts" : "adjustments"}`, body);
    if (result) { if (result.shortageRiskOrderCount > 0) window.alert(`欠品見込みの注文が${result.shortageRiskOrderCount}件あります`); router.push(`/staff/inventory/${inv.inventoryId}`); }
  }
  return <form onSubmit={submit} className="max-w-xl space-y-5"><fieldset disabled={mutation.pending} className="space-y-5"><label className="block">種類<select className="field" value={kind} onChange={e => setKind(e.target.value)}><option value="RECEIVE">入荷</option><option value="STOCKTAKE">棚卸（実数）</option><option value="DAMAGE">破損・紛失</option></select></label><label className="block">{kind === "STOCKTAKE" ? "数えた数" : "数量"}<input className="field" type="number" required min={kind === "STOCKTAKE" ? 0 : 1} max={kind === "STOCKTAKE" ? 99999 : kind === "RECEIVE" ? 9999 : inv.onHandQuantity} value={quantity} onChange={e => setQuantity(Number(e.target.value))}/></label><label className="block">理由（{required ? "必須" : "任意"}）<input className="field" maxLength={200} required={required} value={reason} onChange={e => setReason(e.target.value)}/></label><p>調整後：帳簿在庫 {after} ・販売可能 {Math.max(0, after - inv.reservedQuantity)}</p>{after < inv.reservedQuantity && <p role="status" className="text-amber-800">EC注文の欠品見込みが発生します（{inv.reservedQuantity - after}点）</p>}<button className="primary">{mutation.pending ? "登録中…" : "登録"}</button></fieldset>{mutation.error && <ErrorPanel error={mutation.error} retry={mutation.error.code === "CONFLICTING_UPDATE" ? refresh : undefined}/ >}</form>;
}
