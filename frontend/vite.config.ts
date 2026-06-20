import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      ignored: [
        "**/.git/**",
        "**/.venv/**",
        "**/data/**",
        "**/dist/**",
        "**/node_modules/**",
      ],
      usePolling: true,
      interval: 500,
    },
  },
});
