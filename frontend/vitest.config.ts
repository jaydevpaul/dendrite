import { defineConfig } from "vitest/config";

/**
 * Kept out of `vite.config.ts` on purpose: the dev server config carries the
 * proxy that makes the session cookie same-origin, and it should not gain a
 * second job. Nothing here is shared with it except the `@` alias.
 *
 * `jsdom` is here for one thing -- the DOM range arithmetic that turns a
 * highlighted span into offsets. Everything downstream of that measurement is
 * plain string work and runs with no environment at all.
 */
export default defineConfig({
  resolve: { alias: { "@": "/src" } },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
