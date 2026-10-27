import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Matches FRONTEND_ORIGIN in backend/.env.example, which the backend's
    // CORS policy allows. Changing one means changing the other.
    port: 5173,
  },
});
