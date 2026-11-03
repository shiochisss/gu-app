import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StaffOrder } from "../src/components/staff-operations";
import { CustomerPickup, CancelOrder } from "../src/components/customer-pickup";
import { PickupProvider, PickupScanner, PickupConfirm } from "../src/components/pickup";
import { apiFetch } from "../src/lib/api";
const mockPush=jest.fn(); const mockReplace=jest.fn(); const mockRetry=jest.fn();
const mockStop=jest.fn(); const mockCamera=jest.fn();
let mockData: Record<string,unknown>;
jest.mock("next/navigation",()=>({useRouter:()=>({push:mockPush,replace:mockReplace})}));
jest.mock("@/components/runtime",()=>({useApi:()=>({data:mockData,loading:false,error:null,retry:mockRetry})}));
jest.mock("@/lib/api",()=>({...jest.requireActual("../src/lib/api"),apiFetch:jest.fn()}));
jest.mock("@zxing/browser",()=>({BrowserQRCodeReader:class{decodeFromConstraints(...args:unknown[]){return mockCamera(...args);}}}));
const send=jest.mocked(apiFetch);
const order={orderId:"order",orderNumber:"P000001",version:3,status:"PREPARING",statusLabel:"準備中",shortagePolicy:"PURCHASE_AVAILABLE",paymentStatus:"AUTHORIZED",paymentStatusLabel:"カード利用枠確保済み",payment:{capturedAmountYen:0},allowedActions:["MARK_READY"],items:[{orderItemId:"item",productName:"シャツ",colorName:"白",size:"M",sku:"SKU",orderedQuantity:2,shortageQuantity:1,unitPriceYen:990,onHandQuantity:2,shortageRiskQuantity:0}],delays:[],canCancel:false};
beforeEach(()=>{jest.clearAllMocks();mockData={...order};mockCamera.mockResolvedValue({stop:mockStop});jest.spyOn(window,"confirm").mockReturnValue(true);});
afterEach(()=>jest.restoreAllMocks());
test("preparation confirms only the remaining amount and sends the displayed version",async()=>{
  send.mockResolvedValue({status:"READY"});render(<StaffOrder id="order"/>);
  expect(screen.queryByRole("button",{name:"準備開始"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"準備完了（決済確定）"}));
  await waitFor(()=>expect(mockRetry).toHaveBeenCalled());
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("¥990"));
  expect(send).toHaveBeenCalledWith("/api/v1/staff/orders/order/ready",expect.objectContaining({body:{version:3},idempotencyKey:expect.any(String)}));
});
test("customer can reissue a visible pickup QR with a confirmation",async()=>{
  const data={...order,pickup:{qrValue:"PA1.signed.test",manualCode:"001234"},canReissuePickupCode:true};
  send.mockResolvedValue({});
  render(<CustomerPickup order={data as unknown as Parameters<typeof CustomerPickup>[0]["order"]} refresh={mockRetry}/>);
  expect(screen.getByText(/001234/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"QRを再発行"}));
  await waitFor(()=>expect(mockRetry).toHaveBeenCalled());
  expect(window.confirm).toHaveBeenCalledWith("再発行すると、以前のQRは使えなくなります");
});
test("a non-cancellable order cannot send a cancellation",()=>{
  render(<CancelOrder id="order"/>);
  expect(screen.getByRole("button",{name:"取り消す"})).toBeDisabled();
  expect(send).not.toHaveBeenCalled();
});
test("camera failure leaves manual entry available",async()=>{
  mockCamera.mockRejectedValueOnce(new Error("camera blocked"));
  render(<PickupProvider><PickupScanner/></PickupProvider>);
  fireEvent.click(screen.getByRole("button",{name:"カメラでQRを読み取る"}));
  expect(await screen.findByText("カメラを使えません。手入力してください")).toBeInTheDocument();
  expect(screen.getByLabelText("受取コード（6桁）")).toBeEnabled();
});
test("manual verification preserves leading zeros and handover uses the verified token and version",async()=>{
  send.mockResolvedValueOnce({canHandOver:true,orderId:"order",orderNumber:"P000001",version:7,pickupVerificationId:"token",items:[],capturedAmountYen:990,status:"READY"}).mockResolvedValueOnce({status:"PICKED_UP"});
  render(<PickupProvider><PickupScanner/><PickupConfirm/></PickupProvider>);
  fireEvent.change(screen.getByLabelText("注文番号"),{target:{value:"P000001"}});
  fireEvent.change(screen.getByLabelText("受取コード（6桁）"),{target:{value:"001234"}});
  fireEvent.submit(screen.getByRole("button",{name:"照合する"}).closest("form")!);
  const handover=await screen.findByRole("button",{name:"商品を渡した（受け取り完了）"});
  expect(send.mock.calls[0][1]?.body).toEqual({orderNumber:"P000001",manualCode:"001234"});
  fireEvent.click(handover);
  expect(await screen.findByText("受け取りを完了しました")).toBeInTheDocument();
  expect(send.mock.calls[1][1]?.body).toEqual({version:7,pickupVerificationId:"token"});
});
test("camera controls stop when leaving the pickup screen",async()=>{
  const view=render(<PickupProvider><PickupScanner/></PickupProvider>);
  fireEvent.click(screen.getByRole("button",{name:"カメラでQRを読み取る"}));
  await act(async()=>{});view.unmount();expect(mockStop).toHaveBeenCalled();
});
test("capture stock errors show the affected item and ask for shortage registration",async()=>{
  const {ApiError}=jest.requireActual("../src/lib/api");
  send.mockRejectedValueOnce(new ApiError(409,"INSUFFICIENT_STOCK","在庫不足",[],undefined,{items:[{orderItemId:"item",onHandQuantity:0,requiredQuantity:1}]}));
  render(<StaffOrder id="order"/>);
  fireEvent.click(screen.getByRole("button",{name:"準備完了（決済確定）"}));
  expect(await screen.findByText("帳簿在庫が足りない商品があります。欠品を登録してください")).toBeInTheDocument();
  expect(screen.getByText("シャツ：帳簿在庫 0点／必要 1点")).toBeInTheDocument();
});
