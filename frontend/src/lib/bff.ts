import { createHash, randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

type User = { userId: string; email: string; role: string; storeId?: string | null; storeName?: string | null };
type Tokens = { user: User; accessToken: string; refreshToken: string };
type Config = { backendBaseUrl: string; frontendBaseUrl: string; sharedSecret: string; fetchImpl?: typeof fetch };
const uuid = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const routes: [string, RegExp][] = [
  ["GET", /^\/api\/v1\/staff\/(orders|store)$/],
  ["GET", new RegExp(`^/api/v1/staff/orders/${uuid}$`)],
  ["POST", /^\/api\/v1\/staff\/pickups\/verify$/],
  ["POST", new RegExp(`^/api/v1/staff/orders/${uuid}/(preparation/start|shortages|delay|ready|return-to-stock|handover)$`)],
  ["POST", new RegExp(`^/api/v1/orders/${uuid}/(cancel|pickup-token/reissue)$`)],
  ["PUT", /^\/api\/v1\/staff\/store\/acceptance$/],
  ["PUT", /^\/api\/v1\/staff\/store\/business-hours\/[0-9]{4}-[0-9]{2}-[0-9]{2}$/],
  ["POST", /^\/api\/v1\/orders(?:\/estimate)?$/],
  ["GET", /^\/api\/v1\/(orders|dev\/mails)$/],
  ["GET", new RegExp(`^/api/v1/orders/${uuid}$`)],
  ["POST", new RegExp(`^/api/v1/orders/${uuid}/payment/refresh$`)],
  ["GET", /^\/api\/v1\/staff\/(products|inventories|pos\/sales)$/],
  ["POST", /^\/api\/v1\/staff\/pos\/sales(?:\/estimate)?$/],
  ["POST", new RegExp(`^/api/v1/staff/pos/sales/${uuid}/void$`)],
  ["GET", new RegExp(`^/api/v1/staff/inventories/${uuid}/transactions$`)],
  ["POST", new RegExp(`^/api/v1/staff/inventories/${uuid}/(receipts|adjustments)$`)],
  ["POST", /^\/api\/v1\/auth\/(register|login|refresh|logout)$/],
  ["GET", /^\/api\/v1\/auth\/me$/],
  ["GET", /^\/api\/v1\/stores$/],
  ["GET", new RegExp(`^/api/v1/stores/${uuid}/products(?:/${uuid})?$`)],
];

export function createBff(config: Config) {
  const send = config.fetchImpl ?? fetch;
  const frontend = new URL(config.frontendBaseUrl);
  const backend = new URL(config.backendBaseUrl);
  if (!["http:", "https:"].includes(backend.protocol) || backend.username || backend.password) throw new Error("Invalid backend URL");
  const secure = !(frontend.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(frontend.hostname));
  const refreshes = new Map<string, { promise: Promise<Tokens | null>; until: number; revoked: boolean }>();
  const revokedTokens = new WeakSet<Tokens>();
  const refreshKey = (raw: string) => createHash("sha256").update(raw).digest("hex");

  function error(status: number, code: string, message: string, traceId: string) {
    return NextResponse.json({ code, message, details: null, fieldErrors: [], traceId, latestResource: null }, { status });
  }
  function cookies(response: NextResponse, tokens: Tokens | null) {
    response.cookies.set("pa_at", tokens?.accessToken ?? "", { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: tokens ? 900 : 0 });
    response.cookies.set("pa_rt", tokens?.refreshToken ?? "", { httpOnly: true, secure, sameSite: "strict", path: "/api/v1", maxAge: tokens ? 604800 : 0 });
  }
  async function refresh(raw: string, traceId: string) {
    const key = refreshKey(raw);
    const now = Date.now();
    for (const [id, item] of refreshes) if (item.until <= now) refreshes.delete(id);
    const current = refreshes.get(key);
    if (current) return current.revoked ? null : current.promise;
    const promise = (async (): Promise<Tokens | null> => {
      try {
        const result = await send(new URL("/api/v1/auth/refresh", backend), {
          method: "POST", headers: { "Content-Type": "application/json", "X-BFF-Secret": config.sharedSecret, "X-Request-Id": traceId },
          body: JSON.stringify({ refreshToken: raw }), cache: "no-store", signal: AbortSignal.timeout(15000),
        });
        if (!result.ok) return null;
        const value = await result.json();
        return typeof value.accessToken === "string" && typeof value.refreshToken === "string" && value.user ? value as Tokens : null;
      } catch { return null; }
    })();
    if (refreshes.size >= 500) refreshes.delete(refreshes.keys().next().value!);
    const entry = { promise, until: now + 30000, revoked: false };
    refreshes.set(key, entry);
    void promise.then(value => { entry.until = Date.now() + 30000; if (entry.revoked && value) revokedTokens.add(value); });
    return promise;
  }

  return async function handle(request: NextRequest): Promise<NextResponse> {
    const incomingId = request.headers.get("X-Request-Id") ?? "";
    const traceId = new RegExp(`^${uuid}$`).test(incomingId) ? incomingId : randomUUID();
    const finish = (response: NextResponse) => { response.headers.set("X-Request-Id", traceId); response.headers.set("Cache-Control", "no-store"); return response; };
    const path = request.nextUrl.pathname;
    if (!routes.some(([method, pattern]) => method === request.method && pattern.test(path))) {
      return finish(error(404, "NOT_FOUND", "対象が見つかりません。", traceId));
    }
    if (request.method !== "GET" && (request.headers.get("Origin") !== frontend.origin || request.headers.get("X-Requested-With") !== "pickup-app")) {
      return finish(error(403, "CSRF_REJECTED", "画面を再読み込みしてから、もう一度お試しください。", traceId));
    }
    const rawRefresh = request.cookies.get("pa_rt")?.value;
    let access = request.cookies.get("pa_at")?.value;
    let updated: Tokens | null | undefined;
    let attemptedRefresh = false;
    const apply = (response: NextResponse) => { if (updated !== undefined) cookies(response, updated && revokedTokens.has(updated) ? null : updated); return finish(response); };

    if (path === "/api/v1/auth/logout") {
      const pending = rawRefresh ? refreshes.get(refreshKey(rawRefresh)) : undefined;
      if (pending) pending.revoked = true;
      const revoke = async (raw: string) => {
        try { await send(new URL(path, backend), { method: "POST", headers: { "Content-Type": "application/json", "X-BFF-Secret": config.sharedSecret, "X-Request-Id": traceId }, body: JSON.stringify({ refreshToken: raw }), signal: AbortSignal.timeout(15000) }); } catch { /* Cookies must still be removed. */ }
      };
      await revoke(rawRefresh ?? "");
      const successor = await pending?.promise;
      if (successor) { revokedTokens.add(successor); await revoke(successor.refreshToken); }
      const response = new NextResponse(null, { status: 204 }); cookies(response, null); return finish(response);
    }
    if (path === "/api/v1/auth/refresh") {
      updated = rawRefresh ? await refresh(rawRefresh, traceId) : null;
      return apply(updated ? NextResponse.json({ user: updated.user }) : error(401, "UNAUTHENTICATED", "ログインしてください。", traceId));
    }
    const authEntry = path === "/api/v1/auth/login" || path === "/api/v1/auth/register";
    if (!authEntry && !access && rawRefresh) {
      attemptedRefresh = true; updated = await refresh(rawRefresh, traceId); access = updated?.accessToken;
    }
    const body = request.method === "GET" ? undefined : await request.text();
    const headers = new Headers({ "Content-Type": request.headers.get("Content-Type") ?? "application/json", "X-BFF-Secret": config.sharedSecret, "X-Request-Id": traceId });
    const idempotency = request.headers.get("Idempotency-Key");
    if (idempotency) headers.set("Idempotency-Key", idempotency);
    if (access && !authEntry) headers.set("Authorization", `Bearer ${access}`);
    const target = new URL(path + request.nextUrl.search, backend);
    const forward = () => send(target, { method: request.method, headers, body, cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(15000) });
    try {
      let result = await forward();
      if (!authEntry && result.status === 401 && rawRefresh && !attemptedRefresh) {
        const failure = await result.clone().json().catch(() => ({}));
        if (["UNAUTHENTICATED", "TOKEN_EXPIRED"].includes(failure.code)) {
          attemptedRefresh = true; updated = await refresh(rawRefresh, traceId);
          if (!updated) return apply(error(401, "UNAUTHENTICATED", "ログインしてください。", traceId));
          headers.set("Authorization", `Bearer ${updated.accessToken}`); result = await forward();
        }
      }
      if (authEntry && result.ok) {
        const value = await result.json() as Tokens;
        if (!value.accessToken || !value.refreshToken || !value.user) throw new Error("Invalid auth response");
        updated = value; return apply(NextResponse.json({ user: value.user }, { status: result.status }));
      }
      const response = new NextResponse(result.status === 204 ? null : await result.text(), { status: result.status, headers: { "Content-Type": result.headers.get("Content-Type") ?? "application/json" } });
      const retryAfter = result.headers.get("Retry-After"); if (retryAfter) response.headers.set("Retry-After", retryAfter);
      return apply(response);
    } catch {
      return apply(error(502, "INTERNAL_ERROR", "通信できませんでした。もう一度お試しください。", traceId));
    }
  };
}
