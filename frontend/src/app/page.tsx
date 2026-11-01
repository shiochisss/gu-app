import { notFound } from "next/navigation";

// C-01 is implemented in step 4; do not expose a placeholder business screen.
export default function Page() {
  notFound();
}
