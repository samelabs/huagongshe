"use client";

/**
 * useUnsavedGuard — IX-5：有未保存的修改时拦截离开。
 *
 * 三层：
 *  1. beforeunload：刷新 / 关闭标签页由浏览器原生确认（不弹自定义 UI，
 *     浏览器安全模型不允许）。
 *  2. 站内路由（next/link 的 <a> 点击）：document 捕获阶段拦截 —— 先于
 *     React 根容器的合成 click 运行，preventDefault + stopPropagation 后
 *     next/link 不会导航；弹 useConfirm（danger「放弃修改」），确认才
 *     router.push 放行，取消则原地不动（编辑器与内容保持挂载）。
 *  3. 浏览器后退/前进（popstate，SMK-001）：popstate 本身不可取消 —— 在
 *     active 变真时向历史栈压一条同 URL 哨兵（history.pushState）。用户按
 *     后退先弹出的是哨兵（URL 不变、视图不动），此时弹确认；取消则把哨兵
 *     压回去（原地保留），确认则连退两步（哨兵 + 用户真正要离开的那一步）。
 *     编辑器卸载时若哨兵仍在栈上则补一次 history.back() 清掉，不留「空后退」。
 *
 * active 语义 = 有不可丢失的状态：草稿脏态 **或 保存请求进行中**（SMK-001：
 * 保存在途时拦截保护不得被撤掉）。调用方传 dirty || busy。
 */
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { useDictionary } from "@/components/shared/I18nContext";

export function useUnsavedGuard(active: boolean) {
  const router = useRouter();
  const confirm = useConfirm();
  const t = useDictionary();
  /** 放行跳转前置 false，避免 router.push 后的一瞬间再次拦截 */
  const activeRef = useRef(active);
  activeRef.current = active;
  /** 哨兵是否在历史栈顶 */
  const sentinelRef = useRef(false);

  // 刷新 / 关闭：原生 beforeunload
  useEffect(() => {
    if (!active) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [active]);

  // 站内 <a> 点击：捕获阶段接管，确认后手动 push
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!activeRef.current || e.defaultPrevented) return;
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
        cancelLabel: t.editor.unsavedCancel,
        tone: "danger",
      }).then((ok) => {
        if (!ok) return;
        activeRef.current = false;
        router.push(url.pathname + url.search + url.hash);
      });
    }
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [confirm, router, t]);

  // 浏览器后退/前进（popstate）：哨兵占位 + 确认
  useEffect(() => {
    if (active && !sentinelRef.current) {
      sentinelRef.current = true;
      history.pushState({ __hgsDraftGuard: true }, "", window.location.href);
    }
    // 卸载时不主动 history.back() 弹哨兵：back() 总是先于程序化导航的
    // pushState 落地，popstate 会中止 Next 在途导航（s45 竞态实测）。
    // 残留哨兵的代价只是之后第一次后退无可见变化（URL 相同），再按一次
    // 即真正离开 —— 比破坏导航安全。
    return () => { sentinelRef.current = false; };
  }, [active]);

  useEffect(() => {
    function onPopState() {
      if (!sentinelRef.current) return;
      if (!activeRef.current) {
        // 保护已解除（保存成功等）：哨兵被消费即放行
        sentinelRef.current = false;
        return;
      }
      // 用户按了后退/前进：先把哨兵压回原位（视图留在原地），再确认
      history.pushState({ __hgsDraftGuard: true }, "", window.location.href);
      void confirm({
        title: t.editor.unsavedTitle,
        body: t.editor.unsavedBody,
        confirmLabel: t.editor.unsavedConfirm,
        cancelLabel: t.editor.unsavedCancel,
        tone: "danger",
      }).then((ok) => {
        if (!ok) return;
        // 确认放弃：先弹哨兵，等它落定再退一步 —— 那才是用户要去的上一页
        sentinelRef.current = false;
        history.back();
        const onSettled = () => {
          window.removeEventListener("popstate", onSettled);
          history.back();
        };
        window.addEventListener("popstate", onSettled);
      });
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [confirm, t]);
}
