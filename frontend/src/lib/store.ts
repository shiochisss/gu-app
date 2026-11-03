import { Cart, emptyCart, parseCart } from "./cart";
export type Snapshot = { selectedStoreId: string | null; cart: Cart; storageNotice: string | null };
const initial: Snapshot = { selectedStoreId: null, cart: emptyCart(), storageNotice: null };
let snapshot = initial;
let loaded = false;
const listeners = new Set<() => void>();
function load() {
  try {
    const raw = localStorage.getItem("pa.cart"); const decoded = raw ? JSON.parse(raw) : null;
    const cart = decoded ? parseCart(decoded) : emptyCart();
    const selected = localStorage.getItem("pa.selectedStoreId");
    const selectedStoreId = selected && /^[0-9a-f-]{36}$/i.test(selected) ? selected : null;
    return { selectedStoreId, cart, storageNotice: decoded?.items?.length && !cart.items.length ? "保存したカートを読み込めませんでした。商品を選び直してください。" : null };
  } catch { return { ...initial }; }
}
export function getSnapshot() { if (!loaded && typeof window !== "undefined") { snapshot = load(); loaded = true; } return snapshot; }
export function getServerSnapshot() { return initial; }
function changed(event: StorageEvent) { if (["pa.cart", "pa.selectedStoreId", null].includes(event.key)) { snapshot = load(); listeners.forEach(fn => fn()); } }
export function subscribe(fn: () => void) { listeners.add(fn); if (listeners.size === 1) window.addEventListener("storage", changed); return () => { listeners.delete(fn); if (!listeners.size) window.removeEventListener("storage", changed); }; }
export function updateSnapshot(value: Partial<Snapshot>) {
  snapshot = { ...getSnapshot(), ...value };
  try { localStorage.setItem("pa.cart", JSON.stringify(snapshot.cart)); if (snapshot.selectedStoreId) localStorage.setItem("pa.selectedStoreId", snapshot.selectedStoreId); } catch { /* Continue with the in-memory cart. */ }
  listeners.forEach(fn => fn());
}
