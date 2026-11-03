"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import type { components } from "@/types/api";
import { formatMoney } from "@/lib/format";
import { useApi } from "./runtime";
import { useMutation } from "./staff-common";
import { ErrorPanel, Loading, PageIntro } from "./ui";

type Detail=components["schemas"]["OrderDetail"];
export function CustomerPickup({order,refresh}:{order:Detail;refresh:()=>void}) {
  const mutation=useMutation();
  async function reissue(){if(!window.confirm("再発行すると、以前のQRは使えなくなります"))return;const value=await mutation.send(`/api/v1/orders/${order.orderId}/pickup-token/reissue`,{version:order.version});if(value)refresh();}
  return <>{order.pickup && <section className="my-6 space-y-5 rounded-xl border p-5 text-center"><div className="flex justify-center"><QRCodeSVG value={order.pickup.qrValue} size={240}/></div><p className="font-bold">受取コード：{order.pickup.manualCode}（注文番号 {order.orderNumber}）</p><p className="text-sm leading-7">店員にこの画面を提示してください。QRを渡した方も受け取れます。</p>{order.canReissuePickupCode && <button className="secondary" disabled={mutation.pending} onClick={()=>void reissue()}>QRを再発行</button>}</section>}{order.canCancel && <Link className="secondary my-5 w-full" href={`/orders/${order.orderId}/cancel`}>注文を取り消す</Link>}{mutation.error && <ErrorPanel error={mutation.error} retry={refresh}/ >}</>;
}
export function CancelOrder({id}:{id:string}) {
  const result=useApi<Detail>(`/api/v1/orders/${id}`);const mutation=useMutation();const router=useRouter();
  if(result.error)return <ErrorPanel error={result.error} retry={result.retry}/>;
  if(!result.data)return <Loading/>;
  const order=result.data;
  async function cancel(){const value=await mutation.send(`/api/v1/orders/${id}/cancel`,{version:order.version});if(value)router.replace(`/orders/${id}?cancelled=true`);}
  return <><PageIntro eyebrow={order.orderNumber} title="取消確認"/><p className="my-5">{order.canCancel ? "準備の遅れにより、無料で取り消せます。" : "このご注文は取り消せません。"}</p><p className="my-5">{order.paymentStatus === "CAPTURED" ? "全額を返金します" : "カードの利用枠を解放します"}</p>{order.items.map(item=><p className="border-b py-4" key={item.orderItemId}>{item.productName} / {item.colorName} / {item.size} × {item.orderedQuantity}点</p>)}<p className="my-5 font-bold">注文金額 {formatMoney(order.orderedAmountYen)}</p>{order.capturedAmountYen !== null && <p className="my-5 font-bold">確定金額 {formatMoney(order.capturedAmountYen)}</p>}<button className="primary w-full" disabled={mutation.pending || !order.canCancel} onClick={()=>void cancel()}>取り消す</button><Link className="secondary my-4 w-full" href={`/orders/${id}`}>注文詳細に戻る</Link>{mutation.error && <ErrorPanel error={mutation.error} retry={result.retry}/ >}</>;
}
