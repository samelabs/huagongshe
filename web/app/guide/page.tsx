import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";

export const metadata: Metadata = {
  title: "帮助指南",
  description: "使用网页或 AI 整理、发布和维护自己的化学反应。",
};

export default function GuidePage() {
  return <div className="content-page guide-page">
    <header className="guide-hero">
      <p className="page-kicker">GUIDE</p>
      <h1>把反应资料交给 AI，整理后收入你的仓库</h1>
      <p>网页、文献、专利、实验文档或图片都可以作为起点。AI 负责整理结构和字段，你确认事实与可见性，化工社负责校验、建立 HCID 关联并生成 HRID。</p>
      <div className="guide-actions">
        <Link className="button primary" href="/submit">网页发布</Link>
        <Link className="button secondary" href="/me/settings">创建 Agent Token</Link>
      </div>
    </header>

    <section className="guide-section">
      <div className="section-heading"><div><p>WORKFLOW</p><h2>最短发布路径</h2></div></div>
      <ol className="guide-steps">
        <li><strong>提供资料</strong><span>上传文件、粘贴网址或直接描述本人的实验反应。</span></li>
        <li><strong>核对草稿</strong><span>AI 整理结构、角色、条件、收率和来源；未知项保持为空。</span></li>
        <li><strong>确认发布</strong><span>选择公开或私有。验证通过后直接生成 HRID，归入你的反应仓库。</span></li>
      </ol>
    </section>

    <section className="guide-section guide-ai-section">
      <div className="section-heading"><div><p>CONVERSATION</p><h2>直接交给对话式 AI</h2></div></div>
      <p className="guide-lead">把下面的提示词连同网页链接或文件一起发给 AI。没有 API 能力的 AI 也可以先生成结构化草稿，再由你粘贴到网页表单。</p>
      <AiSubmissionPrompt />
    </section>

    <section className="guide-section skill-guide">
      <div>
        <p className="page-kicker">AI SKILL</p>
        <h2>化工社反应发布 Skill</h2>
        <p>Skill 为支持技能文件的 AI 提供稳定工作流：读取实时 OpenAPI、保留来源、不编造事实、请求用户确认、验证后幂等提交。</p>
        <div className="guide-actions">
          <a className="button primary" href="/skills/huagongshe-reaction-publisher/SKILL.md" download>下载 SKILL.md</a>
          <a className="button secondary" href="/api/agent-guide" target="_blank" rel="noreferrer">查看 Agent 契约</a>
        </div>
      </div>
      <div className="skill-install">
        <strong>使用方法</strong>
        <ol>
          <li>在“账号与 Agent”创建 Token；明文只保存一次。</li>
          <li>把 SKILL.md 放入 AI 的技能目录，或直接把文件发给 AI。</li>
          <li>提供资料并调用该 Skill；正式发布前由 AI 向你确认。</li>
        </ol>
        <p>Token 仅用于查询、验证和创建。反应的编辑、可见性调整与删除由用户在化工社网页完成。</p>
      </div>
    </section>

    <section className="guide-section ownership-guide">
      <div className="section-heading"><div><p>YOUR DATA</p><h2>发布后仍由你管理</h2></div></div>
      <div className="guide-principles">
        <article><strong>直接归档</strong><p>没有待审核副本。成功提交后直接进入你的公开或私有反应仓库。</p></article>
        <article><strong>持续维护</strong><p>创建者可以编辑结构化内容、切换可见性或删除自己的反应。</p></article>
        <article><strong>事实可核对</strong><p>来源随反应保存；未知信息可以为空，平台不要求为了“完整”而猜测。</p></article>
      </div>
    </section>
  </div>;
}
