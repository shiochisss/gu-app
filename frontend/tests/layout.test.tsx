import { render, screen } from "@testing-library/react";
import RootLayout from "../src/app/layout";

test("共通レイアウトが日本語を指定し子要素を表示する", () => {
  render(<RootLayout><main>テスト内容</main></RootLayout>, { container: document });
  expect(document.documentElement.lang).toBe("ja");
  expect(screen.getByRole("main")).toHaveTextContent("テスト内容");
});
