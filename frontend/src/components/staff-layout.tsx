"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { StaffOnly } from "./staff-common";
export function StaffLayout({ children }: { children: ReactNode }) {
  return usePathname() === "/staff/login" ? children : <StaffOnly>{children}</StaffOnly>;
}
