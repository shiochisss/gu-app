/** @jest-environment node */
import { NextRequest } from "next/server";
import { proxy } from "../src/proxy";
test("canonical loopback GET does not redirect to itself after NextURL normalization", () => {
  const previous = process.env.FRONTEND_BASE_URL;
  process.env.FRONTEND_BASE_URL = "http://127.0.0.1:53000";
  try {
    const response = proxy(new NextRequest("http://localhost:53000/", { headers: { host: "127.0.0.1:53000" } }));
    expect(response.headers.get("location")).toBeNull();
    const alias = proxy(new NextRequest("http://localhost:53000/", { headers: { host: "localhost:53000" } }));
    expect(alias.headers.get("location")).toBe("http://127.0.0.1:53000/");
  } finally { if (previous === undefined) delete process.env.FRONTEND_BASE_URL; else process.env.FRONTEND_BASE_URL = previous; }
});
