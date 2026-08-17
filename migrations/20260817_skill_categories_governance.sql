-- Skill 分类字典 + visibility 治理（2026-08-17 规范收口）。
-- 规则定稿：
--   * 分类唯一来源 = community.skill_categories；create/PATCH 校验字典内，违例 400
--   * visibility 单一路径：create 恒 private（服务端强制）；public 唯一入口 =
--     后台管理动作（PATCH /admin/skills/{id}/visibility），不再接受 create 参数
--   * 停用分类不物理删，历史引用不悬空
BEGIN;

CREATE TABLE community.skill_categories (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  abbr        text NOT NULL,
  color       text NOT NULL,
  sort_order  int  NOT NULL DEFAULT 100,
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE community.skill_categories
  ADD CONSTRAINT skill_categories_name_check CHECK (char_length(name) BETWEEN 1 AND 40),
  ADD CONSTRAINT skill_categories_abbr_check CHECK (abbr ~ '^[A-Z]{1,4}$'),
  ADD CONSTRAINT skill_categories_color_check CHECK (color ~ '^#[0-9a-f]{6}$');

-- 种子 = 现 DB 实际分类（13 类），色值/顺序取自原前端硬编码 map
INSERT INTO community.skill_categories (name, abbr, color, sort_order) VALUES
  ('化学反应记录', 'RX', '#0f5fba', 0),
  ('化学信息学',   'CI', '#1e90ff', 1),
  ('生物信息学',   'BI', '#0f9d58', 2),
  ('临床与医学',   'CM', '#e84393', 3),
  ('机器学习与AI', 'AI', '#6c5ce7', 4),
  ('统计分析',     'ST', '#fd7e14', 5),
  ('科研写作与文献','WR', '#00b894', 6),
  ('科学可视化',   'VZ', '#e17055', 7),
  ('数据处理',     'DP', '#0984e3', 8),
  ('平台集成',     'PI', '#a29bfe', 9),
  ('地球与物理科学','EP', '#2d3436', 10),
  ('研究方法论',   'RM', '#d63031', 11),
  ('通用工具',     'UT', '#636e72', 12);

-- 治理字段：谁发布的、何时、为什么（审计不悬空）
ALTER TABLE community.skills
  ADD COLUMN published_by   bigint REFERENCES community.users(id),
  ADD COLUMN published_at   timestamptz,
  ADD COLUMN publish_note   text;

ALTER TABLE community.skills
  ADD CONSTRAINT skills_publish_note_check CHECK (char_length(publish_note) <= 200);

CREATE INDEX skills_admin_list_idx ON community.skills(visibility, updated_at DESC);

COMMIT;
