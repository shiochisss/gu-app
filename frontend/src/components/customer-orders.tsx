"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { components } from "@/types/api";
import { apiFetch } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { updateSnapshot } from "@/lib/store";
import { useApi, useCartStore } from "./runtime";
import { CustomerPickup } from "./customer-pickup";
import { Pager } from "./staff-common";
import { Empty, ErrorPanel, Loading, PageIntro } from "./ui";

type Detail = components["schemas"]["OrderDetail"];
export function OrderResult({ id }: { id: string }) {
  const result = useApi<Detail>(`/api/v1/orders/${id}`); const { cart } = useCartStore();
  const [timedOut, setTimedOut] = useState(false); const cleared = useRef(false);
  const mountedAt = useRef<number | null>(null);
  useEffect(() => {
    if (result.data?.status !== "RECEIVED" || cleared.current) return;
    cleared.current = true; updateSnapshot({ cart: { ...cart, items: [] } });
  }, [result.data, cart]);
  useEffect(() => {
    if (result.data?.status !== "PENDING_PAYMENT") return;
    if (mountedAt.current === null) mountedAt.current = Date.now();
    let active = true, running = false;
    const timer = setInterval(async () => {
      if (Date.now() - mountedAt.current! >= 120000) { setTimedOut(true); clearInterval(timer); return; }
      if (running) return; running = true;
      try { await apiFetch(`/api/v1/orders/${id}/payment/refresh`, { method: "POST" }); if (active) result.retry(); } catch { /* A transient error is not a declined card. */ } finally { running = false; }
    }, 5000);
    return () => { active = false; clearInterval(timer); };
    // The effect follows status and the stable retry callback, not loading objects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, result.data?.status, result.retry]);
  if (result.error) return <ErrorPanel error={result.error} retry={result.retry}/>;
  if (!result.data) return <Loading/>;
  const order = result.data;
  const pending = order.status === "PENDING_PAYMENT"; const failed = order.status === "NOT_ACCEPTED";
  return <><PageIntro eyebrow="ORDER RESULT" title={pending ? "お支払いを確認しています" : failed ? "注文は成立しませんでした" : "ご注文を受け付けました"}/>{failed ? <p>カードの確認ができませんでした</p> : pending ? <p role="status">{timedOut ? "確認に時間がかかっています。注文一覧で状況を確認できます" : "このままお待ちください。支払結果を確認しています。"}</p> : <p>準備ができたらメールでお知らせします</p>}<div className="my-6 rounded-xl bg-slate-50 p-5 leading-8"><p className="font-bold">{order.orderNumber}</p><p>{order.store.name}</p><p>当初の準備完了予定：{formatDateTime(order.originalReadyAt)}</p><p>{order.statusLabel}</p></div>{failed && <Link href="/checkout" className="primary mb-4 w-full">注文手続きをやり直す</Link>}<Link className="primary w-full" href={`/orders/${id}`}>注文詳細を見る</Link><Link className="secondary mt-4 w-full" href="/orders">注文一覧へ</Link></>;
}
export function CustomerOrders() {
  const [page, setPage] = useState(1);
  const result = useApi<components["schemas"]["OrderList"]>(`/api/v1/orders?page=${page}`);
  return <><PageIntro eyebrow="YOUR ORDERS" title="注文一覧"/>{result.error && <ErrorPanel error={result.error} retry={result.retry}/ >}{result.loading && <Loading/>}{result.data && <>{!result.data.items.length && <Empty>ご注文はまだありません</Empty>}{result.data.items.map(order => <Link className="my-4 block rounded-xl border p-5 leading-8" key={order.orderId} href={`/orders/${order.orderId}`}><p className="font-bold">{order.orderNumber} ・{order.statusLabel}</p><p>{order.storeName}</p><p>{order.isDelayed ? `遅延中・${order.currentReadyAt ? `新予定 ${formatDateTime(order.currentReadyAt)}` : "確認中"}` : `準備完了予定：${formatDateTime(order.currentReadyAt)}`}</p><p>{formatMoney(order.orderedAmountYen)} ・{formatDateTime(order.createdAt)}</p></Link>)}<Pager page={page} total={result.data.totalCount} change={setPage}/></>}</>;
}
export function CustomerOrderDetail({ id }: { id: string }) {
  const result = useApi<Detail>(`/api/v1/orders/${id}`);
  useEffect(() => { const timer = setInterval(result.retry, 30000); return () => clearInterval(timer); }, [result.retry]);
  if (result.error) return <ErrorPanel error={result.error} retry={result.retry}/>;
  if (!result.data) return <Loading/>;
  const order = result.data;
  return <><Link href="/orders" className="underline">注文一覧へ</Link><PageIntro eyebrow={order.orderNumber} title={order.statusLabel}/><div className="space-y-3 rounded-xl bg-slate-50 p-5"><h2 className="font-bold">{order.store.name}</h2><p className="text-sm">{order.store.address}</p><p>当初の準備完了予定：{formatDateTime(order.originalReadyAt)}</p>{order.isDelayed && <p role="status" className="text-amber-800">遅延中：{order.delays[0]?.reasonText}／新しい予定 {order.updatedReadyAt ? formatDateTime(order.updatedReadyAt) : "確認中"}</p>}{order.readyAt && <p>準備完了日時：{formatDateTime(order.readyAt)}</p>}{order.pickupDeadlineAt && <p className={["READY","EXPIRED"].includes(order.status) ? "font-bold" : ""}>受取期限：{formatDateTime(order.pickupDeadlineAt)}</p>}<p>{order.paymentStatusLabel}</p></div>{order.status === "PENDING_PAYMENT" && <Link className="secondary my-5 w-full" href={`/orders/${id}/complete`}>支払結果を確認する</Link>}{order.items.map(item => <div className="border-b py-5" key={item.orderItemId}><p>{item.productName} / {item.colorName} / {item.size}</p><p className="text-sm">{item.sku} ・{formatMoney(item.unitPriceYen)} × {item.orderedQuantity}点</p>{item.shortageQuantity > 0 && <p className="text-red-700">欠品 {item.shortageQuantity}点</p>}</div>)}<div className="my-5 space-y-3"><p className="font-bold">注文金額：{formatMoney(order.orderedAmountYen)}</p>{order.capturedAmountYen !== null && <p className="font-bold">確定金額：{formatMoney(order.capturedAmountYen)}</p>}<p>欠品時：{order.shortagePolicy === "CANCEL_ALL" ? "注文全体をキャンセル" : "用意できた商品だけ購入"}</p>{order.cancelReasonLabel && <p>取り消しました。取消理由：{order.cancelReasonLabel}</p>}{order.status === "EXPIRED" && <p>受取期限を過ぎました。店舗が商品を棚に戻すまでは受け取れます。</p>}<CustomerPickup order={order} refresh={result.retry}/></div></>;
}
export function Mailbox() {
  const result = useApi<components["schemas"]["MailList"]>("/api/v1/dev/mails");
  return <><PageIntro eyebrow="DEVELOPMENT" title="送信メール一覧"/>{result.error && <ErrorPanel error={result.error} retry={result.retry}/ >}{result.loading && <Loading/>}{result.data?.items.map(mail => <article className="my-5 space-y-3 rounded-xl border p-5" key={mail.notificationId}><h2 className="font-bold">{mail.subject}</h2><p className="break-all text-sm">宛先：{mail.recipientEmail}</p><p className="text-sm">{mail.status} ・送信日時：{formatDateTime(mail.sentAt)}</p><p className="whitespace-pre-wrap break-words text-sm leading-7">{mail.bodyText.split(/(https?:\/\/[^\s]+\/orders\/[0-9a-f-]{36})/g).map((part,index) => /^https?:\/\//.test(part) ? <a className="underline" href={part} key={index}>{part}</a> : part)}</p></article>)}{result.data?.items.length === 0 && <Empty>送信メールはありません</Empty>}</>;
}
