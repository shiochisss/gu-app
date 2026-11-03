import { NextRequest } from "next/server";
import { createBff } from "@/lib/bff";

export const runtime = "nodejs";
let handler: ReturnType<typeof createBff> | undefined;
function handle(request: NextRequest) {
  if (!handler) {
    const backendBaseUrl = process.env.BACKEND_BASE_URL;
    const frontendBaseUrl = process.env.FRONTEND_BASE_URL;
    const sharedSecret = process.env.BFF_SHARED_SECRET;
    if (!backendBaseUrl || !frontendBaseUrl || !sharedSecret) return Response.json({ code: "INTERNAL_ERROR", message: "接続設定を確認してください。" }, { status: 503 });
    handler = createBff({ backendBaseUrl, frontendBaseUrl, sharedSecret });
  }
  return handler(request);
}
export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const DELETE = handle;
export const PATCH = handle;
