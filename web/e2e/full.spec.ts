/**
 * REAL end-to-end: real Next.js + real FastAPI + real Supabase (Auth, Postgres, Realtime) + real Gemini.
 * Judge = MOCK provider (no sandbox exists), so code "results" are asserted only as clearly-labelled mocks.
 * One serial story: admin set-up -> participant workspace -> judge review -> results -> Round 2 -> projector -> security.
 */
import fs from "node:fs";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { PASSWORD, STATE_FILE } from "./supa";

test.describe.configure({ mode: "serial" });

const state = () => JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as { admin: string; participant: string; judge: string };
const TEAM_NO = String(6000 + Math.floor(Math.random() * 999));
const TEAM = "E2E Falcons";
const HIDDEN = "E2E-HIDDEN-SECRET-5521";
const REF = "E2E-REFERENCE-SECRET-8830";
const SECTIONS = {
  inefficiency: "The original uses two nested loops that compare every pair, so the work grows quadratically with the list size.",
  approach: "We store seen values in a set and return at the first repeat, so each element is examined once and behaviour is unchanged.",
  complexity: "Original: O(n^2) time and O(1) space. Optimized: O(n) time on average and O(n) extra space for the set.",
  tradeoffs: "We spend extra memory on the set to gain linear time; for tiny inputs the simple loop is equally fast and simpler.",
};

let admin: Page, part: Page, judge: Page;
const ctxs: BrowserContext[] = [];

async function newPage(browser: Browser) {
  const c = await browser.newContext();
  ctxs.push(c);
  return c.newPage();
}
async function login(page: Page, email: string, to: RegExp) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(to, { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
}
/** Click a header link, then wait for hydration/data so forms are interactive before the next step. */
async function nav(p: Page, name: string) {
  await p.locator("header").getByRole("link", { name, exact: true }).click();
  await p.waitForLoadState("networkidle");
}
async function go(p: Page, url: string) {
  await p.goto(url);
  await p.waitForLoadState("networkidle");
}
const shot = (p: Page, name: string) => p.screenshot({ path: `test-results/screens/${name}.png`, fullPage: false });
const alertText = (p: Page) => p.locator("p[role=alert]");
const editorValue = (p: Page) => p.evaluate(() => (window as unknown as { monaco: { editor: { getModels: () => { getValue: () => string }[] } } }).monaco.editor.getModels()[0].getValue());
async function typeInEditor(p: Page, text: string) {
  await p.locator(".monaco-editor .view-lines").first().click();
  await p.keyboard.press("ControlOrMeta+a");
  await p.keyboard.type(text);
}

async function addQuestion(page: Page, category: string, label: string) {
  await page.getByLabel("Category").selectOption(category);
  await page.getByLabel("Title").fill(`E2E ${category} question`);
  await page.getByRole("button", { name: "Create question" }).click();
  const card = page.locator("section", { hasText: `E2E ${category} question` });
  await card.getByRole("button", { name: "Add variant" }).click();
  await card.getByLabel("Label (e.g. A)").fill(label);
  await card.getByLabel("Problem description").fill(`Optimise the ${category} code so it scales to large inputs.`);
  await card.getByLabel("Expected behaviour").fill("Same output as before.");
  await card.getByLabel("Constraints").fill("n <= 100000");
  await card.getByLabel("Original (inefficient) code").fill(`# ORIGINAL ${category} slow()`);
  await card.getByLabel("Visible test input").fill("1 2 3");
  await card.getByLabel("Visible test expected output").fill("6");
  await card.getByLabel("Hidden test input (server only)").fill(HIDDEN);
  await card.getByLabel("Hidden test expected output (server only)").fill("42");
  await card.getByLabel("Reference solution (server only)").fill(REF);
  await card.getByLabel("Expected complexity").fill("O(n)");
  await card.getByRole("button", { name: "Create variant" }).click();
  await expect(card.locator("li", { hasText: `Variant ${label}` })).toBeVisible();
  await card.getByRole("button", { name: "Publish" }).first().click();
  await expect(card.getByText(/PUBLISHED/).first()).toBeVisible();
  await card.locator("li").getByRole("button", { name: "Publish" }).click();
  await expect(card.locator("li").getByText("PUBLISHED")).toBeVisible();
}

test.beforeAll(async ({ browser }) => {
  admin = await newPage(browser); part = await newPage(browser); judge = await newPage(browser);
  for (const p of [admin, part, judge]) p.on("dialog", (d) => void d.accept());   // confirm() prompts and beforeunload
});
test.afterAll(async () => { for (const c of ctxs) await c.close(); });

// ============================ ADMIN SET-UP ============================
test("A1 admin: team, members, participant and judge accounts, questions, assignments, start Round 1", async () => {
  const { admin: email, participant, judge: judgeEmail } = state();
  await login(admin, email, /\/admin$/);
  await expect(admin.getByRole("heading", { name: "Admin overview" })).toBeVisible();
  await expect(admin.getByText("System status")).toBeVisible();
  await expect(admin.getByText(/Code judge:/)).toContainText("mock (not real)");          // the operator is told when verdicts are not real

  await nav(admin, "Teams");
  await admin.getByLabel("Team number").fill(TEAM_NO);
  await admin.getByLabel("Team name").fill(TEAM);
  await admin.getByRole("button", { name: "Create team" }).click();
  const team = admin.locator("section", { hasText: TEAM });
  await expect(team).toContainText("Needs 2+ members");
  for (const [i, m] of ["Asha", "Ravi"].entries()) {
    await team.getByPlaceholder("Member name").fill(m);
    await team.getByRole("button", { name: "Add" }).click();
    await expect(team.getByText(m, { exact: true })).toBeVisible();
    if (i === 0) await expect(team).toContainText("Needs 2+ members (1)");
  }
  await expect(team).toContainText("Eligible");
  await team.getByRole("button", { name: "Create participant login" }).click();
  await team.getByPlaceholder("Email").fill(participant);
  await team.getByPlaceholder(/Password/).fill(PASSWORD);
  await team.getByRole("button", { name: "Create login" }).click();
  await expect(team.getByRole("button", { name: "Create participant login" })).toBeVisible();

  await nav(admin, "Judges");
  await admin.getByLabel("Email").fill(judgeEmail);
  await admin.getByLabel(/Password/).fill(PASSWORD);
  await admin.getByRole("button", { name: "Create judge" }).click();
  await expect(admin.getByText("Judge account created.")).toBeVisible();
  const jcard = admin.locator("section", { hasText: judgeEmail }).first();
  await jcard.getByLabel(`#${TEAM_NO}`).check();
  await jcard.getByRole("button", { name: "Save assignments" }).click();
  await expect(admin.getByText("Assignments saved.")).toBeVisible();

  await nav(admin, "Questions");
  for (const cat of ["DSA", "OOP", "DBMS", "DUEL"]) await addQuestion(admin, cat, "A");

  await nav(admin, "Assignments");
  const row = admin.locator("tr", { hasText: TEAM });
  await admin.getByRole("button", { name: "Lock assignments" }).click();
  await expect(alertText(admin)).toContainText(/cannot be locked/i);
  for (const cat of ["DSA", "OOP", "DBMS"]) await row.getByLabel(new RegExp(`${cat} for team`)).selectOption({ label: `E2E ${cat} question — A` });
  await expect(row.getByLabel(/DBMS for team/)).toHaveValue(/.+/);
  await admin.getByRole("button", { name: "Start Round 1" }).click();
  await expect(admin.getByText(/Round 1: RUNNING · locked/)).toBeVisible();
  await expect(row.getByLabel(/DSA for team/)).toBeDisabled();
  await shot(admin, "admin-assignments");
});

// ============================ PARTICIPANT ============================
test("P1 participant: dashboard, live status, three assigned questions", async () => {
  await login(part, state().participant, /\/participant$/);
  await expect(part.getByRole("heading", { name: new RegExp(`Team ${TEAM_NO}`) })).toBeVisible();
  await expect(part.getByText("Asha")).toBeVisible();
  await expect(part.getByTestId("countdown").first()).toHaveText(/^\d\d:\d\d:\d\d$/);     // server-synced timer
  await expect(part.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible({ timeout: 30_000 });   // Supabase Realtime connected
  await nav(part, "Round 1");
  for (const cat of ["DSA", "OOP", "DBMS"]) await expect(part.getByText(`E2E ${cat} question`)).toBeVisible();
  await expect(part.getByText("E2E DUEL question")).toHaveCount(0);                      // not a finalist
});

test("P2 participant: Monaco workspace, draft save, restore after refresh, mock run, submit, history", async () => {
  await part.getByRole("link", { name: /E2E DSA question/ }).click();
  await expect(part.getByRole("heading", { name: /DSA · E2E DSA question/ })).toBeVisible();
  await part.locator(".monaco-editor").first().waitFor({ timeout: 60_000 });             // real Monaco, not the fallback
  expect(await editorValue(part)).toContain("ORIGINAL DSA");                              // starts from the original code

  await typeInEditor(part, "# optimized draft version 1");
  await expect(part.getByTestId("save-status")).toHaveText(/Draft saved/, { timeout: 20_000 });
  await part.reload();
  await part.waitForLoadState("networkidle");
  await part.locator(".monaco-editor").first().waitFor({ timeout: 60_000 });
  await expect.poll(() => editorValue(part)).toBe("# optimized draft version 1");        // draft restored, not the starter code

  await part.getByRole("button", { name: "Run" }).click();
  const panel = part.getByTestId("result-panel");
  await expect(panel).toContainText(/MOCK RESULT/, { timeout: 30_000 });
  await expect(panel).toContainText(/NOT executed/);
  await expect(panel).not.toContainText(/Hidden tests/);

  await typeInEditor(part, "# optimized final solution");
  await part.getByRole("button", { name: "Submit final solution" }).click();
  await expect(panel).toContainText(/Final submission/, { timeout: 30_000 });
  await part.getByRole("tab", { name: /Submissions \(1\)/ }).click();
  await expect(part.getByRole("tabpanel")).toContainText("Final");
  await shot(part, "participant-workspace");
  const body = await part.content();
  expect(body).not.toContain(HIDDEN);
  expect(body).not.toContain(REF);
});

test("P3 participant: Autopsy Report — validation, draft persistence, submit, immutability", async () => {
  await part.getByRole("tab", { name: "Autopsy Report" }).click();
  const submit = part.getByRole("button", { name: "Submit report" });
  await expect(submit).toBeDisabled();                                                    // empty sections
  await part.getByLabel(/Inefficiency identification/).fill("too short");
  await expect(part.getByText(/at least 30 characters needed/).first()).toBeVisible();
  const lastSave = part.waitForResponse((r) => r.request().method() === "PUT" && r.url().endsWith("/report") && (r.request().postData() ?? "").includes(SECTIONS.tradeoffs));
  await part.getByLabel(/Inefficiency identification/).fill(SECTIONS.inefficiency);
  await part.getByLabel(/Optimization approach/).fill(SECTIONS.approach);
  await part.getByLabel(/Complexity analysis/).fill(SECTIONS.complexity);
  await part.getByLabel(/Trade-offs and reasoning/).fill(SECTIONS.tradeoffs);
  expect((await lastSave).status()).toBe(200);                                            // the save carrying ALL four sections
  await expect(part.getByText("All changes saved")).toBeVisible({ timeout: 20_000 });
  await part.reload();
  await part.waitForLoadState("networkidle");
  await part.getByRole("tab", { name: "Autopsy Report" }).click();
  await expect(part.getByLabel(/Optimization approach/)).toHaveValue(SECTIONS.approach);   // persisted
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(part.getByText(/can no longer be edited/)).toBeVisible({ timeout: 30_000 });
  await expect(part.getByLabel(/Optimization approach/)).toHaveAttribute("readonly", "");
  await expect(part.getByRole("button", { name: /amendment/ })).toBeVisible();
  await shot(part, "participant-report-submitted");
  await part.getByRole("link", { name: "← Questions" }).click();
  await expect(part.locator("[data-status]").filter({ hasText: /Evaluating|Evaluated|Submitted/ }).first()).toBeVisible();
});

test("P4 participant: marks are not visible before release", async () => {
  await go(part, "/participant/results");
  await expect(part.getByText(/Marks have not been released yet/)).toBeVisible();
});

// ============================ JUDGE ============================
test("J1 judge: scoped queue, real Gemini assessment, override with reason, approve", async () => {
  await login(judge, state().judge, /\/judge$/);
  await expect(judge.getByRole("heading", { name: "Review queue" })).toBeVisible();
  const queueRow = judge.getByRole("row", { name: new RegExp(`#${TEAM_NO}`) });
  await expect.poll(async () => {
    await judge.reload();
    await queueRow.first().waitFor({ timeout: 30_000 });                                   // the queue has rendered
    return queueRow.getByText("Completed").count();
  }, { timeout: 180_000, intervals: [5_000], message: "the real Gemini evaluation should complete" }).toBeGreaterThan(0);
  await queueRow.first().getByRole("link", { name: "Review", exact: true }).click();
  await judge.waitForLoadState("networkidle");
  await expect(judge.getByRole("heading", { name: new RegExp(`Team ${TEAM_NO}`) })).toBeVisible();
  await expect(judge.getByText("gemini-3.5-flash-lite")).toBeVisible();                   // AI assessment with the configured model
  await expect(judge.getByText("# optimized final solution")).toBeVisible();              // the exact submitted code
  await expect(judge.getByText(/MOCK/).first()).toBeVisible();
  const body = await judge.content();
  expect(body).not.toContain(HIDDEN);
  expect(body).not.toContain(REF);

  const aiMark = await judge.locator("#m-INEFFICIENCY").inputValue();                      // prefilled from the real AI assessment
  await judge.locator("#m-INEFFICIENCY").fill(aiMark === "5" ? "4.5" : "5");                // a genuine override either way
  await judge.locator("#w-INEFFICIENCY").fill("Identified the quadratic pair scan precisely and explained its consequence.");
  await judge.locator("#cmt").fill("Well argued report.");
  await shot(judge, "judge-review");
  await judge.getByRole("button", { name: "Approve marks" }).click();
  await expect(judge.getByRole("status").filter({ hasText: /Approved/ })).toBeVisible({ timeout: 30_000 });
  await expect(judge.getByText(/Override history/)).toBeVisible();                        // the change from the AI mark was recorded
});

// ============================ ADMIN: RESULTS ============================
test("A2 admin: monitor, audit trail, end Round 1, scores, publish; participant sees marks; public board", async ({ browser }) => {
  await nav(admin, "Round 1");
  await expect(admin.getByRole("cell", { name: `#${TEAM_NO}` }).first()).toBeVisible();
  await admin.getByRole("button", { name: "End round now" }).click();
  await expect(admin.locator("section", { hasText: "Round 1 control" }).getByText("Ended")).toBeVisible({ timeout: 30_000 });

  await nav(admin, "Leaderboard");
  const row = admin.locator("tr", { hasText: TEAM });
  await expect(row).toContainText("(1/3 approved)");
  await shot(admin, "admin-leaderboard");
  const total = Number((await row.locator("td").last().textContent())?.trim());
  expect(total).toBeGreaterThan(0);                                                       // only the judge-approved report counts

  await nav(admin, "Audit");
  await expect(admin.getByRole("cell", { name: "report.review" }).first()).toBeVisible();
  await expect(admin.getByRole("cell", { name: "round.end" }).first()).toBeVisible();

  await nav(admin, "Announcements");
  await admin.getByLabel("Announcement").fill("E2E results are about to be published");
  await admin.getByRole("button", { name: "Publish" }).click();
  await expect(admin.getByText("E2E results are about to be published").first()).toBeVisible();

  await nav(admin, "Round 1");
  await admin.getByRole("button", { name: "Publish results" }).click();
  await expect(admin.getByText("Results published").first()).toBeVisible({ timeout: 30_000 });

  // participant: released marks and judge comment
  await go(part, "/participant/results");
  await expect(part.getByText(/Report marks:/)).toBeVisible({ timeout: 30_000 });
  await shot(part, "participant-results");
  await expect(part.getByText("Well argued report.")).toBeVisible();
  await expect(part.getByText(new RegExp(`${total} / 20|${total}\\.0 / 20`)).first()).toBeVisible();
  // after the end, the workspace is read-only
  await go(part, "/participant/round-1");
  await part.getByRole("link", { name: /E2E DSA question/ }).click();
  await expect(part.getByText(/not accepting changes/)).toBeVisible({ timeout: 30_000 });
  await expect(part.getByRole("button", { name: "Submit final solution" })).toBeDisabled();

  // public leaderboard (no login at all)
  const pub = await newPage(browser);
  await go(pub, "/leaderboard");
  await expect(pub.getByRole("table", { name: "Leaderboard" })).toContainText(TEAM, { timeout: 30_000 });
  const html = await pub.content();
  expect(html).not.toContain("@example.com");
  expect(html).not.toContain(HIDDEN);
});

// ============================ ROUND 2 ============================
test("A3 admin: finalists, Round 2 config, start; finalist plays Round 2", async () => {
  await nav(admin, "Finalists");
  await admin.getByLabel(`Select team ${TEAM_NO}`).check();
  await admin.getByRole("button", { name: "Save selection" }).click();
  await admin.getByRole("button", { name: "Lock finalists" }).click();
  await expect(admin.getByText("Locked")).toBeVisible({ timeout: 30_000 });
  await shot(admin, "admin-finalists");

  await nav(admin, "Round 2");
  await admin.getByLabel(/Common problem/).selectOption({ label: "E2E DUEL question — A" });
  await admin.getByLabel(/Duration/).fill("60");
  await admin.getByRole("button", { name: "Save configuration" }).click();
  await expect(admin.getByText("Saved.", { exact: true })).toBeVisible();
  await admin.getByRole("button", { name: "Start Round 2" }).click();
  await expect(admin.locator("section", { hasText: "Round 2 control" }).getByText("Running")).toBeVisible({ timeout: 30_000 });

  await go(part, "/participant/round-2");
  await expect(part.getByText("E2E DUEL question")).toBeVisible({ timeout: 30_000 });
  await part.setViewportSize({ width: 390, height: 800 });
  await go(part, "/participant");
  await shot(part, "participant-dashboard-mobile");
  await part.setViewportSize({ width: 1280, height: 720 });
  await go(part, "/participant/round-2");
  await part.getByRole("link", { name: /E2E DUEL question/ }).click();
  await expect(part.getByRole("tab", { name: "Autopsy Report" })).toHaveCount(0);        // no report in Round 2
  await part.locator(".monaco-editor").first().waitFor({ timeout: 60_000 });
  await typeInEditor(part, "# duel answer");
  await part.getByRole("button", { name: "Submit final solution" }).click();
  await expect(part.getByTestId("result-panel")).toContainText(/MOCK RESULT/, { timeout: 30_000 });
});

test("A4 admin: end Round 2, manual score, publish; projector shows it live and read-only", async ({ browser }) => {
  await admin.getByRole("button", { name: "End round now" }).click();
  await expect(admin.locator("section", { hasText: "Round 2 control" }).getByText("Ended")).toBeVisible({ timeout: 30_000 });
  await nav(admin, "Leaderboard");
  await admin.getByRole("tab", { name: "Round 2" }).click();
  await admin.getByLabel("Team", { exact: true }).selectOption({ label: `#${TEAM_NO} ${TEAM}` });
  await admin.getByLabel("Component").fill("round2_score");
  await admin.getByLabel("Marks").fill("40");
  await admin.getByLabel("Out of").fill("100");
  await admin.getByLabel(/Reason/).fill("Judged by the panel");
  await admin.getByRole("button", { name: "Save score" }).click();
  await expect(admin.getByText(/Score saved/)).toBeVisible();

  const proj = await newPage(browser);                                                    // anonymous browser, like a projector
  await go(proj, "/projector");
  await expect(proj.getByRole("heading", { name: "The Optimization Arena" })).toBeVisible();
  await expect(proj.getByRole("status").filter({ hasText: /^Live$/ })).toBeVisible({ timeout: 30_000 });
  await expect(proj.getByRole("table", { name: "Leaderboard" })).toContainText(TEAM, { timeout: 30_000 });   // round 1 published
  await expect(proj.getByText(/Results have not been published yet/)).toHaveCount(0);

  await nav(admin, "Round 2");
  await admin.getByRole("button", { name: "Publish results" }).click();
  await expect(admin.getByText("Results published").first()).toBeVisible({ timeout: 30_000 });
  // the projector picks the change up without a manual reload (Realtime hint + polling fallback)
  await proj.getByRole("tab", { name: "Round 2" }).click();
  await expect(proj.getByRole("table", { name: "Leaderboard" })).toContainText("40", { timeout: 40_000 });
  await shot(proj, "projector");
  await proj.reload();                                                                    // authoritative state after refresh
  await expect(proj.getByRole("table", { name: "Leaderboard" })).toContainText(TEAM, { timeout: 30_000 });
  // read-only: no inputs or mutating controls, no private data
  await expect(proj.locator("input, textarea, select")).toHaveCount(0);
  const html = await proj.content();
  for (const banned of ["@example.com", HIDDEN, REF, "Sign out", "Audit"]) expect(html).not.toContain(banned);
});

// ============================ SECURITY ============================
test("S1 security: real tokens against the real API", async ({ request }) => {
  const { participant, judge: judgeEmail, admin: adminEmail } = state();
  const tok = async (email: string) => {
    const r = await fetch(`${process.env.NEXT_PUBLIC_SUPABASE_URL}/auth/v1/token?grant_type=password`, {
      method: "POST", headers: { apikey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!, "Content-Type": "application/json" }, body: JSON.stringify({ email, password: PASSWORD }) });
    return { Authorization: `Bearer ${(await r.json()).access_token}` };
  };
  const [p, j, a] = [await tok(participant), await tok(judgeEmail), await tok(adminEmail)];
  const code = async (path: string, headers?: Record<string, string>, method = "GET", data?: unknown) =>
    (await request.fetch(`/api${path}`, { method, headers, data: data as never })).status();

  for (const path of ["/admin/teams", "/admin/questions", "/admin/users", "/admin/audit", "/admin/assignments", "/admin/leaderboard?round=1", "/admin/export/leaderboard.csv"])
    expect(await code(path, p), `participant ${path}`).toBe(403);
  for (const path of ["/admin/teams", "/admin/audit", "/admin/users"]) expect(await code(path, j), `judge ${path}`).toBe(403);
  expect(await code("/judge/queue", p)).toBe(403);
  expect(await code("/participant/questions", j)).toBe(403);
  expect(await code("/admin/rounds/1/end", p, "POST")).toBe(403);
  expect(await code("/admin/rounds/1/publish", j, "POST", { published: false })).toBe(403);
  expect(await code("/admin/teams")).toBe(401);
  expect(await code("/admin/teams", { Authorization: "Bearer not.a.token" })).toBe(401);
  expect(await code("/admin/teams", { Authorization: "Bearer eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjF9.x" })).toBe(401);     // expired/forged
  expect(await code("/admin/teams", a)).toBe(200);
  // participant data never carries private fields
  const q = await request.fetch("/api/participant/questions", { headers: p });
  const text = await q.text();
  for (const banned of ["hidden_tests", "reference_solution", "reference_concepts", "expected_complexity", HIDDEN, REF]) expect(text).not.toContain(banned);
  // malformed / oversized requests are rejected cleanly, and the closed round refuses late work
  const dsa = (JSON.parse(text).questions as { category: string; variant_id: string }[]).find((x) => x.category === "DSA")!;
  expect(await code(`/participant/variants/${dsa.variant_id}/submit`, p, "POST", { language: "python", code: "x".repeat(200_001) })).toBe(422);
  expect(await code(`/participant/variants/${dsa.variant_id}/submit`, p, "POST", { nope: 1 })).toBe(422);
  expect(await code(`/participant/variants/${dsa.variant_id}/submit`, p, "POST", { language: "c", code: "late" })).toBe(409);   // Round 1 ended
  expect(await code(`/participant/variants/00000000-0000-0000-0000-000000000000/submit`, p, "POST", { language: "python", code: "x" })).toBe(404);
  expect(await code("/public/leaderboard?round=1")).toBe(200);
});
