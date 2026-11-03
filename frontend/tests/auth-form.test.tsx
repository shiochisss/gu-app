import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthForm } from "../src/components/auth-form";
import { apiFetch } from "../src/lib/api";
const mockReplace = jest.fn(); const mockSetUser = jest.fn();
jest.mock("next/navigation", () => ({ useRouter: () => ({ replace: mockReplace }) }));
jest.mock("@/components/runtime", () => ({ useSession: () => ({ user: null, setUser: mockSetUser, signOut: jest.fn() }) }));
jest.mock("@/lib/api", () => ({ ...jest.requireActual("../src/lib/api"), apiFetch: jest.fn() }));
const send = jest.mocked(apiFetch);
afterEach(() => jest.clearAllMocks());
function fill() {
  fireEvent.change(screen.getByLabelText("メールアドレス"), { target: { value: "buyer@example.com" } });
  fireEvent.change(screen.getByLabelText("パスワード", { selector: "input" }), { target: { value: "a-private-test-password" } });
  fireEvent.submit(screen.getByRole("button", { name: "ログインする" }).closest("form")!);
}
test("C-05 login refuses an external next destination", async () => {
  send.mockResolvedValueOnce({ user: { userId: "user", email: "buyer@example.com", role: "CUSTOMER" } });
  render(<AuthForm kind="login" next="//evil.example"/>); fill();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/"));
  expect(mockSetUser).toHaveBeenCalled();
});
test("ST-01 rejects a customer and clears the session", async () => {
  send.mockResolvedValueOnce({ user: { userId: "user", email: "buyer@example.com", role: "CUSTOMER" } }).mockResolvedValueOnce(undefined);
  render(<AuthForm kind="staff"/>); fill();
  expect(await screen.findByRole("alert")).toHaveTextContent("店員アカウントでログインしてください");
  expect(send).toHaveBeenCalledWith("/api/v1/auth/logout", { method: "POST" });
  expect(mockSetUser).toHaveBeenCalledWith(null);
});
test("ST-01 routes authenticated staff to orders", async () => {
  send.mockResolvedValueOnce({ user: { userId: "staff", email: "staff@example.com", role: "STAFF", storeId: "store" } });
  render(<AuthForm kind="staff"/>); fill();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/staff/orders"));
});
