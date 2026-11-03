"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { useSession } from "./runtime";
import { ErrorPanel, Loading } from "./ui";
export function CustomerOnly({ children }: { children: ReactNode }) {
  const { user, checking } = useSession(); const router = useRouter(); const path = usePathname();
  useEffect(() => { if (!checking && !user) router.replace(`/login?next=${encodeURIComponent(path)}`); }, [checking, user, router, path]);
  if (checking || !user) return <Loading/>;
  if (user.role !== "CUSTOMER") return <ErrorPanel error={new Error("購入者アカウントでログインしてください")}/>;
  return children;
}
