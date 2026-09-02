"use client";

import { useEffect, useState } from "react";

/**
 * ShellDebug(临时诊断, 0902 手机壳层失控定位用, 定位后删除):
 * 仅当「疑似手机环境 且 680 media 未命中」的异常态才渲染红条,
 * 显示运行时真值: 视口宽/media命中/display-mode/缩放/tabbar计算高度/body overflow。
 * 正常态(手机+680命中 / 桌面)零渲染零开销。
 */
export function ShellDebug() {
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    const check = () => {
      const mobileish = window.innerWidth < 900
        || /Android|iPhone|iPad|HarmonyOS/i.test(navigator.userAgent);
      const mediaHit = window.matchMedia("(max-width: 680px)").matches;
      if (!mobileish || mediaHit) { setInfo(null); return; }
      const dm = window.matchMedia("(display-mode: standalone)").matches ? "standalone" : "browser";
      const tb = document.querySelector<HTMLElement>(".mobile-tab-bar");
      const tbH = tb ? getComputedStyle(tb).height + "/" + getComputedStyle(tb).display : "无";
      const ac = document.querySelector<HTMLElement>(".app-container");
      const acPos = ac ? getComputedStyle(ac).position : "无";
      const bodyOv = getComputedStyle(document.body).overflow;
      const visual = window.visualViewport
        ? `${Math.round(window.visualViewport.width)}x${Math.round(window.visualViewport.height)}@scale${window.visualViewport.scale.toFixed(2)}`
        : "-";
      setInfo(
        `vw=${window.innerWidth} media680=false ${dm} visual=${visual} dpr=${devicePixelRatio} ` +
        `tabbar=${tbH} shell=${acPos} body.ov=${bodyOv}`
      );
    };
    check();
    window.addEventListener("resize", check);
    window.addEventListener("orientationchange", check);
    return () => {
      window.removeEventListener("resize", check);
      window.removeEventListener("orientationchange", check);
    };
  }, []);

  if (!info) return null;
  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 9999,
      background: "#c0392b", color: "#fff", font: "11px/1.4 monospace",
      padding: "6px 8px", wordBreak: "break-all", pointerEvents: "none",
    }}>
      壳层诊断:{info}
    </div>
  );
}
