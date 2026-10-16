/**
 * 写剪贴板的唯一实现。剪贴板 API 只在安全上下文（https / localhost）可用；
 * 其余情况（如局域网 http 访问）退回临时文本域选区 + execCommand("copy")。
 * 返回是否成功，由调用方给出反馈。
 */
export async function copyText(value: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      return false;
    }
  }
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  area.remove();
  return ok;
}
