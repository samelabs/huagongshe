import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";

export const metadata: Metadata = {
  title: "帮助指南",
  description: "把文献、专利或实验记录交给 AI，确认后发布到个人反应库。",
};

export default function GuidePage() {
  return <div className="content-page guide-page">
    <header className="guide-hero">
      <p className="page-kicker">GUIDE</p>
      <h1>把资料交给 AI，确认后发布</h1>
      <p>无需手工逐项整理。把文献、专利、实验记录或网页发给 AI，它会生成反应草稿；你核对后再发布。</p>
      <div className="guide-actions">
        <Link className="button primary" href="/me/settings/api-tokens">开始使用 AI</Link>
        <Link className="button secondary" href="/submit">直接填写发布</Link>
      </div>
    </header>

    <section className="guide-section">
      <div className="section-heading"><div><p>三步完成</p><h2>第一次连接后，只需发送资料</h2></div></div>
      <ol className="guide-steps">
        <li><strong>连接 AI</strong><span>创建 API Token，点击“复制给 AI”。这一步只需设置一次。</span></li>
        <li><strong>发送资料</strong><span>把文件、网页链接、图片或实验记录发给 AI。</span></li>
        <li><strong>确认发布</strong><span>检查 AI 整理的结构、条件和来源，确认后发布。</span></li>
      </ol>
    </section>

    <section className="guide-section guide-ai-section">
      <div className="section-heading"><div><p>直接复制</p><h2>让 AI 按统一格式整理</h2></div></div>
      <p className="guide-lead">如果你的 AI 暂时不能直接连接化工社，复制下面的提示词并和资料一起发送。AI 会先给出草稿，不会在你确认前发布。</p>
      <AiSubmissionPrompt />
    </section>

    <details className="guide-section technical-guide">
      <summary>AI 工具的可选配置</summary>
      <div className="technical-guide-content">
        <div>
          <h2>Skill 与接口说明</h2>
          <p>普通用户可以跳过。支持 Skill 的 AI 可安装规则文件；需要自行配置工具的用户可查看接口说明。</p>
        </div>
        <div className="guide-actions">
          <a className="button secondary small" href="/skills/huagongshe-reaction-publisher/SKILL.md" download>下载 Skill</a>
          <a className="button secondary small" href="/api/agent-guide" target="_blank" rel="noreferrer">查看接口说明</a>
        </div>
      </div>
    </details>

    <section className="guide-section ownership-guide">
      <div className="section-heading"><div><p>YOUR DATA</p><h2>管理你的反应</h2></div></div>
      <div className="guide-principles">
        <article><strong>归入个人反应库</strong><p>发布成功后，反应会保存到你的账号下。</p></article>
        <article><strong>由你持续维护</strong><p>你可以编辑、调整公开状态或删除自己发布的反应。</p></article>
        <article><strong>来源始终保留</strong><p>来源随反应保存；资料中没有的信息保持为空。</p></article>
      </div>
    </section>
  </div>;
}
