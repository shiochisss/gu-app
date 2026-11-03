/** @jest-environment node */
import { NextRequest } from "next/server";
import { createBff } from "../src/lib/bff";

const user = { userId: "test-user", email: "test@example.com", role: "CUSTOMER", storeId: null };
const bundle = { user, accessToken: "new-access", refreshToken: "new-refresh" };
function request(path: string, method = "GET", headers: Record<string, string> = {}, body?: object) {
  return new NextRequest("http://localhost:3000/api/v1/" + path, { method, headers: { Origin: "http://localhost:3000", "X-Requested-With": "pickup-app", "Content-Type": "application/json", ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
}
function setup(fn: typeof fetch) { return createBff({ backendBaseUrl: "http://backend.test", frontendBaseUrl: "http://localhost:3000", sharedSecret: "server-only-secret", fetchImpl: fn }); }

test.each<Record<string, string>>([{ Origin: "https://evil.example" }, { "X-Requested-With": "wrong" }])("FT-08 refuses CSRF before forwarding", async headers => {
  const send = jest.fn(); const response = await setup(send)(request("auth/login", "POST", headers, {}));
  expect(response.status).toBe(403); expect((await response.json()).code).toBe("CSRF_REJECTED"); expect(send).not.toHaveBeenCalled();
});
test.each(["payments/webhook", "internal/jobs/run", "unknown", "stores/../../internal/jobs/run"])("FT-09 refuses an unlisted path %s", async path => {
  const send = jest.fn(); expect((await setup(send)(request(path, "POST", {}, {}))).status).toBe(404); expect(send).not.toHaveBeenCalled();
});
test("FT-10 moves tokens into HttpOnly cookies and strips them from JSON", async () => {
  const send = jest.fn().mockResolvedValue(Response.json(bundle));
  const response = await setup(send)(request("auth/login", "POST", {}, { email: "test@example.com", password: "a-test-only-password" }));
  expect(await response.json()).toEqual({ user });
  const cookies = response.headers.get("set-cookie")!;
  expect(cookies).toContain("HttpOnly"); expect(cookies).toContain("SameSite=lax"); expect(cookies).toContain("SameSite=strict"); expect(cookies).toContain("Path=/api/v1"); expect(cookies).not.toContain("Secure");
});
test("FT-10 forwards only allowed headers and cookie-derived authorization", async () => {
  const send = jest.fn().mockResolvedValue(Response.json(user));
  await setup(send)(request("auth/me", "GET", { Cookie: "pa_at=good-access; extra=private", Authorization: "Bearer attacker", "X-Other": "must-not-forward" }));
  const headers = send.mock.calls[0][1].headers as Headers;
  expect(headers.get("Authorization")).toBe("Bearer good-access"); expect(headers.get("X-BFF-Secret")).toBe("server-only-secret"); expect(headers.get("Cookie")).toBeNull(); expect(headers.get("X-Other")).toBeNull();
});
test("FT-11 refreshes and retries once with identical idempotency key", async () => {
  const send = jest.fn().mockResolvedValueOnce(Response.json({ code: "TOKEN_EXPIRED" }, { status: 401 })).mockResolvedValueOnce(Response.json(bundle)).mockResolvedValueOnce(Response.json(user));
  const response = await setup(send)(request("auth/me", "GET", { Cookie: "pa_at=old; pa_rt=refresh", "Idempotency-Key": "same-operation" }));
  expect(response.status).toBe(200); expect(send).toHaveBeenCalledTimes(3);
  expect((send.mock.calls[2][1].headers as Headers).get("Idempotency-Key")).toBe("same-operation");
  expect((send.mock.calls[2][1].headers as Headers).get("Authorization")).toBe("Bearer new-access");
});
test("FT-12 deduplicates three concurrent refresh calls", async () => {
  let refreshes = 0;
  const send = jest.fn(async (url: URL | RequestInfo, options?: RequestInit) => {
    if (String(url).endsWith("/auth/refresh")) { refreshes++; await Promise.resolve(); return Response.json(bundle); }
    return new Headers(options?.headers).get("Authorization") === "Bearer new-access" ? Response.json(user) : Response.json({ code: "TOKEN_EXPIRED" }, { status: 401 });
  }) as unknown as typeof fetch;
  const handle = setup(send);
  const responses = await Promise.all([1, 2, 3].map(() => handle(request("auth/me", "GET", { Cookie: "pa_at=old; pa_rt=refresh" }))));
  expect(responses.every(value => value.status === 200)).toBe(true); expect(refreshes).toBe(1);
});
test("BND-F08 retry stops after a second 401", async () => {
  const send = jest.fn().mockResolvedValueOnce(Response.json({ code: "TOKEN_EXPIRED" }, { status: 401 })).mockResolvedValueOnce(Response.json(bundle)).mockResolvedValueOnce(Response.json({ code: "UNAUTHENTICATED" }, { status: 401 }));
  expect((await setup(send)(request("auth/me", "GET", { Cookie: "pa_at=old; pa_rt=refresh" }))).status).toBe(401);
  expect(send).toHaveBeenCalledTimes(3);
});
test("failed preemptive refresh clears cookies and continues a public GET anonymously", async () => {
  const send = jest.fn().mockResolvedValueOnce(Response.json({}, { status: 401 })).mockResolvedValueOnce(Response.json({ items: [] }));
  const response = await setup(send)(request("stores", "GET", { Cookie: "pa_rt=old" }));
  expect(response.status).toBe(200); expect(response.headers.get("set-cookie")).toContain("Max-Age=0"); expect((send.mock.calls[1][1].headers as Headers).has("Authorization")).toBe(false);
});
test("logout removes cookies even if the backend is unavailable", async () => {
  const send = jest.fn().mockRejectedValue(new Error("offline"));
  const response = await setup(send)(request("auth/logout", "POST", { Cookie: "pa_rt=old" }, {}));
  expect(response.status).toBe(204); expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
});
test("HTTPS cookies have Secure", async () => {
  const handle = createBff({ backendBaseUrl: "https://back.test", frontendBaseUrl: "https://front.test", sharedSecret: "private", fetchImpl: jest.fn().mockResolvedValue(Response.json(bundle)) });
  const response = await handle(new NextRequest("https://front.test/api/v1/auth/login", { method: "POST", headers: { Origin: "https://front.test", "X-Requested-With": "pickup-app" }, body: "{}" }));
  expect(response.headers.get("set-cookie")).toContain("Secure"); expect(await response.text()).not.toContain("new-access");
});
test("logout invalidates a pending refresh and revokes its successor", async () => {
  let complete!: (value: Response) => void;
  const revoked: string[] = [];
  const send = jest.fn(async (url: URL | RequestInfo, options?: RequestInit) => {
    if (String(url).endsWith("/auth/refresh")) return new Promise<Response>(resolve => { complete = resolve; });
    if (String(url).endsWith("/auth/logout")) { revoked.push(JSON.parse(options!.body as string).refreshToken); return new Response(null, { status: 204 }); }
    return Response.json(user);
  }) as unknown as typeof fetch;
  const handle = setup(send);
  const pending = handle(request("auth/me", "GET", { Cookie: "pa_rt=old" }));
  const logout = handle(request("auth/logout", "POST", { Cookie: "pa_rt=old" }, {}));
  complete(Response.json(bundle));
  const [response, loggedOut] = await Promise.all([pending, logout]);
  expect(loggedOut.status).toBe(204);
  expect(revoked).toEqual(["old", "new-refresh"]);
  expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  expect(response.headers.get("set-cookie")).not.toContain("new-refresh");
});

test.each([
  ["GET", "staff/products"], ["GET", "staff/inventories"], ["GET", "staff/pos/sales"],
  ["POST", "staff/pos/sales/estimate"], ["POST", "staff/pos/sales"],
  ["POST", "staff/pos/sales/11111111-1111-4111-8111-111111111111/void"],
  ["GET", "staff/inventories/11111111-1111-4111-8111-111111111111/transactions"],
  ["POST", "staff/inventories/11111111-1111-4111-8111-111111111111/receipts"],
  ["POST", "staff/inventories/11111111-1111-4111-8111-111111111111/adjustments"],
])("Step5 forwards %s %s with the original operation key", async (method, path) => {
  const send = jest.fn().mockResolvedValue(Response.json({ ok: true }));
  const response = await setup(send)(request(path, method, { Cookie: "pa_at=staff-token", "Idempotency-Key": "operation-key" }, method === "POST" ? { quantity: 2 } : undefined));
  expect(response.status).toBe(200);
  expect((send.mock.calls[0][1].headers as Headers).get("Idempotency-Key")).toBe("operation-key");
});

test.each([
  ["POST", "orders/estimate"], ["POST", "orders"], ["GET", "orders"], ["GET", "dev/mails"],
  ["GET", "orders/11111111-1111-4111-8111-111111111111"],
  ["POST", "orders/11111111-1111-4111-8111-111111111111/payment/refresh"],
])("Step6 forwards %s %s without opening webhook routes", async (method, path) => {
  const send = jest.fn().mockResolvedValue(Response.json({ ok: true }));
  expect((await setup(send)(request(path, method, { Cookie: "pa_at=buyer-token" }, method === "POST" ? {} : undefined))).status).toBe(200);
  expect(send).toHaveBeenCalledTimes(1);
});

test.each([
  ["GET","staff/orders"],["GET","staff/store"],
  ["GET","staff/orders/11111111-1111-4111-8111-111111111111"],
  ["POST","staff/orders/11111111-1111-4111-8111-111111111111/preparation/start"],
  ["POST","staff/orders/11111111-1111-4111-8111-111111111111/shortages"],
  ["POST","staff/orders/11111111-1111-4111-8111-111111111111/delay"],
  ["POST","staff/orders/11111111-1111-4111-8111-111111111111/ready"],
  ["POST","staff/orders/11111111-1111-4111-8111-111111111111/return-to-stock"],
  ["POST","staff/orders/11111111-1111-4111-8111-111111111111/handover"],
  ["POST","staff/pickups/verify"],
  ["POST","orders/11111111-1111-4111-8111-111111111111/cancel"],
  ["POST","orders/11111111-1111-4111-8111-111111111111/pickup-token/reissue"],
  ["PUT","staff/store/acceptance"],["PUT","staff/store/business-hours/2026-11-03"],
])("remaining workflow forwards %s %s",async(method,path)=>{
  const send=jest.fn().mockResolvedValue(Response.json({ok:true}));
  expect((await setup(send)(request(path,method,{Cookie:"pa_at=token"},method==="GET"?undefined:{}))).status).toBe(200);
});
