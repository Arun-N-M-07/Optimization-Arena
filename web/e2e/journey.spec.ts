import fs from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { PASSWORD, STATE_FILE } from "./supa";

const state = () => JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as { admin: string; participant: string };
const TEAM_NO = String(8000 + Math.floor(Math.random() * 999));
const SECRET_HIDDEN = "E2E-HIDDEN-SECRET-5521";
const SECRET_REF = "E2E-REFERENCE-SECRET-8830";

async function login(page: Page, email: string, to: RegExp) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(to);
}

async function addQuestion(page: Page, category: string, variantLabel: string) {
  await page.getByLabel("Category").selectOption(category);
  await page.getByLabel("Title").fill(`E2E ${category} question`);
  await page.getByRole("button", { name: "Create question" }).click();
  const card = page.locator("section", { hasText: `E2E ${category} question` });
  await card.getByRole("button", { name: "Add variant" }).click();
  await card.getByLabel("Label (e.g. A)").fill(variantLabel);
  await card.getByLabel("Problem description").fill(`Optimise the ${category} code.`);
  await card.getByLabel("Expected behaviour").fill("Same output as before.");
  await card.getByLabel("Original (inefficient) code").fill("slow()");
  await card.getByLabel("Hidden test input (server only)").fill(SECRET_HIDDEN);
  await card.getByLabel("Hidden test expected output (server only)").fill("42");
  await card.getByLabel("Reference solution (server only)").fill(SECRET_REF);
  await card.getByRole("button", { name: "Create variant" }).click();
  await expect(card.getByText("Variant", { exact: false }).first()).toBeVisible();
  await card.getByRole("button", { name: "Publish" }).first().click(); // question
  await expect(card.getByText(/PUBLISHED/).first()).toBeVisible();
  await card.locator("li").getByRole("button", { name: "Publish" }).click(); // variant
  await expect(card.locator("li").getByText("PUBLISHED")).toBeVisible();
}

test("signed-out visitors are redirected away from role areas", async ({ page }) => {
  for (const p of ["/admin", "/admin/teams", "/participant", "/judge"]) {
    await page.goto(p);
    await expect(page).toHaveURL(/\/login/);
  }
});

test("wrong password is rejected", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(state().admin);
  await page.getByLabel("Password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("p[role=alert]")).toContainText("Invalid");
  await expect(page).toHaveURL(/\/login/);
});

test("admin sets up the round, participant sees only their own assigned questions", async ({ page, context }) => {
  const { admin, participant } = state();

  // ---- admin: teams ----
  await login(page, admin, /\/admin$/);
  await page.getByRole("link", { name: "Teams", exact: true }).click();
  await page.getByLabel("Team number").fill(TEAM_NO);
  await page.getByLabel("Team name").fill("E2E Falcons");
  await page.getByRole("button", { name: "Create team" }).click();
  const team = page.locator("section", { hasText: "E2E Falcons" });
  await expect(team).toContainText("Needs 2+ members");
  await team.getByPlaceholder("Member name").fill("Asha");
  await team.getByRole("button", { name: "Add" }).click();
  await expect(team).toContainText("Needs 2+ members (1)");
  await team.getByPlaceholder("Member name").fill("Ravi");
  await team.getByRole("button", { name: "Add" }).click();
  await expect(team).toContainText("Eligible");
  // duplicate team number is refused
  await page.getByLabel("Team number").fill(TEAM_NO);
  await page.getByLabel("Team name").fill("E2E Dup");
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.locator("p[role=alert]")).toContainText(/already exists/i);
  // participant login
  await team.getByRole("button", { name: "Create participant login" }).click();
  await team.getByPlaceholder("Email").fill(participant);
  await team.getByPlaceholder(/Password/).fill(PASSWORD);
  await team.getByRole("button", { name: "Create login" }).click();
  await expect(team.getByRole("button", { name: "Create participant login" })).toBeVisible();

  // ---- admin: questions ----
  await page.getByRole("link", { name: "Questions", exact: true }).click();
  for (const cat of ["DSA", "OOP", "DBMS"]) await addQuestion(page, cat, "A");

  // ---- admin: assignments ----
  await page.getByRole("link", { name: "Assignments", exact: true }).click();
  const row = page.locator("tr", { hasText: "E2E Falcons" });
  await page.getByRole("button", { name: "Lock assignments" }).click();
  await expect(page.locator("p[role=alert]")).toContainText(/cannot be locked/i);   // incomplete -> refused
  for (const cat of ["DSA", "OOP", "DBMS"]) {
    await row.getByLabel(new RegExp(`${cat} for team`)).selectOption({ label: `E2E ${cat} question — A` });
  }
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Start Round 1" }).click();
  await expect(page.getByText(/Round 1: RUNNING · locked/)).toBeVisible();
  await expect(row.getByLabel(/DSA for team/)).toBeDisabled();

  // ---- participant ----
  const p2 = await context.newPage();
  await context.clearCookies();
  await login(p2, participant, /\/participant$/);
  await expect(p2.getByRole("heading", { name: new RegExp(`Team ${TEAM_NO}`) })).toBeVisible();
  await expect(p2.getByText("Asha")).toBeVisible();
  await p2.getByRole("link", { name: "Go to Round 1" }).click();
  for (const cat of ["DSA", "OOP", "DBMS"]) await expect(p2.getByText(`${cat} · E2E ${cat} question`)).toBeVisible();
  await expect(p2.getByText("slow()").first()).toBeVisible();
  const html = await p2.content();
  expect(html).not.toContain(SECRET_HIDDEN);
  expect(html).not.toContain(SECRET_REF);

  // participant cannot reach the admin area, nor the admin API
  await p2.goto("/admin");
  await expect(p2).toHaveURL(/\/participant$/);
  // a genuine participant token is refused by the admin API (authorization is on the server)
  const tok = await fetch(`${process.env.NEXT_PUBLIC_SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: { apikey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!, "Content-Type": "application/json" },
    body: JSON.stringify({ email: participant, password: PASSWORD }),
  }).then((r) => r.json());
  const h = { Authorization: `Bearer ${tok.access_token}` };
  expect((await fetch("http://localhost:3000/api/admin/teams", { headers: h })).status).toBe(403);
  expect((await fetch("http://localhost:3000/api/admin/questions", { headers: h })).status).toBe(403);
  expect((await fetch("http://localhost:3000/api/admin/teams")).status).toBe(401);

  // reload keeps the session
  await p2.reload();
  await expect(p2.getByRole("heading", { name: new RegExp(`Team ${TEAM_NO}`) })).toBeVisible();
});
