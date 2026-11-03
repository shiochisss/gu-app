import { addCartItem, changeQuantity, changeStore, emptyCart, parseCart } from "../src/lib/cart";
import { formatDateTime, formatMoney } from "../src/lib/format";
import { safeNext, apiFetch } from "../src/lib/api";
const store = "10000000-0000-4000-8000-000000000000";
const item = { productId: "20000000-0000-4000-8000-000000000000", productVariantId: "30000000-0000-4000-8000-000000000000", quantity: 2 };

test("FT-01 money formatting", () => { expect(formatMoney(1234)).toBe("¥1,234"); expect(formatMoney(0)).toBe("¥0"); });
test("FT-02 JST day boundaries", () => {
  const now = new Date("2026-11-02T15:00:00Z");
  expect(formatDateTime("2026-11-02T15:00:00Z", now)).toBe("本日 00:00");
  expect(formatDateTime("2026-11-02T14:59:59Z", now)).toBe("11月2日 23:59");
});
test("FT-03 adds the same SKU, limits total and preserves old contents on failure", () => {
  const first = addCartItem(emptyCart(), store, item, 10);
  expect(addCartItem(first, store, item, 10).items[0].quantity).toBe(4);
  expect(() => addCartItem(first, store, { ...item, quantity: 9 }, 10)).toThrow("合計10点");
  expect(() => addCartItem(first, store, item, 3)).toThrow("在庫が足りません");
  expect(first.items[0].quantity).toBe(2);
});
test("FT-04 store change requires confirmation", () => {
  const cart = addCartItem(emptyCart(), store, item, 10);
  expect(changeStore(cart, "other", false)).toBe(cart);
  expect(changeStore(cart, "other", true).items).toHaveLength(0);
});
test("BND-F02 rejects negative, fractional, duplicate or over-limit saved quantities", () => {
  for (const quantity of [-1, 0, .5, 11]) expect(parseCart({ storeId: store, items: [{ ...item, quantity }], shortagePolicy: "CANCEL_ALL" }).items).toHaveLength(0);
  const valid = addCartItem(emptyCart(), store, item, 10);
  expect(() => changeQuantity(valid, item.productVariantId, 0, 10)).toThrow();
  expect(parseCart({ ...valid, items: [item, item] }).items).toHaveLength(0);
  expect(Object.keys(valid.items[0]).sort()).toEqual(["productId", "productVariantId", "quantity"]);
});
test.each(["https://evil.example", "//evil.example", "/\\evil.example", "/%2f%2fevil.example", "/%0aevil"])("FT-06 rejects unsafe next %s", value => expect(safeNext(value)).toBe("/"));
test("FT-06 allows an internal path", () => expect(safeNext("/orders")).toBe("/orders"));
test("FT-05 sets Ajax and idempotency headers", async () => {
  const send = jest.spyOn(global, "fetch").mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) } as Response);
  await apiFetch("/api/v1/test", { method: "POST", idempotencyKey: "test-key", body: {} });
  const headers = send.mock.calls[0][1]!.headers as Record<string, string>;
  expect(headers["X-Requested-With"]).toBe("pickup-app"); expect(headers["Idempotency-Key"]).toBe("test-key"); send.mockRestore();
});

test("FT-07 localStorage failures keep an in-memory cart", () => {
  const read = jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("storage blocked"); });
  const write = jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage blocked"); });
  jest.isolateModules(() => {
    const storage = jest.requireActual<typeof import("../src/lib/store")>("../src/lib/store");
    expect(storage.getSnapshot().cart.items).toHaveLength(0);
    storage.updateSnapshot({ cart: addCartItem(emptyCart(), store, item, 10) });
    expect(storage.getSnapshot().cart.items[0].quantity).toBe(2);
  });
  read.mockRestore(); write.mockRestore();
});
test("stock reduction still allows reducing an oversized cart line", () => {
  const cart = addCartItem(emptyCart(), store, { ...item, quantity: 5 }, 10);
  expect(changeQuantity(cart, item.productVariantId, 4, 1).items[0].quantity).toBe(4);
  expect(() => changeQuantity(cart, item.productVariantId, 6, 1)).toThrow();
});
