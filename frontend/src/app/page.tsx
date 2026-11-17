import { redirect } from "next/navigation";

/** The proxy sends visitors to /home or /login; this covers requests it does not see. */
export default function Index() {
  redirect("/home");
}
