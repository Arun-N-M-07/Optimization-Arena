import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { STATE_FILE } from "./supa";

const state = () => JSON.parse(fs.readFileSync(STATE_FILE, "utf8")) as { admin: string; participant: string };

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

