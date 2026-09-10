-- 2026-08-31 收口: 老表 chemical_supplier 摘除。
-- 背景: 双表并行期结束 — profile/listing 两表已完成存量迁移(带sid 264,572行直接迁入,
-- 无sid 193,597行按名字映射迁入), 代码侧双写/双读回退桥已拆除(api/services/cb.py),
-- 老表无引用后 DROP。数据不备份(用户裁定); 924 行无sid孤儿(569家无档小公司)随之消失。

DROP TABLE IF EXISTS chemistry.chemical_supplier;
