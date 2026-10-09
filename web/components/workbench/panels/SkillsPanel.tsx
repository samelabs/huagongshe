"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Pagination, PanelError, PanelHeading, PanelLoading, WbEmpty } from "../shared";
import type { LoadState, PageResponse, SkillItem } from "../types";

const emptyPage = <T,>(): PageResponse<T> => ({ items: [], total: 0, page: 1, page_size: 20 });

/**
 * v1.7.0 L3(+补正): 上传/删除失败提示按真实状态分类 —
 * 401 会话失效 / 403 权限不足 / 429 限流各自专用文案(不挪用搜索专用
 * 的"结构检索需要登录"); 400/409 展示后端业务校验 detail(zip 结构/
 * slug 冲突/大小上限等可行动信息); 5xx 与网络错误落本地化通用失败,
 * 不暴露内部 API 路径。
 */
function skillsErrorMessage(error: unknown, t: { me: { skillLoginRequired: string; skillForbidden: string; skillRateLimited: string }; common: { networkError: string } }, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return t.me.skillLoginRequired;
    if (error.status === 403) return t.me.skillForbidden;
    if (error.status === 429) return t.me.skillRateLimited;
    if ((error.status === 400 || error.status === 409) && error.detail) return error.detail;
    if (error.status >= 500) return t.common.networkError;
    return fallback;
  }
  if (error instanceof Error && !(error instanceof ApiError)) return t.common.networkError;
  return fallback;
}

export function SkillsPanel({ page, initialData }: { page: number; initialData?: PageResponse<SkillItem> | null }) {
  const t = useDictionary();
  const locale = useLocale();
  const [skills, setSkills] = useState<PageResponse<SkillItem>>(initialData ?? emptyPage<SkillItem>());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current && initialData) {
      mounted.current = true;
      return;
    }
    mounted.current = true;
    let active = true;
    setState("loading");
    setError(null);
    apiGet<PageResponse<SkillItem>>(`/skills?scope=mine&page=${page}&page_size=20`)
      .then((value) => {
        if (active) {
          setSkills(value);
          setState("ready");
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err);
          setState("error");
        }
      });
    return () => {
      active = false;
    };
  }, [page, initialData]);

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setUploadNotice(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const created = await apiPost<SkillItem & { warnings?: string[] }>("/skills", form);
      // v1.7.0 L3 补正: 写请求成功即视为操作成功 — 成功提示先落定;
      // 后续列表刷新失败单独提示, 不反向报"上传失败", 也不重试写请求。
      const warn = created.warnings?.length ? t.me.skillUploadWarnings(created.warnings.length) : "";
      setUploadNotice(t.me.skillUploaded(created.slug) + warn);
      try {
        const value = await apiGet<PageResponse<SkillItem>>(`/skills?scope=mine&page=1&page_size=20`);
        setSkills(value);
        setState("ready");
      } catch {
        setUploadNotice(t.me.skillUploaded(created.slug) + warn + " " + t.me.skillRefreshFailed);
      }
    } catch (err) {
      setUploadError(skillsErrorMessage(err, t, t.me.skillUploadFailed));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleDelete(id: number, slug: string) {
    setUploadNotice(null);
    setUploadError(null);
    try {
      await apiDelete(`/skills/${id}`);
      // v1.7.0 L3 补正: 删除成功即成功 — 刷新失败单独提示, 不报"删除失败",
      // 不重复提交删除。
      setUploadNotice(t.me.skillDeleted(slug));
      try {
        const value = await apiGet<PageResponse<SkillItem>>(
          `/skills?scope=mine&page=${Math.min(page, Math.max(1, Math.ceil((skills.total - 1) / 20)))}&page_size=20`
        );
        setSkills(value);
      } catch {
        setUploadNotice(t.me.skillDeleted(slug) + " " + t.me.skillRefreshFailed);
      }
    } catch (err) {
      setUploadError(skillsErrorMessage(err, t, t.me.skillDeleteFailed));
    }
  }

  return (
    <section className="wb-panel">
      <PanelHeading title={t.me.tabSkills} subtitle={t.me.skillsHint} count={state === "ready" ? skills.total : "—"} unit={t.me.unitSkill} />
      <div className="wb-skills-upload">
        <div className="wb-skills-upload-row">
          <input ref={fileRef} type="file" accept=".zip" aria-label={t.me.skillsPickZip} />
          <button type="button" className="wb-btn wb-btn-ghost" onClick={handleUpload} disabled={uploading}>
            {uploading ? t.me.skillsUploading : t.me.skillsUpload}
          </button>
        </div>
        <p className="wb-skills-upload-hint">{t.me.skillsUploadHint}</p>
        {uploadNotice && <p className="wb-skills-notice">{uploadNotice}</p>}
        {uploadError && <p className="wb-skills-error">{uploadError}</p>}
      </div>
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (skills.items.length ? (
        <div className="wb-skill-list">
          {skills.items.map((s) => (
            <div key={s.id} className="wb-skill-row">
              <span>
                <strong>{s.slug}</strong>
                {s.description && <small>{s.description}</small>}
                <small>
                  {s.file_count} {t.me.unitFiles}
                  {s.has_scripts ? ` · ${t.me.skillHasScripts}` : ""}
                  {s.visibility === "public" ? ` · ${t.me.skillPublic}` : ""}
                </small>
              </span>
              <span className="wb-skill-actions">
                <a className="wb-btn wb-btn-ghost" href={`/api/skills/${s.id}/archive`} download={`${s.slug}.zip`}>
                  {t.me.skillDownload}
                </a>
                <button type="button" className="wb-btn wb-btn-danger" onClick={() => handleDelete(s.id, s.slug)}>
                  {t.me.skillDelete}
                </button>
              </span>
            </div>
          ))}
        </div>
      ) : <WbEmpty text={t.me.skillsEmpty} />)}
      {state === "ready" && skills.total > skills.page_size && (
        <Pagination page={skills.page} pageSize={skills.page_size} total={skills.total} href={(value) => withLocale(`/aichem?tab=skills&page=${value}`, locale)} />
      )}
    </section>
  );
}
