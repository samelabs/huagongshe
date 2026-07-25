import Link from "next/link";
export default function NotFound() { return <div className="empty-state"><p>没有找到这条记录</p><Link className="text-link" href="/">返回搜索</Link></div>; }
