import type { ReactNode } from "react";
import { PickupProvider } from "@/components/pickup";
export default function Layout({children}:{children:ReactNode}){return <PickupProvider>{children}</PickupProvider>;}
