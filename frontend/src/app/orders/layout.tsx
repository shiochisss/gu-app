import type { ReactNode } from "react";
import { CustomerOnly } from "@/components/customer-common";
export default function Layout({ children }: { children: ReactNode }) { return <CustomerOnly>{children}</CustomerOnly>; }
