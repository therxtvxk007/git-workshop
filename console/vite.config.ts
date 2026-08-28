import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: { port: 5173 },
  build: {
    rollupOptions: {
      output: {
        // MapLibre is ~800 kB and is only needed by one panel on one route,
        // which degrades gracefully when it is absent. Splitting it out keeps
        // it off the critical path for the ten routes that never draw a map.
        manualChunks: {
          maplibre: ["maplibre-gl"],
          react: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
