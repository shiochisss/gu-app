"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode, FormEvent } from "react";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import type { components } from "@/types/api";
import { ApiError, apiFetch } from "@/lib/api";
import { formatDateTime, formatMoney, formatTime } from "@/lib/format";
import { updateSnapshot } from "@/lib/store";
import { useCartStore, useSession } from "./runtime";
import { useMutation } from "./staff-common";
import { Empty, ErrorPanel, Loading, PageIntro } from "./ui";

type Estimate = components["schemas"]["EstimateResponse"];
type OrderInput = components["schemas"]["OrderInput"];
type OrderCreated = components["schemas"]["OrderCreated"];
type Draft = { estimate: Estimate; signature: string; userId: string; agreed: boolean };
const CheckoutContext = createContext<{ draft: Draft | null; setDraft: (value: Draft | null) => void } | null>(null);
export function CheckoutProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  return <CheckoutContext.Provider value={{ draft, setDraft }}>{children}</CheckoutContext.Provider>;
}
function useCheckout() { const value = useContext(CheckoutContext); if (!value) throw new Error("CheckoutProvider required"); return value; }
function cartSignature(cart: ReturnType<typeof useCartStore>["cart"]) { return JSON.stringify([cart.storeId, cart.items.map(({ productVariantId, quantity }) => ({ productVariantId, quantity })), cart.shortagePolicy]); }
const rejectionMessages: Record<string, string> = { STORE_NOT_ACCEPTING: "この店舗は現在、注文の受付を停止しています。", ORDER_CLOSED: "本日の注文受付は終了しました。", OUT_OF_STOCK: "在庫が足りない商品があります。", CAPACITY_FULL: "混雑のため、閉店までに準備が間に合いません。" };
const returnMessages: Record<string, string> = { PAYMENT_DECLINED: "カードでのお支払いができませんでした。別のカードをお試しください。", ESTIMATE_EXPIRED: "確認画面の有効期限が切れました。もう一度確認してください。", CALCULATION_CHANGED: "金額または準備完了予定が変わりました。内容を確認してください。", ...rejectionMessages };

export function CheckoutPage() {
  const { cart } = useCartStore(); const { user } = useSession(); const { draft, setDraft } = useCheckout();
  const router = useRouter(); const params = useSearchParams(); const [revision, setRevision] = useState(0);
  const [agreed, setAgreed] = useState(false); const [now, setNow] = useState(0);
  const [response, setResponse] = useState<{ key: string; value: Estimate } | null>(null);
  const [error, setError] = useState<ApiError | null>(null); const [changeNotice, setChangeNotice] = useState("");
  const previous = useRef<Estimate | null>(null);
  const signature = cartSignature(cart); const key = `${user?.userId}:${signature}:${revision}`;
  const preview = response?.key === key ? response.value : null;
  useEffect(() => {
    if (!user || user.role !== "CUSTOMER" || !cart.storeId || !cart.items.length) return;
    let active = true; const controller = new AbortController();
    apiFetch<Estimate>("/api/v1/orders/estimate", { method: "POST", body: { storeId: cart.storeId, items: cart.items.map(({ productVariantId, quantity }) => ({ productVariantId, quantity })), shortagePolicy: cart.shortagePolicy }, signal: controller.signal }).then(value => {
      if (!active) return;
      const old = previous.current;
      if (old?.accepted && value.accepted && (old.estimatedReadyAt !== value.estimatedReadyAt || old.totalAmountYen !== value.totalAmountYen)) setChangeNotice(`準備完了予定が変わりました：${formatDateTime(old.estimatedReadyAt)} → ${formatDateTime(value.estimatedReadyAt)}／${formatMoney(old.totalAmountYen)} → ${formatMoney(value.totalAmountYen)}`);
      previous.current = value; setResponse({ key, value }); setAgreed(false); setError(null);
      setDraft({ estimate: value, signature, userId: user.userId, agreed: false });
    }).catch(value => { if (active && value.name !== "AbortError") setError(value); });
    return () => { active = false; controller.abort(); };
  // signature includes all cart fields that affect an estimate.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    if (!preview?.accepted || !preview.estimateExpiresAt) return;
    let requested = false;
    const timer = setInterval(() => { const value = Date.now(); setNow(value); if (!requested && value >= Date.parse(preview.estimateExpiresAt!)) { requested = true; setRevision(x => x + 1); } }, 1000);
    return () => clearInterval(timer);
  }, [preview]);
  if (!cart.items.length || !cart.storeId) return <Empty>カートに商品が入っていません。<Link href="/cart" className="primary mt-4">カートに戻る</Link></Empty>;
  return <><PageIntro eyebrow="CHECKOUT" title="注文・受取条件の確認"/>{returnMessages[params.get("reason") ?? ""] && <p role="alert" className="mb-4 text-red-700">{returnMessages[params.get("reason") ?? ""]}</p>}{changeNotice && <p role="status" className="mb-4 text-amber-800">{changeNotice}</p>}{error ? <ErrorPanel error={error} retry={() => setRevision(x => x + 1)}/> : !preview ? <Loading/> : <><h2 className="text-lg font-bold">{preview.storeName}でお受け取り</h2>{preview.accepted ? <div className="my-5 rounded-xl bg-slate-50 p-5"><p className="text-xl font-bold">{formatDateTime(preview.estimatedReadyAt)} ごろ準備完了予定</p><p className="mt-2 text-sm">現時点の見込みです</p></div> : <div role="alert" className="my-5 text-red-700"><p>{rejectionMessages[preview.rejectionCode ?? ""]}</p>{Array.isArray(preview.rejectionDetails?.lines) && (preview.rejectionDetails.lines as { productName: string; availableQuantity: number }[]).map((line, index) => <p key={index}>{line.productName}：販売可能{line.availableQuantity}点</p>)}</div>}
    {preview.items.map(line => <div className="border-b py-4" key={line.productVariantId}><p>{line.productName} / {line.colorName} / {line.size}</p><p className="text-sm">{formatMoney(line.unitPriceYen)} × {line.quantity}点 ・{formatMoney(line.lineAmountYen)}</p></div>)}<p className="my-5 text-xl font-bold">合計{preview.totalQuantity}点 ・{formatMoney(preview.totalAmountYen)}</p>
    {preview.accepted && <><fieldset className="my-5 space-y-3"><legend className="mb-3 font-bold">欠品時の希望</legend>{([['CANCEL_ALL','注文全体をキャンセル'],['PURCHASE_AVAILABLE','用意できた商品だけ購入']] as const).map(([value,label]) => <label className="flex items-center gap-3" key={value}><input type="radio" name="shortage" value={value} checked={cart.shortagePolicy === value} onChange={() => updateSnapshot({ cart: { ...cart, shortagePolicy: value } })}/>{label}</label>)}</fieldset><div className="my-5 space-y-4 rounded-xl border p-5 text-sm leading-7"><p>{preview.pickupDeadlineRuleText}</p><p>{preview.overduePolicyText}</p></div><label className="my-5 flex items-start gap-3 text-sm leading-7"><input className="mt-2" type="checkbox" checked={agreed} onChange={e => setAgreed(e.target.checked)}/>受取期限と期限を過ぎた場合の扱いを確認しました</label><p className="my-4 text-sm">{formatTime(preview.estimateExpiresAt)} まで有効です{now > 0 && preview.estimateExpiresAt ? `（残り${Math.max(0, Math.ceil((Date.parse(preview.estimateExpiresAt) - now) / 1000))}秒）` : ""}</p><button className="primary w-full" disabled={!agreed || !draft || (now > 0 && now >= Date.parse(preview.estimateExpiresAt!))} onClick={() => { if (draft) { setDraft({ ...draft, agreed: true }); router.push("/checkout/payment"); } }}>支払手続きへ進む</button></>}<Link className="secondary my-4 w-full" href="/cart">カートに戻る</Link></>}</>;
}

const publishableKey = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? "";
const stripePromise = /^pk_test_/.test(publishableKey) && !publishableKey.includes("replace") ? loadStripe(publishableKey) : null;
export function PaymentPage() {
  const { draft } = useCheckout(); const { cart } = useCartStore(); const { user } = useSession(); const router = useRouter();
  const valid = !!draft?.agreed && draft.estimate.accepted && draft.userId === user?.userId && draft.signature === cartSignature(cart);
  useEffect(() => { if (!valid) router.replace("/checkout"); }, [valid, router]);
  if (!valid || !draft) return <Loading/>;
  return <><PageIntro eyebrow="PAYMENT" title="支払手続き"/><p className="mb-3 text-xl font-bold">{formatMoney(draft.estimate.totalAmountYen)}</p><p className="mb-5">{formatDateTime(draft.estimate.estimatedReadyAt)} ごろ準備完了予定</p><p className="mb-5 rounded-lg bg-amber-50 p-4 text-sm">テスト環境です。Stripeのテスト用カード番号を入力してください。</p>{stripePromise ? <Elements key={draft.estimate.estimateId} stripe={stripePromise} options={{ mode: "payment", amount: draft.estimate.totalAmountYen, currency: "jpy", captureMethod: "manual", paymentMethodCreation: "manual", allowedPaymentMethodTypes: ["card"] }}><PaymentForm draft={draft}/></Elements> : <ErrorPanel error={new Error("Stripeのテスト用公開キーを設定してください。")}/>}<Link className="secondary mt-5 w-full" href="/checkout">確認画面に戻る</Link></>;
}
export function PaymentForm({ draft }: { draft: Draft }) {
  const stripe = useStripe(); const elements = useElements(); const router = useRouter(); const mutation = useMutation();
  const [working, setWorking] = useState(false); const [error, setError] = useState<Error | null>(null);
  const active = useRef(false); const submitted = useRef<OrderInput | null>(null);
  const busy = working || mutation.pending;
  useEffect(() => { if (!busy) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [busy]);
  useEffect(() => { if (!mutation.error) return; if (["PAYMENT_DECLINED", "ESTIMATE_EXPIRED", "CALCULATION_CHANGED", "ORDER_CLOSED", "STORE_NOT_ACCEPTING", "OUT_OF_STOCK"].includes(mutation.error.code)) router.replace(`/checkout?reason=${mutation.error.code}`); }, [mutation.error, router]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!stripe || !elements || active.current) return;
    active.current = true; setWorking(true); setError(null);
    try {
      if (!submitted.current) {
        const validation = await elements.submit(); if (validation.error) throw new Error(validation.error.message ?? "カード情報を確認してください。");
        const token = await stripe.createConfirmationToken({ elements }); if (token.error) throw new Error(token.error.message ?? "カード情報を確認してください。");
        const { estimate } = draft;
        submitted.current = { estimateId: estimate.estimateId!, storeId: estimate.storeId,
          items: estimate.items.map(({ productVariantId, quantity }) => ({ productVariantId, quantity })),
          shortagePolicy: estimate.shortagePolicy as OrderInput["shortagePolicy"],
          clientTotalAmountYen: estimate.totalAmountYen, clientEstimatedReadyAt: estimate.estimatedReadyAt!,
          confirmationTokenId: token.confirmationToken.id, agreedToPickupTerms: true };
      }
      const result = await mutation.send<OrderCreated>("/api/v1/orders", submitted.current);
      if (!result) return;
      if (result.nextAction) {
        try { await stripe.handleNextAction({ clientSecret: result.nextAction.clientSecret }); } catch { /* Closing authentication still requires a server-side check. */ } finally {
          try { await apiFetch(`/api/v1/orders/${result.orderId}/payment/refresh`, { method: "POST" }); } catch { /* Result page keeps checking. */ }
        }
      }
      router.replace(`/orders/${result.orderId}/complete`);
    } catch (failure) { setError(failure instanceof Error ? failure : new Error("通信できませんでした")); }
    finally { active.current = false; setWorking(false); }
  }
  return <form onSubmit={submit}><fieldset disabled={busy}><PaymentElement options={{ layout: "tabs" }}/><button className="primary mt-6 w-full" disabled={!stripe || !elements || busy}>{busy ? "確認しています…" : mutation.error ? "同じ注文を再試行" : "注文を確定する"}</button></fieldset>{error && <ErrorPanel error={error}/ >}{mutation.error && <ErrorPanel error={mutation.error}/>}</form>;
}
