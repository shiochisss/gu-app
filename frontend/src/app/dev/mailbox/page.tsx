import { notFound } from "next/navigation";
import { Mailbox } from "@/components/customer-orders";
export default function Page() { if (process.env.NEXT_PUBLIC_DEV_TOOLS_ENABLED !== "true") notFound(); return <Mailbox/>; }
