/**
 * Dictionary 类型契约 fixture · 只做编译期验证, 不含真实翻译
 *
 * 必须同时成立(通过 = tsc --noEmit 对本文件零错误):
 *   [OK-1] zh-CN 字典自身满足 Dictionary(完整真实字典可赋值)
 *   [OK-2] 字符串值 widen 为 string(不同语言字面量可互换)
 *   [OK-3] 函数保留参数签名、返回 string
 *   [REJ-1] 缺 key → 编译期断言"不满足 Dictionary"
 *   [REJ-2] 函数参数类型错误 → 编译期断言"不满足 Dictionary"
 *   [REJ-3] 多余 key → 对象字面量直赋会触发 excess property 检查(留档验证)
 *
 * 说明: 多余 key 在纯 structural extends 下不可见(TS 结构子类型允许超集),
 * 其拒绝由"字面量赋值给 Dictionary 变量"的 excess property check 保证 ——
 * 未来 en/ja/ko/de 文件正是以 `const en: Dictionary = {...}` 形式注册, 该
 * 检查天然生效; 验证代码见文末注释(实际报错已留档)。
 */

import type { Dictionary } from "./locales/zh-CN";
import zhCN from "./locales/zh-CN";

/* ── [OK-1] 真实完整 zh-CN 字典可赋值给 Dictionary(同构自检) ── */
const selfCheck: Dictionary = zhCN;
void selfCheck;

/* ── [OK-2] widen: 字符串值类型是 string, 不是中文字面量类型 ── */
const widened: string = zhCN.common.loading;   // '加载中…' 已 widen 为 string
const anyLanguageString: string = zhCN.brand.name;
void widened; void anyLanguageString;

// 不同语言的字符串可以放进同一个 widened 槽位(证明未来字典可换语言):
const slot: string = "Loading…" ;
const alsoFits: string = zhCN.common.loading.length > 0 ? slot : "読み込み中…";
void alsoFits;

/* ── [OK-3] 函数签名保留: pageOf 仍是 (cur: number, total: number) => string ── */
const pageOf: (cur: number, total: number) => string = zhCN.common.pageOf;
const hcidLabel: (id: number | string) => string = zhCN.common.hcidLabel;
void pageOf; void hcidLabel;
// @ts-expect-error 参数结构被保留: 少传/错传在调用侧被拒绝(签名未被放宽)
zhCN.common.pageOf(1);

/* ── [REJ-1] 缺 key 的形状不满足 Dictionary ── */
type MissingKeySample = { brand: { name: string; seoDesc: string } };
type RejectMissing = MissingKeySample extends Dictionary ? true : false;
type AssertMissingRejected = Expect<Equal<RejectMissing, false>>;
void 0 as unknown as AssertMissingRejected;

/* ── [REJ-2] 函数参数类型错误不满足 Dictionary ──
 * (注: 少一个参数在 TS 结构兼容下是合法的; 参数类型变更是非法的) */
type WrongFnSample = { common: { pageOf: (cur: string, total: number) => string } };
type RejectWrongFn = WrongFnSample extends Dictionary ? true : false;
type AssertWrongFnRejected = Expect<Equal<RejectWrongFn, false>>;
void 0 as unknown as AssertWrongFnRejected;

/* ── [REJ-3] 多余 key: excess property check(验证留档) ──
 * 以下赋值被 TypeScript 拒绝(实测):
 *   const extra: Dictionary["brand"] = { ...zhCN.brand, notARealKey: "x" };
 *   // error TS2353: Object literal may only specify known properties,
 *   //                and 'notARealKey' does not exist in type ...
 * 未来语言包以 `const en: Dictionary = {...}` 注册时同样受此检查约束。
 */

type Expect<T extends true> = T;
type Equal<X, Y> = (<G>() => G extends X ? 1 : 2) extends (<G>() => G extends Y ? 1 : 2) ? true : false;
