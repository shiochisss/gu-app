export type FieldError = { field: string; code: string; message: string };
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public fieldErrors: FieldError[] = [], public traceId?: string, public details: Record<string, unknown> | null = null, public latestResource: Record<string, unknown> | null = null) { super(message); }
}
export async function apiFetch<T>(path: string, options: { method?: string; body?: unknown; idempotencyKey?: string; signal?: AbortSignal } = {}): Promise<T> {
  if (!path.startsWith("/api/v1/")) throw new Error("API path must be same-origin");
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Requested-With": "pickup-app" };
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  let response: Response;
  try { response = await fetch(path, { method: options.method ?? "GET", headers, credentials: "same-origin", cache: "no-store", signal: options.signal, body: options.body === undefined ? undefined : JSON.stringify(options.body) }); }
  catch (error) { if (error instanceof DOMException && error.name === "AbortError") throw error; throw new ApiError(0, "NETWORK_ERROR", "通信できませんでした"); }
  if (response.status === 204) return undefined as T;
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, value?.code ?? "INTERNAL_ERROR", value?.message ?? "通信できませんでした", value?.fieldErrors ?? [], value?.traceId, value?.details ?? null, value?.latestResource ?? null);
  if (value === null) throw new ApiError(502, "INTERNAL_ERROR", "通信できませんでした");
  return value as T;
}
export function safeNext(value: string | undefined | null): string {
  if (!value?.startsWith("/")) return "/";
  let decoded = value;
  try { for (let i = 0; i < 2; i++) decoded = decodeURIComponent(decoded); } catch { return "/"; }
  if (decoded.startsWith("//") || /[\\\x00-\x1f\x7f]/.test(decoded)) return "/";
  try { return new URL(value, "https://pickup.invalid").origin === "https://pickup.invalid" ? value : "/"; } catch { return "/"; }
}
