import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/openflux/static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
        manualChunks: {
          recharts: ["recharts"],
          motion: ["motion/react"],
        },
      },
    },
  },
  server: {
    port: 5174,
    proxy: {
      "/api": "http://localhost:5173",
    },
  },
});
