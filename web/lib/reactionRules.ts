/**
 * reactionRules — 反应录入表单的校验规则单一来源（前端侧）。
 *
 * 数值范围、长度上限、枚举与配对规则与后端 ReactionBody/ParticipantBody
 * schema 逐项对账（tests/test_reaction_rules_contract.py 在后端侧锁死两
 * 边一致）；改任何一条先改后端 schema，再同步本文件，对账测试会拦住
 * 漏改。表单与提交前校验一律引用本常量，不得各自另写一份。
 */

export const REACTION_RULES = {
  /** 参与物行数（含角色去重前的全部行） */
  participantsMin: 2,
  participantsMax: 100,
  smilesMaxLength: 4000,
  /** 出现次数：整数 */
  occurrenceCountMin: 1,
  occurrenceCountMax: 20,
  /** 投料量 / 当量 / 浓度取值下限（闭区间 0） */
  nonNegativeMin: 0,
  yieldMin: 0,
  yieldMax: 100,
  /** 反应时长：必须大于 0（开区间） */
  durationExclusiveMin: 0,
  phMin: 0,
  phMax: 14,
  /** 压强：必须大于 0（开区间） */
  pressureExclusiveMin: 0,
  amountUnitMaxLength: 40,
  atmosphereMaxLength: 120,
  doiMaxLength: 300,
  /** 与后端 normalize_doi 的 DOI_RE 同源（前导 10. 前缀 + 后缀非空白） */
  doiPattern: "^10\\.\\d{4,9}/\\S+$",
  patentMaxLength: 300,
  sourceUrlMaxLength: 1000,
  sourceUrlSchemes: ["http://", "https://"],
  sourceCitationMaxLength: 2000,
  procedureMaxLength: 30000,
  textAreaMaxLength: 10000,
  temperatureUnits: ["CELSIUS", "KELVIN"],
  durationUnits: ["MINUTE", "HOUR", "DAY"],
  /** 来源类型 → 必填的来源字段 */
  requiredSourceField: {
    doi: "doi",
    patent: "patent",
    database: "source_citation",
    url: "source_url",
    other: "source_citation",
  } as Record<string, string>,
} as const;

export const DOI_RE = new RegExp(REACTION_RULES.doiPattern, "i");
