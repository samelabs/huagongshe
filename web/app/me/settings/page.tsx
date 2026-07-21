import Link from "next/link";

const items = [
  { href: "/me/settings/profile", label: "公开资料", text: "修改展示名称和简介。" },
  { href: "/me/settings/avatar", label: "头像", text: "更新公开头像。" },
  { href: "/me/settings/security", label: "密码安全", text: "修改密码并注销现有凭据。" },
  { href: "/me/settings/api-tokens", label: "API Token", text: "创建或撤销 API 访问凭据。" },
];

export default function SettingsPage() {
  return <div className="settings-overview"><div className="settings-section-title"><p>ACCOUNT</p><h2>选择一项设置</h2></div><div className="settings-cards">{items.map((item) => <Link href={item.href} key={item.href}><strong>{item.label}</strong><span>{item.text}</span><em aria-hidden="true">→</em></Link>)}</div></div>;
}
