import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The Vercel output directory is deployed at the domain root. Workspace
  // routes rewrite to index.html, but compiled assets must remain at /assets.
  base: "/",
  build: {
    outDir: "../engine/web/react-ui",
    emptyOutDir: true,
  },
});
