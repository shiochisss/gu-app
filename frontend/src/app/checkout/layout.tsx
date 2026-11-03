import type { ReactNode } from "react";
import { CheckoutProvider } from "@/components/checkout";
import { CustomerOnly } from "@/components/customer-common";
export default function Layout({ children }: { children: ReactNode }) { return <CustomerOnly><CheckoutProvider>{children}</CheckoutProvider></CustomerOnly>; }
