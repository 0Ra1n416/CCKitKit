import path from "node:path"
import { fileURLToPath } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  // 相对 base:资源路径(./assets/...)自动跟随当前子路径,使后端可用 --base 运行时挂到
  // 任意根路径前缀下(根部署与 /cckit 子路径部署同一份产物都可用)。
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
})
