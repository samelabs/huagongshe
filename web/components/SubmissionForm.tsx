"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

export function SubmissionForm() {
  const search = useSearchParams();
  const initial = search.get("type") === "reaction" ? "reaction" : "chemical";
  const [kind, setKind] = useState<"chemical" | "reaction">(initial);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <div className="tabs">
        <button className={kind === "chemical" ? "active" : ""} onClick={() => setKind("chemical")}>化合物</button>
        <button className={kind === "reaction" ? "active" : ""} onClick={() => setKind("reaction")}>反应</button>
      </div>
      <form className="form-stack" onSubmit={async (event) => {
        event.preventDefault(); setBusy(true); setMessage(null);
        const values = new FormData(event.currentTarget);
        const payload = kind === "chemical"
          ? { smiles: values.get("smiles") || null, cas: values.get("cas") || null, note: values.get("note") || null }
          : { reaction_smiles: values.get("reaction_smiles"), note: values.get("note") || null };
        const response = await fetch(`/api/community/${kind}-submissions`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        if (response.status === 401) { setMessage({ ok: false, text: "请先登录后提交" }); setBusy(false); return; }
        const body = await response.json().catch(() => null);
        if (!response.ok) { setMessage({ ok: false, text: body?.detail || "校验失败" }); setBusy(false); return; }
        setMessage({ ok: true, text: `已通过格式校验并进入审核队列（#${body.id}）` });
        event.currentTarget.reset(); setBusy(false);
      }}>
        {kind === "chemical" ? (
          <>
            <label>SMILES<input name="smiles" placeholder="例如 CCO" /></label>
            <label>CAS<input name="cas" placeholder="例如 64-17-5" /></label>
            <p className="result-sub">至少填写一项。结构通过校验后匹配现有化合物。</p>
          </>
        ) : (
          <>
            <label>反应 SMILES<textarea name="reaction_smiles" required placeholder="reactants&gt;agents&gt;products" /></label>
            <p className="result-sub">反应物和产物中的每个结构都会先进行格式校验。</p>
          </>
        )}
        <label>说明（可选）<textarea name="note" placeholder="来源、条件、需要补充或纠正的内容" /></label>
        {message && <p className={`form-message ${message.ok ? "ok" : "bad"}`}>{message.text}</p>}
        <button className="button primary" disabled={busy}>{busy ? "校验中…" : "校验并提交"}</button>
      </form>
    </>
  );
}
