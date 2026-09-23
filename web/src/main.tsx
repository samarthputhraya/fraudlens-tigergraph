import ReactDOM from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";
import App from "./App";

// No StrictMode: its dev-only double mount would open two SSE connections, and every /run connection starts a real
// investigation on the server (runs are serialised, so the second would wait for the first).
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
