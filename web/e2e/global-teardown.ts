import { cleanup } from "./supa";

export default async function teardown() {
  await cleanup();
}
