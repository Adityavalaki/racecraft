import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs separately in development; in production FastAPI serves web/dist.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", globals: true },
});
