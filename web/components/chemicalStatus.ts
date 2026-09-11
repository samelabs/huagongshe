/**
 * Chemical Detail data-status 语义映射(唯一实现)。
 *
 * 只做 UI 映射, 不改 API:
 *  - PubChem 状态来自 `EnrichmentState.status`(queued | stale | current)
 *  - ChemicalBook 状态直接来自 `externals.state`(queued | stale | fresh | absent | no_cas)
 *
 * 原则(PM review #4):
 *  - stale 不得显示为"最新"
 *  - CB 空数据不得推断为 in flight; 只有服务端 state === "queued" 才是在途
 *  - externals 请求失败(state === null)显示"暂不可用/—", 不得显示 queued
 */

export type DataStatus = "queued" | "stale" | "current" | "none" | "unavailable";
export type EnrichmentStatus = "queued" | "stale" | "current";

/** PubChem: queued → 补全中; stale → 待刷新; current + CID → 最新; 无 CID → 暂无 */
export function pubchemDataStatus(status: EnrichmentStatus, hasCid: boolean): DataStatus {
  if (status === "queued") return "queued";
  if (status === "stale") return "stale";
  return hasCid ? "current" : "none";
}

/**
 * ChemicalBook: 有 entry 或 supplier → 当前已有数据; queued → 补全中;
 * 其他空数据状态(fresh negative / absent / no_cas) → 暂无;
 * state === null(externals 请求本身失败) → 暂不可用。
 */
export function cbDataStatus(state: string | null, hasData: boolean): DataStatus {
  if (state === null) return "unavailable";
  if (state === "queued") return "queued";
  if (state === "stale") return "stale";
  return hasData ? "current" : "none";
}

/** 在途 = 服务端真实 queued; 空数据不算在途(避免 fresh negative 被持续轮询)。 */
export function cbInFlight(state: string | null | undefined): boolean {
  return state === "queued";
}
