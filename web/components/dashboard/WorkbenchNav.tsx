"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { panelRegistry, sectionLabels } from "./registry";
import type { Counts } from "./types";

export function WorkbenchNav({ counts, activeTab }: { counts?: Counts | null; activeTab?: string }) {
  const pathname = usePathname();
  return (
    <nav className="wb-nav" aria-label="工作台导航">
      {(["work", "social", "account"] as const).map((section) => {
        const panels = panelRegistry.filter((p) => p.section === section);
        if (panels.length === 0 && section !== "account") return null;
        return (
          <div className="wb-nav-group" key={section}>
            <p className="wb-nav-label">{sectionLabels[section] ?? ""}</p>
            {section === "account" ? (
              <Link href="/me" className={`wb-nav-link${pathname.startsWith("/me/settings") || pathname === "/me" ? " active" : ""}`}><span>我的</span></Link>
            ) : (
              panels.map((panel) => {
                const badge = counts && panel.badge ? panel.badge(counts) : null;
                const active = activeTab === panel.id;
                return (
                  <Link key={panel.id} href={panel.href} className={`wb-nav-link${active ? " active" : ""}`}>
                    <span>{panel.label}</span>
                    {badge != null && badge > 0 && <em>{badge}</em>}
                  </Link>
                );
              })
            )}
          </div>
        );
      })}
    </nav>
  );
}
