import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { AppProvider, useSession } from "../src/components/runtime";
import { apiFetch } from "../src/lib/api";
import type { UserInfo } from "../src/lib/types";
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
const staff: UserInfo = { userId: "staff", email: "staff@example.com", role: "STAFF", storeId: "store", storeName: "店舗" };
function Controls() {
  const session = useSession();
  return <><span>{session.user?.role ?? "anonymous"}</span><button onClick={() => session.setUser(staff)}>login</button><button onClick={() => void session.signOut()}>logout</button></>;
}
test.each(["login", "logout"])("late initial me cannot overwrite %s", async action => {
  let complete!: (user: UserInfo) => void;
  jest.mocked(apiFetch).mockImplementation(path => path === "/api/v1/auth/me" ? new Promise(resolve => { complete = resolve as (user: UserInfo) => void; }) : Promise.resolve({ items: [] }));
  render(<AppProvider><Controls /></AppProvider>);
  fireEvent.click(screen.getByText(action));
  await act(async () => { complete(action === "login" ? { ...staff, role: "CUSTOMER" } : staff); });
  await waitFor(() => expect(screen.getByText(action === "login" ? "STAFF" : "anonymous")).toBeInTheDocument());
});
