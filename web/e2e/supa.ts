import fs from "node:fs";

const URL_ = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const SECRET = process.env.SUPABASE_SECRET_KEY!;
const H = { apikey: SECRET, Authorization: `Bearer ${SECRET}`, "Content-Type": "application/json" };
export const STATE_FILE = "/tmp/arena-e2e-state.json";
export const PASSWORD = "E2e-test-password-1";

export async function createUser(email: string, role: string) {
  const r = await fetch(`${URL_}/auth/v1/admin/users`, { method: "POST", headers: H, body: JSON.stringify({ email, password: PASSWORD, email_confirm: true }) });
  if (!r.ok) throw new Error(`create user failed: ${r.status}`);
  const { id } = await r.json();
  const p = await fetch(`${URL_}/rest/v1/profiles?id=eq.${id}`, { method: "PATCH", headers: H, body: JSON.stringify({ role }) });
  if (!p.ok) throw new Error(`profile update failed: ${p.status}`);
  return id as string;
}

export async function cleanup() {
  const rest = (path: string, method: string, body?: unknown) => fetch(`${URL_}/rest/v1/${path}`, { method, headers: H, body: body ? JSON.stringify(body) : undefined });
  await rest("teams?name=like.E2E*", "DELETE");
  await rest("questions?title=like.E2E*", "DELETE");
  await rest("contest_sessions?round=eq.1", "PATCH", { state: "DRAFT", starts_at: null, ends_at: null });
  const ids: string[] = fs.existsSync(STATE_FILE) ? JSON.parse(fs.readFileSync(STATE_FILE, "utf8")).users : [];
  const emails: string[] = fs.existsSync(STATE_FILE) ? JSON.parse(fs.readFileSync(STATE_FILE, "utf8")).emails : [];
  // account created through the UI during the test
  for (const e of emails) {
    const r = await rest(`profiles?email=eq.${encodeURIComponent(e)}&select=id`, "GET");
    for (const row of (await r.json()) as { id: string }[]) ids.push(row.id);
  }
  for (const id of ids) {
    await rest(`audit_logs?actor_id=eq.${id}`, "DELETE");
    await fetch(`${URL_}/auth/v1/admin/users/${id}`, { method: "DELETE", headers: H });
  }
  if (fs.existsSync(STATE_FILE)) fs.unlinkSync(STATE_FILE);
}
