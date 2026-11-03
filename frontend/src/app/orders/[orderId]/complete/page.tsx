import { OrderResult } from "@/components/customer-orders";
export default async function Page({ params }: { params: Promise<{ orderId: string }> }) { const { orderId } = await params; return <OrderResult id={orderId}/>; }
