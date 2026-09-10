-- 0001_bootstrap_reference_data.sql
-- Fresh DB bootstrap reference data(schema 之外的运行必需配置行)。
-- 这是 bootstrap reference data, 不是生产数据快照:
--  - 计数一律中性初值 0, 禁止复制 production exact_count;
--  - 不含用户/worker/业务数据。

BEGIN;

-- community.skill_categories: 13 条正式分类字典(api/skills.py 运行时依赖)
INSERT INTO community.skill_categories (id, name, abbr, color, sort_order, active)
OVERRIDING SYSTEM VALUE VALUES
    (1,  '化学反应记录',   'RX', '#0f5fba', 0,  true),
    (2,  '化学信息学',     'CI', '#1e90ff', 1,  true),
    (3,  '生物信息学',     'BI', '#0f9d58', 2,  true),
    (4,  '临床与医学',     'CM', '#e84393', 3,  true),
    (5,  '机器学习与AI',   'AI', '#6c5ce7', 4,  true),
    (6,  '统计分析',       'ST', '#fd7e14', 5,  true),
    (7,  '科研写作与文献', 'WR', '#00b894', 6,  true),
    (8,  '科学可视化',     'VZ', '#e17055', 7,  true),
    (9,  '数据处理',       'DP', '#0984e3', 8,  true),
    (10, '平台集成',       'PI', '#a29bfe', 9,  true),
    (11, '地球与物理科学', 'EP', '#2d3436', 10, true),
    (12, '研究方法论',     'RM', '#d63031', 11, true),
    (13, '通用工具',       'UT', '#636e72', 12, true);
SELECT setval(pg_get_serial_sequence('community.skill_categories', 'id'),
              (SELECT max(id) FROM community.skill_categories));

-- chemistry.statistics: 应用依赖的 metric rows(admin 计数/首页统计), 中性初值 0
INSERT INTO chemistry.statistics (metric, exact_count, calculated_at) VALUES
    ('chemicals', 0, now()),
    ('reactions', 0, now());

COMMIT;
