import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppProvider } from "./lib/app";
import "./base.css";
import "./theme.css";

createRoot(document.getElementById("root")).render(<StrictMode><AppProvider><App /></AppProvider></StrictMode>);
