"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost, apiDelete, ApiError } from "@/lib/api";
import t from "@/lib/i18n";

type SkillRow = {
  id: number; slug: string; title: string; description: string | null;
  category: string | null; origin: string; visibility: "private" | "public";
  has_scripts: boolean; file_count: number; size_bytes: number;
  created_at: string; updated_at: string; published_at: string | null; publish_note: string | null;
  owner: { username: string; display_name: string };
};

type CategoryRow = {
  id: number; name: string; abbr: string; color: string;
  sort_order: number; active: boolean; skill_count: number;
};

type AdminSkillsResponse = { total: number; items: SkillRow[] };

function fmtSize(n: number) {
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)}MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)}KB`;
  return `${n}B`;
}

export function SamelabsSkills() {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [total, setTotal] = useState(0);
  const [visibility, setVisibility] = useState<"all" | "public" | "private">("all");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const [cats, setCats] = useState<CategoryRow[]>([]);
  const [newCat, setNewCat] = useState({ name: "", abbr: "", color: "#1e90ff", sort_order: 100 });
  const [catBusy, setCatBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<SkillRow | null>(null);
  const [catError, setCatError] = useState("");

  async function reload(vis: "all" | "public" | "private" = visibility) {
    setError("");
    const params = new URLSearchParams({ visibility: vis, limit: "100" });
    if (q.trim()) params.set("q", q.trim());
    try {
      const data = await apiGet<AdminSkillsResponse>(`/admin/skills?${params}`);
      setSkills(data.items);
      setTotal(data.total);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    }
  }

  async function reloadCats() {
    try {
      setCats(await apiGet<CategoryRow[]>(`/admin/skill-categories`));
    } catch { /* 分类加载失败不阻塞技能区 */ }
  }

  useEffect(() => {
    let active = true;
    apiGet<AdminSkillsResponse>(`/admin/skills?visibility=all&limit=100`).then((data) => {
      if (active) { setSkills(data.items); setTotal(data.total); }
    }).catch((err) => {
      if (!active) return;
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) setError(t.admin.noPermission);
      else setError(t.admin.errLoadFailed);
    });
    apiGet<CategoryRow[]>(`/admin/skill-categories`).then((data) => { if (active) setCats(data); }).catch(() => {});
    return () => { active = false; };
  }, []);

  async function setVis(id: number, vis: "private" | "public") {
    setError(""); setBusyId(id);
    try {
      await apiPatch(`/admin/skills/${id}/visibility`, JSON.stringify({ visibility: vis }));
      await reload();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  async function removeSkill(id: number) {
    setError(""); setBusyId(id);
    try {
      await apiDelete(`/admin/skills/${id}`);
      await reload();
      await reloadCats();
    } catch { setError(t.admin.errOperation); } finally { setBusyId(null); }
  }

  async function saveCat(existing: CategoryRow | null) {
    setCatError(""); setCatBusy(true);
    const body = existing
      ? { ...existing, active: !existing.active }
      : { ...newCat, active: true };
    try {
      if (existing) {
        await apiPatch(`/admin/skill-categories/${existing.id}`, JSON.stringify(body));
      } else {
        await apiPost(`/admin/skill-categories`, JSON.stringify(body));
        setNewCat({ name: "", abbr: "", color: "#1e90ff", sort_order: 100 });
      }
      await reloadCats();
    } catch (e) {
      setCatError(e instanceof ApiError && e.status !== 401 && e.status !== 403 ? e.message : t.admin.errSaveFailed);
    } finally { setCatBusy(false); }
  }

  if (error && skills.length === 0) return <div className="notice error">{error}</div>;

  return <>
    <header className="page-title">
      <p className="page-kicker">{t.admin.skillsKicker}</p>
      <h1>{t.admin.skillsTitle}</h1>
    </header>
        {error && <div className="notice error">{error}</div>}

        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.skillsAll}</h2></div>
            <span>{t.admin.skillCount(total)}</span>
          </div>
          <div className="admin-filters">
            <input
              value={q}
              placeholder={t.admin.skillsSearchPlaceholder}
              onChange={(e) => setQ(e.target.value)}
            />
            <button onClick={() => reload()}>{t.admin.skillsFilterApply}</button>
            {(["all", "public", "private"] as const).map((v) => (
              <button key={v} className={visibility === v ? "active" : ""}
                onClick={() => { setVisibility(v); reload(v); }}>
                {v === "all" ? t.admin.visAll : v === "public" ? t.admin.publicLabel : t.admin.privateLabel}
              </button>
            ))}
          </div>
          <div className="admin-table admin-actions-min">
            {skills.map((s) => <article key={s.id}>
              <div>
                <strong>{s.title}</strong>
                <span>@{s.owner.username} · {s.slug} · {s.file_count} {t.admin.skillFiles} · {fmtSize(s.size_bytes)}</span>
                <span>{s.category ?? t.admin.skillUncategorized}{s.has_scripts ? ` · ${t.admin.skillHasScripts}` : ""}{s.publish_note ? ` · ${s.publish_note}` : ""}</span>
              </div>
              <div className="admin-user-badges">
                <span className={`status ${s.visibility}`}>{s.visibility === "public" ? t.admin.publicLabel : t.admin.privateLabel}</span>
                <span className="status">{s.origin}</span>
              </div>
              <div className="admin-user-actions">
                <button className="text-button" disabled={busyId === s.id}
                  onClick={() => setVis(s.id, s.visibility === "public" ? "private" : "public")}>
                  {busyId === s.id ? "…" : s.visibility === "public" ? t.admin.skillUnpublish : t.admin.skillPublish}
                </button>
                <button className="text-button" disabled={busyId === s.id}
                  onClick={() => setPendingDelete(s)}>
                  {t.admin.skillDelete}
                </button>
              </div>
            </article>)}
          </div>
        </section>

        <section className="dashboard-section">
          <div className="section-heading">
            <div><h2>{t.admin.skillCategoriesTitle}</h2></div>
            <span>{t.admin.categoryCount(cats.length)}</span>
          </div>
          {catError && <div className="notice error">{catError}</div>}
          <div className="admin-table admin-actions-min">
            {cats.map((c) => <article key={c.id}>
              <div>
                <strong><span style={{ color: c.color }}>{c.abbr}</span> {c.name}</strong>
                <span>#{c.id} · {t.admin.categorySort(c.sort_order)}</span>
              </div>
              <div className="admin-user-badges">
                <span className={`status ${c.active ? "active" : "disabled"}`}>{c.active ? t.admin.categoryActive : t.admin.categoryInactive}</span>
                <span className="status">{t.admin.skillCount(c.skill_count)}</span>
              </div>
              <div className="admin-user-actions">
                <button className="text-button" disabled={catBusy}
                  onClick={() => saveCat(c)}>
                  {c.active ? t.admin.categoryDeactivate : t.admin.categoryActivate}
                </button>
              </div>
            </article>)}
          </div>
          <div className="admin-cat-create">
            <input value={newCat.name} placeholder={t.admin.categoryNamePlaceholder}
              onChange={(e) => setNewCat({ ...newCat, name: e.target.value })} />
            <input value={newCat.abbr} placeholder={t.admin.categoryAbbrPlaceholder} maxLength={4}
              onChange={(e) => setNewCat({ ...newCat, abbr: e.target.value.toUpperCase() })} />
            <input type="color" value={newCat.color}
              onChange={(e) => setNewCat({ ...newCat, color: e.target.value })} />
            <input type="number" value={newCat.sort_order} min={0}
              onChange={(e) => setNewCat({ ...newCat, sort_order: Number(e.target.value) })} />
            <button className="button primary small" disabled={catBusy || !newCat.name || !newCat.abbr}
              onClick={() => saveCat(null)}>
              {catBusy ? "…" : t.admin.categoryCreate}
            </button>
          </div>
        </section>
    {pendingDelete && (
      <div className="pipe-confirm" role="dialog" aria-modal onClick={() => setPendingDelete(null)}>
        <div className="pipe-confirm-box" onClick={(e) => e.stopPropagation()}>
          <p>{t.admin.skillDeleteConfirm(pendingDelete.title, pendingDelete.slug)}</p>
          <p>{t.admin.skillDeleteIrreversible}</p>
          <div className="pipe-confirm-actions">
            <button type="button" className="button small" onClick={() => setPendingDelete(null)}>{t.admin.cancel}</button>
            <button type="button" className="button danger small" disabled={busyId === pendingDelete.id}
              onClick={() => { removeSkill(pendingDelete.id).finally(() => setPendingDelete(null)); }}>
              {t.admin.skillDelete}
            </button>
          </div>
        </div>
      </div>
    )}
  </>;
}
