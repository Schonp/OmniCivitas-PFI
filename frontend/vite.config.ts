import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        // Se conserva el Host original: Twilio firma la llamada con la URL
        // pública (la del túnel) y la API la reconstruye con ese Host para
        // validar la firma. Si el proxy lo cambiara a localhost, la rechaza.
        changeOrigin: false,
        // El teléfono web abre un WebSocket contra la API.
        ws: true,
      },
    },
  },
  // `vite preview` sirve el panel compilado para la demo remota (scripts/demo.ps1)
  // y hereda el proxy de arriba. Llega por un túnel de ngrok, y Vite rechaza
  // cualquier Host que no sea localhost salvo los que se listan acá.
  preview: {
    allowedHosts: [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app", ".ngrok.dev"],
  },
});
