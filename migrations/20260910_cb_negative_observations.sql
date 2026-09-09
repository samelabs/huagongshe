-- 2026-09-10  B-minimal: CB negative observations (只读审计后的 absence semantics)
--
-- 不变量 (用户令, 2026-09-10):
-- 1. chemistry.chemical_cb 继续只承载 positive source data
--    (本机制绝不向其写 last_status='not_found')。
-- 2. maintenance.cas_jobs 继续只承载 queued/leased/error;
--    ok/not_found complete 后 DELETE 契约不变。
-- 3. negative observation 不带 chemical_id, 不进入 identity merge registry
--    (absorb/rekey 对本表零影响 — 表内根本没有行主键关联)。
-- 4. ERROR 永远不得创建 negative observation (判定单点在 caslib,
--    只有上游明确回答"没有"才落本表)。
--
-- key grain (审计 §9): 三种 negative fact 不得折叠 —
--   cas_locator  : CAS 在 CB 不存在 (搜索 miss / zh 链未拿到 cb_number)
--   locale_variant: (cb_number, locale) 无语言变体 (zh 有 / en 无 = 正常事实)
-- source-record grain (CB 号 404) 本轮禁实现 — 仍属 ERROR。

BEGIN;

CREATE TABLE IF NOT EXISTS maintenance.cb_negative_observations (
    negative_key      text PRIMARY KEY,
    kind              text NOT NULL,
    cas_number        text,
    cb_number         text,
    locale            text,
    first_observed_at timestamptz NOT NULL DEFAULT now(),
    observed_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cb_negative_kind_check
        CHECK (kind IN ('cas_locator', 'locale_variant')),
    -- shape: cas_locator → cas_number 非空, cb_number/locale 为空
    CONSTRAINT cb_negative_cas_locator_shape_check
        CHECK (kind <> 'cas_locator'
               OR (cas_number IS NOT NULL
                   AND cb_number IS NULL AND locale IS NULL)),
    -- shape: locale_variant → cb_number + locale 非空, cas_number 为空
    CONSTRAINT cb_negative_locale_variant_shape_check
        CHECK (kind <> 'locale_variant'
               OR (cb_number IS NOT NULL AND locale IS NOT NULL
                   AND cas_number IS NULL))
);

COMMIT;
