"use client";

import { useState } from "react";
import t from "@/lib/i18n";

const prompt = `请作为我的化工社反应整理助手。

我会提供网页、文献、专利、实验文档、图片或一段文字。请完成：
1. 只提取资料中明确存在的反应事实，不猜测 SMILES、条件、用量、收率或来源。
2. 将参与物整理为反应物、产物、试剂、催化剂和溶剂，并把结构规范为 SMILES。
3. 保留 DOI、专利号、网址、文献题目或“本人实验”等来源证据。
4. 未知的可选字段留空；结构或身份有歧义时先问我。
5. 先给我查看结构化草稿；整理结果保存到我的个人反应库，默认仅自己可见。
6. 得到我确认后，先调用化工社验证接口，再使用唯一 Idempotency-Key 保存。
7. 成功后告诉我 HRID、页面链接、新建的 HCID 和可见范围；未经成功响应不要声称已经保存。

如果你暂时不能调用化工社 API，请仍按相同字段输出草稿，并指导我在网页保存。`;

export function AiSubmissionPrompt() {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  return <div className="prompt-box">
    <pre>{prompt}</pre>
        <button type="button" className="button secondary small" onClick={copy}>{copied ? t.guide.copyPrompt(true) : t.guide.copyPrompt(false)}</button>
  </div>;
}
