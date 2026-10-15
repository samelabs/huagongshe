import { SiteHeader } from "@/components/shell/SiteHeader";
import { WbMobileNav } from "@/components/workbench/WbMobileNav";
import { WbCreateMenu } from "@/components/workbench/WbCreateMenu";
import { getShellWorkbenchChrome } from "@/lib/shellData";

/**
 * AppShell — 根 layout 挂载的全站唯一外壳。
 *
 * 公开页与工作台共用同一实例；工作台路由时把服务端已取的手机动作
 * （抽屉菜单、创建入口）与未读数交给外壳，不靠重挂外壳切换形态。
 */
export async function AppShell() {
  const chrome = await getShellWorkbenchChrome();
  if (!chrome) return <SiteHeader />;
  return (
    <SiteHeader
      initialUnread={chrome.counts?.unread ?? 0}
      mobileActions={<><WbCreateMenu /><WbMobileNav counts={chrome.counts} user={chrome.user} /></>}
    />
  );
}
