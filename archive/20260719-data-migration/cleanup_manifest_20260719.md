# 2026-07-19 空间清理审计

## 保留

- `/var/www/ord-samelabs/DSSToxCCDdump.csv`
  - SHA-256: `e69f56b35ce9d626810c6df2b5c79c48d0c3bb50ccde399da30687c6dd6d6a1b`
- `pubchem.dsstox_chemical_matches` 及 DSSTox 残余审计表
- `ord.legacy_rdkit_mol_map`
- `ord.legacy_reaction_map`
- `ord.legacy_rdkit_reaction_map`
- `pubchem.rdkit_mol_chemical_map`（迁移审计，暂留）

## 删除的可重建文件

- `/var/www/ord-samelabs/web/.next`：旧前端构建产物与缓存，约 3.9GB。
- `/var/www/ord-samelabs/CID-SMILES.gz`
  - SHA-256: `c1b26405f253160ac1e06d93989fd2e4800bb6ae353d38119eb59b2de1d1189f`
  - 导入元数据：124,001,345 行，状态 `complete`。
- `/var/www/ord-samelabs/CID-Identifiers.tsv.gz`
  - SHA-256: `e2678a1cf8df953d1d18a99bd5476153b416b1cebfe25ffc6a7c58a504ada987`
  - 导入元数据：7,339,625 个 CID、8,631,170 个值，状态 `complete`。
- `/var/www/ord-samelabs/CID-Synonym-filtered.gz`
  - SHA-256: `e9313082128814d38c905cdc9103698d5fadeaee0c44f0ccdb4376e3b6942de9`
  - 未导入；因噪声和来源混杂明确不进入第一版 chemicals。

## 删除的数据库派生对象

- `public.tmp_dsstox`：1,248,802 行，约 735MB；原始 DSSTox CSV 和匹配审计已保留。
- `ord.compound_identifier`：50,813,014 行，约 6.437GB；无孤儿、无双重挂载、无下游表或视图依赖。

删除前 `ord.compound_identifier` 类型统计：

```text
SMILES               18,860,951
NAME                 16,912,963
INCHI                13,582,325
CUSTOM                1,192,471
CAS_NUMBER              253,485
MOLBLOCK                  8,052
MDL                       2,736
IUPAC_NAME                   24
AMINO_ACID_SEQUENCE           7
```

其表结构备份为服务器上的
`/var/www/ord-samelabs/compound_identifier_schema_20260719.sql`。原始 ORD
protobuf 数据当前不在服务器；若未来要恢复这些值，需要重新取得对应 ORD 数据快照并重建。
