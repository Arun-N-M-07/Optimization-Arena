import fs from "node:fs";
import { createUser, STATE_FILE } from "./supa";

export default async function setup() {
  const stamp = Date.now().toString(36);
  const admin = `e2e-admin-${stamp}@example.com`;
  const participant = `e2e-part-${stamp}@example.com`;
  const id = await createUser(admin, "ADMIN");
  fs.writeFileSync(STATE_FILE, JSON.stringify({ users: [id], emails: [participant], admin, participant }));
}
