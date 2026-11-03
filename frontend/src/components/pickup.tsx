"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useRouter } from "next/navigation";
import { BrowserQRCodeReader } from "@zxing/browser";
import type { IScannerControls } from "@zxing/browser";
import type { components } from "@/types/api";
import { apiFetch } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { useMutation } from "./staff-common";
import { ErrorPanel, Loading, PageIntro } from "./ui";

type Verification = components["schemas"]["Verification"];
const Context = createContext<{ verification:Verification|null; setVerification:(value:Verification|null)=>void }|null>(null);
export function PickupProvider({children}:{children:ReactNode}) { const [verification,setVerification]=useState<Verification|null>(null); return <Context.Provider value={{verification,setVerification}}>{children}</Context.Provider>; }
function usePickup() { const value=useContext(Context); if (!value) throw new Error("PickupProvider required"); return value; }
export function PickupScanner() {
  const {setVerification}=usePickup(); const router=useRouter(); const [number,setNumber]=useState(""); const [code,setCode]=useState(""); const [error,setError]=useState<Error|null>(null); const [reason,setReason]=useState(""); const [pending,setPending]=useState(false); const [camera,setCamera]=useState(false);
  const video=useRef<HTMLVideoElement|null>(null); const controls=useRef<IScannerControls|null>(null); const running=useRef(false); const last=useRef({value:"",at:0}); const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controls.current?.stop();};},[]);
  async function verify(body: {qrValue:string}|{orderNumber:string;manualCode:string}) {
    if (running.current) return;
    running.current=true;setPending(true);setError(null);setReason("");
    try { const value=await apiFetch<Verification>("/api/v1/staff/pickups/verify",{method:"POST",body}); if (!mounted.current) return; if (value.canHandOver) { controls.current?.stop();setVerification(value);router.push("/staff/pickup/confirm"); } else setReason(`${value.reasonMessage ?? "照合できませんでした"}${value.reasonCode === "OTHER_STORE" ? `（${value.orderNumber}）` : ""}`); }
    catch(value) { if(mounted.current)setError(value as Error); } finally { running.current=false;if(mounted.current)setPending(false); }
  }
  useEffect(()=>{
    if (!camera || !video.current) return;
    let active=true; const reader=new BrowserQRCodeReader();
    reader.decodeFromConstraints({video:{facingMode:"environment"}},video.current,(result)=>{ if (!result || !active) return; const value=result.getText(),now=Date.now(); if (last.current.value === value && now-last.current.at<3000) return;last.current={value,at:now};void verify({qrValue:value}); }).then(value=>{ if(active)controls.current=value;else value.stop(); }).catch(()=>{if(active){setError(new Error("カメラを使えません。手入力してください"));setCamera(false);}});
    return()=>{active=false;controls.current?.stop();};
    // The scanner uses refs for in-flight and repeat-scan guards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[camera]);
  return <><PageIntro eyebrow="PICKUP" title="受け取り照合"/><div className="mb-6 rounded-xl border p-4"><button className="secondary" onClick={()=>{if(camera)controls.current?.stop();setCamera(!camera);}}>{camera ? "カメラを停止" : "カメラでQRを読み取る"}</button>{camera && <video ref={video} className="mt-4 w-full rounded-lg" muted playsInline aria-label="QR読み取りカメラ"/>}</div><form onSubmit={(e:FormEvent)=>{e.preventDefault();void verify({orderNumber:number.trim().toUpperCase(),manualCode:code});}} className="space-y-5"><fieldset disabled={pending} className="space-y-5"><label className="block">注文番号<input className="field" required pattern="P[0-9]{6,15}" maxLength={16} value={number} onChange={e=>setNumber(e.target.value.toUpperCase())}/></label><label className="block">受取コード（6桁）<input className="field" required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value)}/></label><button className="primary">{pending ? "照合中…" : "照合する"}</button></fieldset></form>{reason && <p role="alert" className="my-5 text-red-700">{reason}</p>}{error && <ErrorPanel error={error}/ >}</>;
}
export function PickupConfirm() {
  const {verification,setVerification}=usePickup(); const router=useRouter(); const mutation=useMutation(); const [notice,setNotice]=useState("");
  useEffect(()=>{if(!verification)router.replace("/staff/pickup");},[verification,router]);
  if(!verification)return <Loading/>;
  async function confirm(){if(!verification)return;const value=await mutation.send(`/api/v1/staff/orders/${verification.orderId}/handover`,{version:verification.version,pickupVerificationId:verification.pickupVerificationId});if(value){setNotice("受け取りを完了しました");}}
  return <><PageIntro eyebrow={verification.orderNumber ?? "PICKUP"} title="引き渡し確認"/>{notice ? <><p role="status">{notice}</p><button className="primary mt-5" onClick={()=>{setVerification(null);router.replace("/staff/pickup");}}>次の受け取り照合へ</button></> : <><p>{verification.status === "EXPIRED" ? "受取期限切れ（棚に戻す前）" : "受け取り可能"}</p>{verification.items?.map((item,index)=><p className="border-b py-4" key={index}>{item.productName} / {item.colorName} / {item.size} × {item.preparedQuantity}点</p>)}<p className="my-5 font-bold">確定金額 {formatMoney(verification.capturedAmountYen ?? 0)}</p><p>受取期限 {formatDateTime(verification.pickupDeadlineAt)}</p><button className="primary my-5 w-full" disabled={mutation.pending} onClick={()=>void confirm()}>商品を渡した（受け取り完了）</button>{mutation.error && <><ErrorPanel error={mutation.error.status === 409 ? new Error("すでに受け取り済み、または状態が変わりました") : mutation.error}/><button className="secondary mt-4" onClick={()=>{setVerification(null);router.replace("/staff/pickup");}}>再照合する</button></>}</>}</>;
}
