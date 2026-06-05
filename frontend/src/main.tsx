import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";

// React 应用入口。
//
// Vite 会从 index.html 加载这个文件；这里唯一的职责是：
// 1. 找到 index.html 里的 #root 容器。
// 2. 把根组件 App 挂载进去。
// 3. 引入全局样式，让所有页面和组件共享基础布局规则。
//
// 业务逻辑不要放在入口文件里。课堂状态、API 调用、WebSocket 处理都从
// App 或后续的 store/service 模块开始，入口保持轻量，方便以后接路由。
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
