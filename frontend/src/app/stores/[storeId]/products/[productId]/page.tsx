import { ProductDetail } from "@/components/product-detail";
export default async function ProductPage({ params }: { params: Promise<{ storeId: string; productId: string }> }) { const { storeId, productId } = await params; return <ProductDetail storeId={storeId} productId={productId}/>; }
