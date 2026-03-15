import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initMobileApp } from "./lib/mobileSetup";

document.documentElement.classList.add('dark');

createRoot(document.getElementById("root")!).render(<App />);

initMobileApp();
