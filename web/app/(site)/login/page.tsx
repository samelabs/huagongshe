import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  // S4 (G1.5-A): 登录页不参与索引(鉴权入口无索引价值), 仍可跟随回跳链接
  return { title: t.auth.title, robots: { index: false, follow: true } };
}
/** 6.9 登录/注册（框架 E）：单卡 ≤400，next 回跳逻辑不动。 */
export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const query = await searchParams;
  const nextPath = safeNextPath(typeof query.next === "string" ? query.next : null);
  return (
    <div className="auth-page">
      <div className="auth-panel">
        <AccountForm nextPath={nextPath} />
      </div>
    </div>
  );
}

function safeNextPath(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/aichem";
}

