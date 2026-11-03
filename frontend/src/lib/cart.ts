import { z } from "zod";
export type CartItem = { productId: string; productVariantId: string; quantity: number };
export type Cart = { storeId: string | null; items: CartItem[]; shortagePolicy: "CANCEL_ALL" | "PURCHASE_AVAILABLE" };
export const emptyCart = (): Cart => ({ storeId: null, items: [], shortagePolicy: "CANCEL_ALL" });
const schema = z.object({ storeId: z.uuid().nullable(), items: z.array(z.object({ productId: z.uuid(), productVariantId: z.uuid(), quantity: z.number().int().min(1).max(10) })).max(10), shortagePolicy: z.enum(["CANCEL_ALL", "PURCHASE_AVAILABLE"]) });
export function parseCart(value: unknown): Cart {
  const result = schema.safeParse(value);
  if (!result.success || result.data.items.reduce((n, item) => n + item.quantity, 0) > 10 || (result.data.items.length > 0 && !result.data.storeId) || new Set(result.data.items.map(item => item.productVariantId)).size !== result.data.items.length) return emptyCart();
  return result.data;
}
export function cartCount(cart: Cart) { return cart.items.reduce((n, item) => n + item.quantity, 0); }
export function addCartItem(cart: Cart, storeId: string, item: CartItem, max: number): Cart {
  if (!Number.isInteger(item.quantity) || item.quantity < 1) throw new Error("数量を確認してください。");
  if (cart.items.length && cart.storeId !== storeId) throw new Error("受取店舗を確認してください。");
  if (cartCount(cart) + item.quantity > 10) throw new Error("1回の注文は合計10点までです");
  const existing = cart.items.find(line => line.productVariantId === item.productVariantId);
  if ((existing?.quantity ?? 0) + item.quantity > max) throw new Error(`在庫が足りません（残り${max}点）`);
  return { ...cart, storeId, items: existing ? cart.items.map(line => line === existing ? { ...line, quantity: line.quantity + item.quantity } : line) : [...cart.items, item] };
}
export function changeQuantity(cart: Cart, id: string, quantity: number, max: number): Cart {
  const current = cart.items.find(line => line.productVariantId === id);
  if (!Number.isInteger(quantity) || quantity < 1 || (quantity > max && quantity >= (current?.quantity ?? 0))) throw new Error("数量を確認してください。");
  const result = { ...cart, items: cart.items.map(line => line.productVariantId === id ? { ...line, quantity } : line) };
  if (cartCount(result) > 10) throw new Error("1回の注文は合計10点までです");
  return result;
}
export function changeStore(cart: Cart, storeId: string, confirmed: boolean): Cart {
  if (cart.storeId === storeId) return cart;
  return cart.items.length && !confirmed ? cart : { ...emptyCart(), storeId };
}
