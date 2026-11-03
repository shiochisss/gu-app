import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { StaffPos } from "../src/components/staff-pos";
import { StaffOnly, useMutation } from "../src/components/staff-common";
import { ApiError, apiFetch } from "../src/lib/api";
const mockReplace = jest.fn();
let mockSession = { user: { role: "STAFF", storeName: "テスト店舗", email: "staff@test.example" } as { role: string; storeName: string; email: string } | null, checking: false, signOut: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => ({ replace: mockReplace }) }));
jest.mock("@/components/runtime", () => ({ useSession: () => mockSession, useApi: () => ({ data: null, error: null, loading: false }) }));
jest.mock("@/lib/api", () => ({ ...jest.requireActual("../src/lib/api"), apiFetch: jest.fn() }));
const send = jest.mocked(apiFetch);
afterEach(() => { jest.clearAllMocks(); mockSession = { user: { role: "STAFF", storeName: "テスト店舗", email: "staff@test.example" }, checking: false, signOut: jest.fn() }; });
test("staff guard hides content from a customer", async () => {
  mockSession.user = { role: "CUSTOMER", storeName: "", email: "buyer@test.example" };
  render(<StaffOnly><p>在庫編集フォーム</p></StaffOnly>);
  expect(screen.queryByText("在庫編集フォーム")).not.toBeInTheDocument();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/staff/login"));
});
test("unknown outcome retries the original payload and key, and rapid double clicks send once", async () => {
  let reject!: (reason: Error) => void;
  send.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
  const { result } = renderHook(() => useMutation());
  let first!: Promise<unknown>;
  act(() => { first = result.current.send("/api/v1/staff/pos/sales", { quantity: 2 }); void result.current.send("/api/v1/staff/pos/sales", { quantity: 2 }); });
  expect(send).toHaveBeenCalledTimes(1);
  await act(async () => { reject(new ApiError(0, "NETWORK_ERROR", "通信できませんでした")); await first; });
  const firstOptions = send.mock.calls[0][1];
  send.mockResolvedValueOnce({ saleId: "sale" });
  await act(async () => { await result.current.retry(); });
  expect(send.mock.calls[1][1]).toEqual(firstOptions);
  send.mockResolvedValueOnce({ saleId: "another" });
  await act(async () => { await result.current.send("/api/v1/staff/pos/sales", { quantity: 2 }); });
  expect(send.mock.calls[2][1]?.idempotencyKey).not.toBe(firstOptions?.idempotencyKey);
});
test("POS recovers a lost successful response even when refreshing the quote finds no remaining stock", async () => {
  const product = { productVariantId: "variant", sku: "P001", productName: "シャツ", colorName: "白", size: "M", priceYen: 1000, availableQuantity: 1 };
  const line = { ...product, unitPriceYen: 1000, quantity: 1, lineAmountYen: 1000, reservedQuantity: 0, ok: true, reasonCode: null };
  let estimates = 0;
  let sales = 0;
  send.mockImplementation(async (path) => {
    if (path.includes("/products?")) return { items: [product] };
    if (path.endsWith("/estimate")) { estimates++; return { lines: [{ ...line, ok: estimates === 1, availableQuantity: estimates === 1 ? 1 : 0, reasonCode: estimates === 1 ? null : "OUT_OF_STOCK" }], totalQuantity: 1, totalAmountYen: 1000, allOk: estimates === 1 }; }
    sales++; if (sales === 1) throw new ApiError(0, "NETWORK_ERROR", "通信できませんでした");
    return { saleId: "sale", saleNumber: "S000001" };
  });
  jest.spyOn(window, "confirm").mockReturnValue(true);
  render(<StaffPos/>);
  fireEvent.change(screen.getByLabelText("商品コード"), { target: { value: "P001" } });
  fireEvent.submit(screen.getByRole("button", { name: "追加" }).closest("form")!);
  await waitFor(() => expect(screen.getByRole("button", { name: "売上確定" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "売上確定" }));
  await waitFor(() => expect(screen.getByText("在庫不足")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "売上確定" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "再試行" }));
  expect(await screen.findByText("売上を登録しました（S000001）")).toBeInTheDocument();
  const calls = send.mock.calls.filter(([path]) => path === "/api/v1/staff/pos/sales");
  expect(calls).toHaveLength(2); expect(calls[0][1]).toEqual(calls[1][1]);
  jest.restoreAllMocks();
});
