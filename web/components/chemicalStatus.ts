/**
 * Chemical Detail 内部补全在途判定。
 *
 * 只为 DetailRefresher 的轮询服务 —— 不再有面向用户的"数据状态"表达,
 * 因此不暴露底层数据源名称, 也不保留 rail 专用状态映射(已随 Data Status 移除)。
 *
 * 原则(PM review #4 保留项):
 *  - 空数据不得推断为 in flight; 只有服务端 state === "queued" 才是在途,
 *    否则 fresh negative 会被持续轮询。
 */

/** 在途 = 服务端真实 queued; 空数据不算在途。 */
export function cbInFlight(state: string | null | undefined): boolean {
  return state === "queued";
}
