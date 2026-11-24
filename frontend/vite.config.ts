import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // FastAPI serves the built workspace at / and /workspace; compiled assets
  // use the shared /assets mount in local and Vercel deployments.
  base: "/",
  build: {
    outDir: "../engine/web/react-ui",
    emptyOutDir: true,
  },
});
