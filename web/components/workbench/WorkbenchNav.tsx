"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { workbenchRegistry, sectionOrder, sectionLabels } from "./registry";
import type { Counts } from "./types";
import t from "@/lib/i18n";

export function WorkbenchNav({ counts, activeTab, variant = "sidebar" }: {
  counts?: Counts | null;
  activeTab?: string;
  variant?: "sidebar" | "drawer";
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") || "";
  const currentTab = activeTab ?? (tab || "home");
  const wrapperClass = variant === "drawer" ? "wb-nav wb-drawer-nav" : "wb-nav";

  function isItemActive(id: string, href: string): boolean {
    if (href.startsWith("/me")) return pathname === href;
    if (id === "home") return currentTab === "home";
    return currentTab === id;
  }

  return (
    <nav className={wrapperClass} aria-label={t.nav.workbenchNav}>
      {sectionOrder.map((section) => {
        const panels = workbenchRegistry.filter((p) => p.section === section);
        if (panels.length === 0) return null;
        return (
          <div className="wb-nav-group" key={section}>
            <p className="wb-nav-label">{sectionLabels[section]}</p>
            {panels.map((panel) => {
              const badge = counts && panel.badge ? panel.badge(counts) : null;
              const active = isItemActive(panel.id, panel.href);
              return (
                <Link key={panel.id} href={panel.href} className={`wb-nav-link${active ? " active" : ""}`}>
                  <span>{panel.label}</span>
                  <em>{badge != null && badge > 0 ? badge : ""}</em>
                </Link>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}
