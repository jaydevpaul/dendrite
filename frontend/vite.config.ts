import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Root-relative alias, so no Node path APIs (and no @types/node) are needed.
    alias: { "@": "/src" },
  },
  server: {
    port: 5173,
    // The whole point of this proxy is that the browser only ever sees one
    // origin, so the session cookie is same-origin and CORS never enters the
    // picture. See docs/frontend_design.md section 3 -- do NOT replace this
    // with CORSMiddleware on the backend.
    //
    // The backend mounts its routers at /auth and /health (not /api/*), so the
    // proxy keys match those prefixes exactly.
    proxy: {
      "/auth": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
