import type { ReactNode } from "react";
import type { Metadata } from "next";
import { AppProvider } from "@/components/runtime";
import { AppShell } from "@/components/ui";
import "./globals.css";
export const metadata: Metadata = { title: "Pickup App | 店舗で受け取り", description: "お近くの店舗の商品を探して、店舗で受け取り。" };
export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="ja"><body><AppProvider><AppShell>{children}</AppShell></AppProvider></body></html>;
}
