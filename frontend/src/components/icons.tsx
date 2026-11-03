import type { SVGProps } from "react";
export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: "home" | "bag" | "orders" | "user" | "pin" | "arrow" | "search" | "back" | "check" | "clock" | "close" }) {
  const paths = {
    home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/><path d="M9 21v-8h6v8"/></>,
    bag: <><path d="M5 7h14l1 14H4Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/></>,
    orders: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>,
    pin: <><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/></>,
    arrow: <path d="m9 5 7 7-7 7"/>, back: <path d="m15 5-7 7 7 7"/>,
    search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>,
    check: <path d="m5 12 4 4L19 6"/>, clock: <><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...props}>{paths[name]}</svg>;
}
