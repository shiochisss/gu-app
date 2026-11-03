import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import RootLayout from "../src/app/layout";

jest.mock("@/components/runtime", () => ({ AppProvider: ({ children }: { children: ReactNode }) => children }));
jest.mock("@/components/ui", () => ({ AppShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
test("共通レイアウトが日本語を指定し子要素を表示する", () => {
  render(<RootLayout><p>テスト内容</p></RootLayout>, { container: document });
  expect(document.documentElement.lang).toBe("ja");
  expect(screen.getByRole("main")).toHaveTextContent("テスト内容");
});
