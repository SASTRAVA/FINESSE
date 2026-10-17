import React from "react";
import { createRoot } from "react-dom/client";
import { Workspace } from "./workspace";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Workspace />
  </React.StrictMode>,
);
