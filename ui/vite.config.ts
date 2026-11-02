import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // the API must be told to allow this origin (MARGIN_API_CORS_ORIGINS, see README)
  server: { port: 3000, strictPort: true },
  preview: { port: 3000, strictPort: true },
  test: { environment: "jsdom", setupFiles: ["src/test/setup.ts"] },
});
