import type { Metadata } from "next";
import Link from "next/link";
import { AiSubmissionPrompt } from "@/components/AiSubmissionPrompt";

export const metadata: Metadata = {
  title: "帮助指南",
  description: "使用网页表单或 AI 整理并提交化学反应。",
};

export default function GuidePage() {
  return <div className="content-page guide-page">
    <header className="guide-hero">
      <p className="page-kicker">GUIDE</p>
      <h1>使用 AI 整理并提交反应</h1>
      <p>提供文献、专利、实验记录或网页。AI 整理结构化数据，经你确认后提交到个人反应库。</p>
      <div className="guide-actions">
        <Link className="button primary" href="/submit">网页发布</Link>
        <Link className="button secondary" href="/me/settings/api-tokens">创建 API Token</Link>
      </div>
    </header>

    <section className="guide-section">
      <div className="section-heading"><div><p>WORKFLOW</p><h2>提交步骤</h2></div></div>
      <ol className="guide-steps">
        <li><strong>提供来源</strong><span>发送文件、网页链接或实验记录。</span></li>
        <li><strong>核对数据</strong><span>确认结构、角色、条件、结果和来源。</span></li>
        <li><strong>提交反应</strong><span>选择公开或私有；校验通过后生成 HRID。</span></li>
      </ol>
    </section>

    <section className="guide-section guide-ai-section">
      <div className="section-heading"><div><p>CONVERSATION</p><h2>对话提示词</h2></div></div>
      <p className="guide-lead">将提示词与文献、网页或实验记录一并发送给 AI。无法调用 API 时，可先生成草稿，再通过网页表单提交。</p>
      <AiSubmissionPrompt />
    </section>

    <section className="guide-section skill-guide">
      <div>
        <p className="page-kicker">AI SKILL</p>
        <h2>化工社反应发布 Skill</h2>
        <p>该 Skill 定义来源核对、结构整理、用户确认、接口校验和幂等提交规则。</p>
        <div className="guide-actions">
          <a className="button primary" href="/skills/huagongshe-reaction-publisher/SKILL.md" download>下载 SKILL.md</a>
          <a className="button secondary" href="/api/agent-guide" target="_blank" rel="noreferrer">查看 AI 接口规则</a>
        </div>
      </div>
      <div className="skill-install">
        <strong>使用方法</strong>
        <ol>
          <li>在账户设置中创建 API Token。</li>
          <li>将 SKILL.md 加入 AI 的技能目录，或直接发送给 AI。</li>
          <li>提供反应资料；确认草稿后提交。</li>
        </ol>
        <p>API Token 当前用于查询、验证和创建。反应的编辑、可见性调整与删除由用户在化工社网页完成。</p>
      </div>
    </section>

    <section className="guide-section ownership-guide">
      <div className="section-heading"><div><p>YOUR DATA</p><h2>管理你的反应</h2></div></div>
      <div className="guide-principles">
        <article><strong>直接保存</strong><p>提交成功后，反应进入你的公开或私有反应库。</p></article>
        <article><strong>自主维护</strong><p>你可以编辑、调整可见性或删除自己创建的反应。</p></article>
        <article><strong>保留来源</strong><p>来源随反应保存；无法确认的信息应留空。</p></article>
      </div>
    </section>
  </div>;
}
