import { StaffInventoryDetail } from "@/components/staff-inventory";
export default async function Page({ params }: { params: Promise<{ inventoryId: string }> }) { const { inventoryId } = await params; return <StaffInventoryDetail id={inventoryId}/>; }
