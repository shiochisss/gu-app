export function securityHeaders(development: boolean) {
  const scripts = `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ""} https://js.stripe.com https://*.js.stripe.com`;
  const csp = [
    "default-src 'self'", scripts, "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://*.stripe.com", "connect-src 'self' https://api.stripe.com",
    "frame-src https://js.stripe.com https://*.js.stripe.com https://hooks.stripe.com",
    "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'",
  ].join("; ");
  return [
    { key: "Content-Security-Policy", value: csp },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
  ];
}
