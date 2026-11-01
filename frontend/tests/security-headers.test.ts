import { securityHeaders } from "../src/lib/security-headers";

test("公開用CSPでStripeと3Dセキュアを許可し、埋め込みとevalを防ぐ", () => {
  const headers = Object.fromEntries(securityHeaders(false).map(({ key, value }) => [key, value]));
  expect(headers["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
  expect(headers["Content-Security-Policy"]).toContain("https://hooks.stripe.com");
  expect(headers["Content-Security-Policy"]).toContain("https://*.js.stripe.com");
  expect(headers["Content-Security-Policy"]).not.toContain("'unsafe-eval'");
  expect(headers["X-Content-Type-Options"]).toBe("nosniff");
  expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["Permissions-Policy"]).toBe("camera=(self), microphone=(), geolocation=()");
});
test("開発中だけevalを許可する", () => {
  expect(securityHeaders(true)[0].value).toContain("'unsafe-eval'");
});
