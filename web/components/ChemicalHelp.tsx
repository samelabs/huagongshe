"use client";

import Link from "next/link";
import { useState } from "react";

type HelpPost = { id: number; title: string; body: string; username: string; created_at: string };

export function ChemicalHelp({ chemicalId, initialPosts }: { chemicalId: number; initialPosts: HelpPost[] }) {
  const [posts, setPosts] = useState(initialPosts);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [needsLogin, setNeedsLogin] = useState(false);

  return (
    <section className="help-section" id="reaction-help">
      <div className="section-heading compact-heading">
        <div><p>COMMUNITY</p><h2>反应求助</h2></div>
        <button className="button secondary small" type="button" onClick={() => setOpen((value) => !value)}>
          {open ? "收起" : "发布求助"}
        </button>
      </div>
      <p className="section-intro">围绕这个化合物提出合成、条件或文献问题。求助是讨论入口，不直接改写核心数据。</p>
      {open && (
        <form className="help-form" onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true); setMessage(""); setNeedsLogin(false);
          const form = event.currentTarget;
          const values = new FormData(form);
          const response = await fetch(`/api/community/chemicals/${chemicalId}/help`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: values.get("title"), body: values.get("body") }),
          });
          if (response.status === 401) {
            setNeedsLogin(true); setMessage("发布求助需要先登录。"); setBusy(false); return;
          }
          const body = await response.json().catch(() => null);
          if (!response.ok) {
            setMessage(typeof body?.detail === "string" ? body.detail : "发布失败，请稍后重试。");
            setBusy(false); return;
          }
          const me = await fetch("/api/community/me", { cache: "no-store" }).then((result) => result.ok ? result.json() : null);
          setPosts((current) => [{ id: body.id, title: String(values.get("title")), body: String(values.get("body")), username: me?.username || "我", created_at: body.created_at }, ...current]);
          form.reset(); setOpen(false); setBusy(false);
        }}>
          <label>问题标题<input name="title" required minLength={2} maxLength={120} /></label>
          <label>问题说明<textarea name="body" required minLength={5} rows={4} placeholder="说明目标、已尝试的方法与希望获得的帮助" /></label>
          {message && <p className="inline-error">{message} {needsLogin && <Link href="/login">去登录</Link>}</p>}
          <button className="button primary" disabled={busy}>{busy ? "发布中…" : "发布求助"}</button>
        </form>
      )}
      {posts.length > 0 ? (
        <div className="help-list">{posts.map((post) => (
          <article key={post.id}>
            <div><strong>{post.title}</strong><span>{post.username} · {formatDate(post.created_at)}</span></div>
            <p>{post.body}</p>
          </article>
        ))}</div>
      ) : <p className="quiet-empty">目前没有公开求助。</p>}
    </section>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}
