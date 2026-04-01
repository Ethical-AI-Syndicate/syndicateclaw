import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";
const rootDir = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            "/api": "http://localhost:8000",
            "/webhooks": "http://localhost:8000"
        }
    },
    build: {
        outDir: "dist"
    },
    resolve: {
        alias: {
            "@": path.resolve(rootDir, "src"),
        },
    }
});
