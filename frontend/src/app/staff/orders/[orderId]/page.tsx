import { StaffOrder } from "@/components/staff-operations";
export default async function Page({params}:{params:Promise<{orderId:string}>}){const {orderId}=await params;return <StaffOrder id={orderId} mode="detail"/>;}
