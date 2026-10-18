"use client";

/**
 * ShellWorkbenchChrome — 外壳工作台形态的客户端上下文。
 *
 * 顶栏挂在根 layout、全站唯一实例；它是否呈现工作台的手机动作（抽屉
 * 菜单 ≡ 与创建入口 +）由三个条件共同决定：服务端按请求取到的外壳
 * 数据、当前登录态、当前是否工作台路由。
 *
 * 根 layout 渲染时用初始值建上下文（工作台路由且有会话时非空，整页
 * 打开即有服务端渲染的手机动作）；站内导航时根 layout 不重渲染，由
 * 工作台 layout 挂载的 Sync 组件在渲染后把本路由的外壳数据写进上下文，
 * 顶栏随即切换形态 —— 外壳实例全程不卸载重建。
 */
import { createContext, useContext, useEffect, useState } from "react";
import type { ShellWorkbenchChrome } from "@/lib/shellData";

const ChromeContext = createContext<ShellWorkbenchChrome | null>(null);
const ChromeUpdateContext = createContext<((chrome: ShellWorkbenchChrome | null) => void) | null>(null);

/** 当前外壳是否处于工作台形态（null = 公开外壳） */
export function useShellWorkbenchChrome(): ShellWorkbenchChrome | null {
  return useContext(ChromeContext);
}

export function ShellWorkbenchChromeProvider({ initial, children }: {
  /** 根 layout 服务端取到的外壳数据；公开路由或匿名时为 null */
  initial: ShellWorkbenchChrome | null;
  children: React.ReactNode;
}) {
  const [chrome, setChrome] = useState<ShellWorkbenchChrome | null>(initial);
  return (
    <ChromeContext.Provider value={chrome}>
      <ChromeUpdateContext.Provider value={setChrome}>
        {children}
      </ChromeUpdateContext.Provider>
    </ChromeContext.Provider>
  );
}

/** 工作台 layout 渲染后把服务端取到的外壳数据写进上下文（渲染期不更新，避免闪烁） */
export function ShellWorkbenchChromeSync({ chrome }: { chrome: ShellWorkbenchChrome | null }) {
  const update = useContext(ChromeUpdateContext);
  useEffect(() => {
    update?.(chrome);
  }, [update, chrome]);
  return null;
}
