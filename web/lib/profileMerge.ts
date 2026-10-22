/** 资料设置页迟到 GET 的按字段合并。
 *
 * GET 在途时用户可能已改了某些字段(如 display_name)。若整份丢弃 GET 初值,
 * 未改字段(bio 等)保持空串, 保存时会把服务端已有资料清空。因此逐字段
 * 合并: 用户改过的字段保留当前输入, 没改过的字段用 GET 返回值回填;
 * 保存提交的即合并后的完整资料。
 */
export type ProfileFields = {
  display_name: string;
  bio: string;
  email: string;
  location: string;
  institution: string;
  title: string;
  website: string;
  orcid: string;
};

export const PROFILE_FIELD_KEYS: ReadonlyArray<keyof ProfileFields> = [
  "display_name", "bio", "email", "location",
  "institution", "title", "website", "orcid",
];

export function mergeLateProfile(
  current: ProfileFields,
  incoming: Readonly<Partial<Record<keyof ProfileFields, unknown>>>,
  touched: ReadonlySet<keyof ProfileFields>,
): ProfileFields {
  const next: ProfileFields = { ...current };
  for (const key of PROFILE_FIELD_KEYS) {
    if (touched.has(key)) continue;
    const value = incoming[key];
    next[key] = typeof value === "string" ? value : "";
  }
  return next;
}
