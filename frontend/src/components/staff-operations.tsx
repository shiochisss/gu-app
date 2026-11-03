"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { components } from "@/types/api";
import { apiFetch } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { useApi } from "./runtime";
import { Pager, useMutation } from "./staff-common";
import { Empty, ErrorPanel, Loading, PageIntro } from "./ui";

type Detail = components["schemas"]["StaffOrderDetail"];
type Store = components["schemas"]["StaffStore"];
const tabs = { ACTIVE:"受付中", DELAYED:"遅延", ACTION_REQUIRED:"要対応", READY:"受取待ち", EXPIRED:"期限切れ", DONE:"完了" };
export function StaffOrders() {
  const [tab, setTab] = useState("ACTIVE"); const [page, setPage] = useState(1);
  const result = useApi<components["schemas"]["StaffOrderList"]>(`/api/v1/staff/orders?tab=${tab}&page=${page}`);
  const store = useApi<Store>("/api/v1/staff/store");
  useEffect(() => { const timer = setInterval(() => { result.retry(); store.retry(); }, 30000); return () => clearInterval(timer); // The API hooks expose stable retry callbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.retry, store.retry]);
  return <><PageIntro eyebrow="ORDERS" title="店舗の注文"/>{store.data && <Acceptance store={store.data} refresh={store.retry}/>}<div className="my-6 flex flex-wrap gap-2" role="tablist" aria-label="注文の状態">{Object.entries(tabs).map(([value,label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? "primary" : "secondary"} onClick={() => { setTab(value); setPage(1); }}>{label} {result.data?.tabCounts[value] ?? ""}</button>)}</div>{result.error && <ErrorPanel error={result.error} retry={result.retry}/ >}{result.loading && <Loading/>}{result.data && <>{!result.data.items.length && <Empty>該当する注文はありません</Empty>}{result.data.items.map((order,index) => <Link className="my-4 block rounded-xl border p-5 leading-8" key={order.orderId} href={`/staff/orders/${order.orderId}`}>{tab === "ACTIVE" && order.status === "RECEIVED" && result.data!.items.findIndex(x => x.status === "RECEIVED") === index && <p className="font-bold text-[#1F4E8C]">次はこの注文</p>}<p className="font-bold">{order.orderNumber} ・{order.statusLabel} ・{order.totalQuantity}点</p><p>受付 {formatDateTime(order.acceptedAt)}</p><p className={order.isDelayed ? "text-red-700" : ""}>{order.isDelayed ? "遅延：" : "準備完了予定："}{order.currentReadyAt ? formatDateTime(order.currentReadyAt) : "確認中"}</p>{order.shortageRisk && <p className="text-amber-800">⚠ 欠品見込み</p>}{order.pickupDeadlineAt && <p>受取期限：{formatDateTime(order.pickupDeadlineAt)}</p>}</Link>)}<Pager page={page} total={result.data.totalCount} change={setPage}/></>}</>;
}
export function StaffOrder({ id, mode = "detail" }: { id: string; mode?: "detail" | "shortage" | "delay" }) {
  const result = useApi<Detail>(`/api/v1/staff/orders/${id}`); const mutation = useMutation(); const [notice, setNotice] = useState("");
  useEffect(() => { if (mode !== "detail") return; const timer = setInterval(result.retry, 30000); return () => clearInterval(timer); }, [result.retry, mode]);
  if (result.error) return <ErrorPanel error={result.error} retry={result.retry}/>;
  if (!result.data) return <Loading/>;
  const order = result.data;
  const amount = order.items.reduce((sum,item) => sum + item.unitPriceYen * (item.orderedQuantity - item.shortageQuantity),0);
  async function action(name: string) {
    if (name === "ready" && !window.confirm(`確定額 ${formatMoney(amount)}で準備完了にしますか？`)) return;
    if (name === "return-to-stock" && !window.confirm("商品を棚に戻しましたか？")) return;
    const value = await mutation.send<Detail>(`/api/v1/staff/orders/${id}/${name}`, { version:order.version });
    if (value) { setNotice(value.status === "ACTION_REQUIRED" ? "決済確定ができませんでした。時間をおいて再実行してください" : "更新しました"); result.retry(); }
  }
  return <><Link className="underline" href="/staff/orders">注文一覧へ</Link><PageIntro eyebrow={order.orderNumber} title={mode === "shortage" ? "欠品登録" : mode === "delay" ? "遅延登録" : order.statusLabel}/>{notice && <p role="status" className="my-4">{notice}</p>}{order.status === "ACTION_REQUIRED" && !notice && <p role="alert" className="my-4 text-red-700">決済確定ができませんでした。時間をおいて再実行してください</p>}<div className="my-5 rounded-xl bg-slate-50 p-5 leading-8"><p>受付：{formatDateTime(order.acceptedAt)}</p><p>当初予定：{formatDateTime(order.originalReadyAt)}</p><p>新予定：{formatDateTime(order.updatedReadyAt)}</p><p>欠品時：{order.shortagePolicy === "CANCEL_ALL" ? "全体キャンセル" : "用意できた分だけ購入"}</p><p>{order.paymentStatusLabel} ・確定額 {formatMoney(order.payment.capturedAmountYen)}</p></div>{mode === "detail" ? <>{order.items.map(item => <div className="border-b py-4" key={item.orderItemId}><p>{item.productName} / {item.colorName} / {item.size}</p><p className="text-sm">{item.sku} ・注文 {item.orderedQuantity}点 ・欠品 {item.shortageQuantity}点 ・帳簿在庫 {item.onHandQuantity}点</p>{item.shortageRiskQuantity > 0 && <p className="text-amber-800">⚠ 欠品見込み {item.shortageRiskQuantity}点</p>}</div>)}<div className="my-5 flex flex-wrap gap-3">{order.allowedActions.includes("START_PREPARATION") && <button className="primary" disabled={mutation.pending} onClick={() => void action("preparation/start")}>準備開始</button>}{order.allowedActions.includes("REGISTER_SHORTAGE") && <Link className="secondary" href={`/staff/orders/${id}/shortage`}>欠品を登録</Link>}{order.allowedActions.includes("REGISTER_DELAY") && <Link className="secondary" href={`/staff/orders/${id}/delay`}>遅延を登録</Link>}{order.allowedActions.includes("MARK_READY") && <button className="primary" disabled={mutation.pending} onClick={() => void action("ready")}>準備完了（決済確定）</button>}{order.allowedActions.includes("RETURN_TO_STOCK") && <button className="primary" disabled={mutation.pending} onClick={() => void action("return-to-stock")}>棚に戻した</button>}</div>{order.delays.map((delay,index) => <p className="my-3 text-sm" key={index}>{formatDateTime(delay.registeredAt)} ・{delay.reasonText} ・{delay.newReadyAt ? formatDateTime(delay.newReadyAt) : "確認中"}</p>)}</> : <OrderForm key={`${order.version}:${mode}`} order={order} mode={mode}/ >}{mutation.error && <ErrorPanel error={mutation.error.code === "INSUFFICIENT_STOCK" ? new Error("帳簿在庫が足りない商品があります。欠品を登録してください") : mutation.error} retry={result.retry}/ >}{mutation.error?.code === "INSUFFICIENT_STOCK" && Array.isArray(mutation.error.details?.items) && (mutation.error.details.items as {orderItemId:string;onHandQuantity:number;requiredQuantity:number}[]).map(item => <p className="my-2 text-sm text-red-700" key={item.orderItemId}>{order.items.find(value => value.orderItemId === item.orderItemId)?.productName}：帳簿在庫 {item.onHandQuantity}点／必要 {item.requiredQuantity}点</p>)}</>;
}
function OrderForm({ order, mode }: { order: Detail; mode: "shortage" | "delay" }) {
  const router = useRouter(); const mutation = useMutation();
  const [quantities,setQuantities] = useState<Record<string,number>>(() => Object.fromEntries(order.items.map(x => [x.orderItemId,x.shortageQuantity])));
  const [reasonCode,setReasonCode] = useState("CONGESTION"); const [reasonText,setReasonText] = useState(""); const [unknown,setUnknown] = useState(true); const [readyTime,setReadyTime] = useState("");
  const amount = order.items.reduce((sum,x) => sum + x.unitPriceYen*(x.orderedQuantity-quantities[x.orderItemId]),0);
  const cancelling = order.items.every(x => quantities[x.orderItemId] === x.orderedQuantity) || (order.shortagePolicy === "CANCEL_ALL" && order.items.some(x => quantities[x.orderItemId]>0));
  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = mode === "shortage" ? { version:order.version, items:order.items.map(x => ({ orderItemId:x.orderItemId, shortageQuantity:quantities[x.orderItemId] })) } : { version:order.version, reasonCode, reasonText:reasonText.trim() || null, updatedReadyAt:unknown ? null : readyTime ? `${readyTime}:00+09:00` : null };
    const value = await mutation.send(`/api/v1/staff/orders/${order.orderId}/${mode === "shortage" ? "shortages" : "delay"}`, body);
    if (value) router.push(`/staff/orders/${order.orderId}`);
  }
  return <form onSubmit={submit} className="space-y-5"><fieldset disabled={mutation.pending} className="space-y-5">{mode === "shortage" ? <>{order.items.map(item => <label className="block" key={item.orderItemId}>{item.productName} / {item.colorName} / {item.size}（注文 {item.orderedQuantity}点）<input className="field" type="number" min={item.shortageQuantity} max={item.orderedQuantity} required value={quantities[item.orderItemId]} onChange={e => setQuantities(previous => ({...previous,[item.orderItemId]:Number(e.target.value)}))}/></label>)}<p className="font-bold">{cancelling ? "この注文は取り消されます" : `変更後の金額 ${formatMoney(amount)}`}</p></> : <><label className="block">理由<select className="field" value={reasonCode} onChange={e => setReasonCode(e.target.value)}><option value="STAFF_SHORTAGE">人手不足</option><option value="CONGESTION">混雑</option><option value="STOCK_CHECK">在庫確認中</option><option value="OTHER">その他</option></select></label>{reasonCode === "OTHER" && <label className="block">理由の詳細<input className="field" required maxLength={200} value={reasonText} onChange={e => setReasonText(e.target.value)}/></label>}<label className="flex gap-3"><input type="checkbox" checked={unknown} onChange={e => setUnknown(e.target.checked)}/>確認中にする</label><label className="block">新しい予定（日本時間）<input className="field" type="datetime-local" required={!unknown} disabled={unknown} value={readyTime} onChange={e => setReadyTime(e.target.value)}/></label></>}<button className="primary">{mutation.pending ? "登録中…" : "登録"}</button></fieldset>{mutation.error && <ErrorPanel error={mutation.error}/ >}</form>;
}
function Acceptance({ store, refresh }: { store: Store; refresh: () => void }) {
  const [pending,setPending] = useState(false); const [error,setError] = useState<Error|null>(null);
  async function change() {
    const reason = store.acceptingOrders ? window.prompt("受付停止の理由を入力してください") : null;
    if (store.acceptingOrders && !reason?.trim()) return;
    setPending(true); setError(null);
    try { await apiFetch("/api/v1/staff/store/acceptance",{method:"PUT",body:{acceptingOrders:!store.acceptingOrders,reason,version:store.version}}); refresh(); } catch (value) { setError(value as Error); } finally { setPending(false); }
  }
  return <div className="my-5 rounded-xl border p-5"><p className="font-bold">{store.acceptingOrders ? "受付中" : `受付停止中（${store.acceptanceReason}）`}</p><button className="secondary mt-3" disabled={pending} onClick={() => void change()}>{store.acceptingOrders ? "受付を停止する" : "受付を再開する"}</button>{error && <ErrorPanel error={error} retry={refresh}/ >}</div>;
}
export function StaffStorePage() {
  const result = useApi<Store>("/api/v1/staff/store"); const [selected,setSelected] = useState<Store["days"][number]|null>(null);
  if (result.error) return <ErrorPanel error={result.error} retry={result.retry}/>;
  if (!result.data) return <Loading/>;
  return <><PageIntro eyebrow="STORE" title="受付・営業時間"/><Acceptance store={result.data} refresh={result.retry}/><p className="my-5">通常営業 {result.data.defaultHours.opensAt}〜{result.data.defaultHours.closesAt} ・定休曜日（ISO）{result.data.defaultHours.regularClosedWeekdays.join(",") || "なし"}</p>{result.data.days.map(day => <div className="flex items-center justify-between border-b py-4" key={day.date}><div><p>{day.date}</p><p className="text-sm">{day.closed ? "休業" : `${day.opensAt}〜${day.closesAt}`} ・{day.source === "DEFAULT" ? "通常" : "個別設定"}</p></div><button className="secondary" onClick={() => setSelected(day)}>変更</button></div>)}{selected && <HoursEditor key={`${selected.date}:${selected.overrideVersion}`} day={selected} close={() => setSelected(null)} refresh={result.retry}/>}</>;
}
function HoursEditor({ day, close, refresh }: { day: Store["days"][number]; close: () => void; refresh: () => void }) {
  const [mode,setMode]=useState(day.closed ? "CLOSED" : "HOURS"); const [opening,setOpening]=useState(day.opensAt ?? "10:00"); const [closing,setClosing]=useState(day.closesAt ?? "21:00"); const [pending,setPending]=useState(false); const [error,setError]=useState<Error|null>(null);
  async function submit(e: FormEvent) { e.preventDefault(); setPending(true); try { const value=await apiFetch<Store>(`/api/v1/staff/store/business-hours/${day.date}`,{method:"PUT",body:{useDefault:mode === "DEFAULT",closed:mode === "CLOSED",opensAt:mode === "HOURS" ? opening : null,closesAt:mode === "HOURS" ? closing : null,version:day.overrideVersion}}); if (value.warnings?.length) window.alert(value.warnings.join("\n")); refresh(); close(); } catch(value) { setError(value as Error); } finally { setPending(false); } }
  return <div role="dialog" aria-modal="true" aria-label="営業時間の変更" className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-5"><form onSubmit={submit} className="w-full max-w-lg space-y-5 rounded-xl bg-white p-6"><h2 className="text-lg font-bold">{day.date} の営業時間</h2><fieldset disabled={pending} className="space-y-4"><label>設定<select className="field" value={mode} onChange={e=>setMode(e.target.value)}><option value="DEFAULT">通常営業に戻す</option><option value="CLOSED">休業にする</option><option value="HOURS">時間を指定</option></select></label>{mode === "HOURS" && <><label className="block">開店<input className="field" type="time" required value={opening} onChange={e=>setOpening(e.target.value)}/></label><label className="block">閉店<input className="field" type="time" required value={closing} onChange={e=>setClosing(e.target.value)}/></label></>}<div className="flex gap-4"><button className="primary">保存</button><button className="secondary" type="button" onClick={close}>閉じる</button></div></fieldset>{error && <ErrorPanel error={error}/ >}</form></div>;
}
