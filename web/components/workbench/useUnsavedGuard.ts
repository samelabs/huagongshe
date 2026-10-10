"use client";

/**
 * useUnsavedGuard — IX-5：有未保存的修改时拦截离开。
 *
 * 两层：
 *  1. beforeunload：刷新 / 关闭标签页由浏览器原生确认（不弹自定义 UI，
 *     浏览器安全模型不允许）。
 *  2. 站内路由（next/link 的 <a> 点击）：document 捕获阶段拦截 —— 先于
 *     React 根容器的合成 click 运行，preventDefault + stopPropagation 后
 *     next/link 不会导航；弹 useConfirm（danger「放弃修改」），确认才
 *     router.push 放行，取消则原地不动（编辑器与内容保持挂载）。
 *
 * 浏览器后退/前进（popstate）无法取消，不在此列。
 */
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useDictionary } from "@/components/shared/I18nContext";

export function useUnsavedGuard(dirty: boolean) {
  const router = useRouter();
  const confirm = useConfirm();
  const t = useDictionary();
  /** 放行跳转前置 false，避免 router.push 后的一瞬间再次拦截 */
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  // 刷新 / 关闭：原生 beforeunload
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  // 站内 <a> 点击：捕获阶段接管，确认后手动 push
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!dirtyRef.current || e.defaultPrevented) return;
      // 只接管普通左键点击（修饰键点击交给浏览器新开标签等默认行为）
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const target = e.target instanceof Element ? e.target : null;
      const anchor = target?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || anchor.hasAttribute("download") || anchor.target === "_blank") return;
      let url: URL;
      try {
        url = new URL(href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      // 同页锚点/同地址不算离开
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;

      e.preventDefault();
      e.stopPropagation();
      void confirm({
        title: t.editor.unsavedTitle,
        body: t.editor.unsavedBody,
        confirmLabel: t.editor.unsavedConfirm,
        tone: "danger",
      }).then((ok) => {
        if (!ok) return;
        dirtyRef.current = false;
        router.push(url.pathname + url.search + url.hash);
      });
    }
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [confirm, router, t]);
}
