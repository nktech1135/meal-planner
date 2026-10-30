import { expect, test as setup } from "@playwright/test";

export const ADMIN = { email: "admin@example.com", password: "admin password 123" };

setup("create the admin account", async ({ request }) => {
  const resp = await request.post("/api/auth/register", { data: { ...ADMIN, display_name: "Admin" } });
  expect(resp.status(), await resp.text()).toBe(201);
  await request.put("/api/profile", {
    data: { sex: "female", birth_date: "1988-04-02", height_cm: 168, weight_kg: 64, timezone: "UTC" },
  });
  await request.storageState({ path: "state/admin.json" });
});
