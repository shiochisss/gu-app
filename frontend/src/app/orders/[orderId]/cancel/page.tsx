import { CancelOrder } from "@/components/customer-pickup";
export default async function Page({params}:{params:Promise<{orderId:string}>}){const {orderId}=await params;return <CancelOrder id={orderId}/>;}
