"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { changeStore } from "@/lib/cart";
import { formatTime } from "@/lib/format";
import { updateSnapshot } from "@/lib/store";
import { Icon } from "./icons";
import { useCartStore, useSession } from "./runtime";
import { Empty, ErrorPanel, Loading, PageIntro, StoreStatus } from "./ui";

export function StoreSelector() {
  const { stores } = useSession(); const { cart, selectedStoreId } = useCartStore(); const router = useRouter();
  function choose(storeId: string) {
    const needsConfirm = cart.items.length > 0 && cart.storeId !== storeId;
    if (needsConfirm && !window.confirm("店舗を変更するとカートが空になります。よろしいですか？")) return;
    updateSnapshot({ selectedStoreId: storeId, cart: changeStore(cart, storeId, true), storageNotice: null });
    router.push(`/stores/${storeId}/products`);
  }
  return <>
    <PageIntro eyebrow="FIND YOUR STORE" title={"受け取るお店を\n選びましょう。"}>お店ごとの在庫から商品を探して、<br/>ご都合のよい時間に店舗でお受け取り。</PageIntro>
    <div className="mb-5 flex items-center justify-between"><h2 className="text-sm font-bold">受取店舗</h2><span className="text-xs text-[#627589]">{stores.data ? `${stores.data.items.length}店舗` : ""}</span></div>
    {stores.loading ? <Loading label="店舗を読み込んでいます"/> : stores.error ? <ErrorPanel error={stores.error} retry={stores.retry}/> : !stores.data?.items.length ? <Empty>現在、選択できる店舗はありません。</Empty> : <div className="space-y-4">{stores.data.items.map((store, index) => <button onClick={() => choose(store.storeId)} key={store.storeId} className={`group block w-full rounded-xl border p-5 text-left transition hover:border-[#1F4E8C] hover:shadow-sm ${selectedStoreId === store.storeId ? "border-[#1F4E8C] bg-[#FBFCFF]" : "border-[#D9E2EC] bg-white"}`}>
      <div className="mb-3 flex items-start justify-between"><div><p className="mb-1 text-[10px] font-semibold tracking-[0.12em] text-[#8B9BAB]">STORE {String(index + 1).padStart(2, "0")} / {store.code}</p><h3 className="text-lg font-bold">{store.name}</h3></div><span className="flex size-9 items-center justify-center rounded-full bg-[#F0F4FA] text-[#1F4E8C] transition group-hover:bg-[#1F4E8C] group-hover:text-white"><Icon name="arrow" className="size-4"/></span></div>
      <p className="mb-3 flex items-start gap-1.5 text-xs leading-6 text-[#627589]"><Icon name="pin" className="mt-1 size-3.5 shrink-0"/>{store.address}</p>
      <div className="mb-4 flex items-center gap-1.5 text-xs text-[#526778]"><Icon name="clock" className="size-3.5"/><span>{store.today.closed ? "本日休業" : `本日の営業時間 ${store.today.opensAt}–${store.today.closesAt}`}</span></div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#EDF1F6] pt-4"><StoreStatus store={store}/>{store.earliestReadyAt && <span className="text-[11px] text-[#627589]">最短の準備完了予定 <strong className="text-sm text-[#1F4E8C]">{formatTime(store.earliestReadyAt)}</strong></span>}</div>
    </button>)}</div>}
    <div className="mt-7 flex gap-3 rounded-xl bg-[#F5F7FA] p-4"><Icon name="bag" className="mt-1 size-5 shrink-0 text-[#627589]"/><p className="text-xs leading-6 text-[#627589]">選択した店舗で受け取れる商品をご案内します。<br/>店舗はあとから変更できます。</p></div>
    <p className="mt-7 text-center"><Link href="/staff/login" className="inline-flex min-h-11 items-center text-xs text-[#627589]">店舗スタッフの方はこちら <Icon name="arrow" className="ml-1 size-3"/></Link></p>
  </>;
}
