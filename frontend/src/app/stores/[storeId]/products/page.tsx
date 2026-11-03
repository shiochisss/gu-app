import { Products } from "@/components/products";
export default async function ProductsPage({ params }: { params: Promise<{ storeId: string }> }) { return <Products storeId={(await params).storeId}/>; }
