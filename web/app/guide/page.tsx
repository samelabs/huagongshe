import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";

export const metadata: Metadata = {
  title: "帮助指南",
  description: "使用 AI 整理文献、专利或实验记录，并保存到个人反应库。",
};

export default function GuidePage() {
  return <div className="content-page guide-page">
    <header className="guide-hero">
      <p className="page-kicker">GUIDE</p>
      <h1>用 AI 整理你的反应资料</h1>
      <p>AI 可以从文献、专利、实验记录或网页中整理反应条目。你核对后保存到个人反应库，数据由你自己管理。</p>
      <div className="guide-actions">
        <Link className="button primary" href="/me/settings/api-tokens">使用 AI 整理</Link>
        <Link className="button secondary" href="/submit">手动填写</Link>
      </div>
    </header>

    <section className="guide-section">
      <div className="section-heading"><div><p>三步完成</p><h2>从原始资料到个人反应库</h2></div></div>
      <ol className="guide-steps">
        <li><strong>连接 AI</strong><span>创建 API Token，点击“复制给 AI”。这一步只需设置一次。</span></li>
        <li><strong>提供资料</strong><span>选择文件、网页链接、图片或实验记录，让 AI 进行整理。</span></li>
        <li><strong>核对保存</strong><span>检查整理后的结构、条件和来源，保存到你的反应库。</span></li>
      </ol>
    </section>

    <section className="guide-section guide-ai-section">
      <div className="section-heading"><div><p>直接复制</p><h2>让 AI 按统一格式整理</h2></div></div>
      <p className="guide-lead">如果你的 AI 暂时不能直接连接化工社，复制下面的提示词并与资料一起使用。AI 会先生成草稿，由你核对和保存。</p>
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
        <article><strong>保存到个人反应库</strong><p>整理后的反应归入你的账号，形成自己的数据档案。</p></article>
        <article><strong>由你持续维护</strong><p>你可以随时编辑、管理或删除自己保存的反应。</p></article>
        <article><strong>来源始终保留</strong><p>来源随反应保存；资料中没有的信息保持为空。</p></article>
      </div>
    </section>
  </div>;
}
