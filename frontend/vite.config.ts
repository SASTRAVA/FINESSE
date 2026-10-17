import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/workspace/",
  build: {
    outDir: "../engine/web/react-ui",
    emptyOutDir: true,
  },
});
