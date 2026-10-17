#!/usr/bin/env python3
"""name_index 多语言回填 executor(可续跑)。

CB 摄入把全部 locale 的名称写进 name_index(source='cb');
历史行只有 zh-CN 的名称。本脚本按 chemical_id 分批重建存量化合物的
source='cb' 镜像(与 services/name_index.ingest_from_cb_locales 同一
语义: 全 locale ok 行并集 + 供应商档案名), 不触碰 source='pubchem' 行。

契约:
  - 按 chemical_id 升序分批(默认 500 个/批), 每批一个事务;
  - 断点续跑: 默认从头开始, --since-chemical-id 从指定 id(含)之后继续
    (进度打印当前批末 id, 中断后从该 id 续);
  - --dry-run: 只统计不写 —— 逐化合物计算目标行数(含排除 preferred/
    iupac 同名)与预计新增行数、估算体积, 结束打印汇总;
  - 只处理"有 chemical_cb 行"的 chemical_id(distinct), 全表扫描按
    chemical_cb 索引分批驱动, 不锁写(name_index 删插按 chemical_id 定位);
  - 生产规模参考(PM 口径): chemical_cb ≈ 430 万行(五 locale 各 ≈85 万),
    name_index 现有 1820 万行 / 6.9 GB。回填由 PM 在用户确认后执行,
    本脚本不进迁移、不自动调度。

用法:
  python scripts/backfill_name_index_locales.py --dry-run
  python scripts/backfill_name_index_locales.py --since-chemical-id 123456
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

# 直接 `python scripts/backfill_name_index_locales.py` 执行时, sys.path[0]
# 是 scripts/ 而非仓库根 —— 显式补根目录, 使 api.* 可导入(不依赖部署侧
# PYTHONPATH/WorkingDirectory 约定)。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BATCH = 500
# name_index 单行平均体积估算(dry-run 用): 现状 6.9GB/1820万行 ≈ 380B/行,
# 多语言行名称偏长(日韩文 UTF-8 3 字节/字符), 取 400B 上浮口径。
BYTES_PER_ROW_ESTIMATE = 400


async def _iter_ids(conn, since: int, batch: int):
    """按 id 升序分批产出"有 chemical_cb 行"的 chemical_id 列表。"""
    last = since
    while True:
        rows = (await conn.execute(text("""
            SELECT DISTINCT chemical_id FROM chemistry.chemical_cb
            WHERE chemical_id > :last
            ORDER BY chemical_id LIMIT :batch
        """), {"last": last, "batch": batch})).scalars().all()
        if not rows:
            return
        yield rows
        last = rows[-1]


async def _rebuild_one(conn, chemical_id: int) -> int:
    """与 ingest_from_cb_locales 同语义重建单个化合物的 cb 镜像, 返回行数。"""
    from api.services.name_index import ingest_from_cb_locales
    return await ingest_from_cb_locales(conn, chemical_id)


async def _estimate_one(conn, chemical_id: int) -> tuple[int, int]:
    """dry-run: (目标总行数近似, 其中非 zh-CN 来源的预计新增行数)。"""
    rows = (await conn.execute(text("""
        SELECT locale,
               CASE WHEN jsonb_typeof(entry->'identity'->'cn') = 'string'
                    THEN 1 ELSE 0 END AS cn_n,
               CASE WHEN jsonb_typeof(entry->'identity'->'alias_cn') = 'array'
                    THEN jsonb_array_length(entry->'identity'->'alias_cn')
                    ELSE 0 END AS alias_cn_n,
               CASE WHEN jsonb_typeof(entry->'identity'->'alias_en') = 'array'
                    THEN jsonb_array_length(entry->'identity'->'alias_en')
                    ELSE 0 END AS alias_en_n
        FROM chemistry.chemical_cb
        WHERE chemical_id=:id AND last_status='ok'
    """), {"id": chemical_id})).all()
    total = sum(int(r[1] or 0) + int(r[2] or 0) + int(r[3] or 0) for r in rows)
    zh = sum(int(r[1] or 0) + int(r[2] or 0)
             for r in rows if r[0] == "zh-CN")
    # 非 zh locale 的当地名+别名是纯新增; alias_en 历史已有(去重近似不新增)。
    new_rows = max(total - zh - sum(int(r[3] or 0) for r in rows), 0)
    return total, new_rows


async def run(*, dry_run: bool, since: int, batch: int) -> int:
    from api.core.database import async_session
    processed = 0
    rebuilt_rows = 0
    est_total = 0
    est_new = 0
    async with async_session() as session:
        async for ids in _iter_ids(session, since, batch):
            for chemical_id in ids:
                if dry_run:
                    total_rows, new_rows = await _estimate_one(session, chemical_id)
                    est_total += total_rows
                    est_new += new_rows
                else:
                    rebuilt_rows += await _rebuild_one(session, chemical_id)
                processed += 1
            if not dry_run:
                await session.commit()
            if dry_run:
                print(f"[name-index-locales] dry-run processed={processed} "
                      f"last_chemical_id={ids[-1]} est_rows={est_total} "
                      f"est_new={est_new}", flush=True)
            else:
                print(f"[name-index-locales] processed={processed} "
                      f"last_chemical_id={ids[-1]} rebuilt_rows={rebuilt_rows}",
                      flush=True)
    if dry_run:
        print(f"[name-index-locales] DRY-RUN summary: chemicals={processed} "
              f"est_target_rows={est_total} est_new_rows={est_new} "
              f"est_new_bytes≈{est_new * BYTES_PER_ROW_ESTIMATE} "
              f"(≈{est_new * BYTES_PER_ROW_ESTIMATE / 1e9:.2f} GB)",
              flush=True)
    else:
        print(f"[name-index-locales] summary: chemicals={processed} "
              f"rebuilt_rows={rebuilt_rows}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计预计行数/体积, 不写库")
    parser.add_argument("--since-chemical-id", type=int, default=0,
                        help="从该 chemical_id(不含)之后继续, 断点续跑")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                        help="每批 chemical_id 数(默认 500)")
    args = parser.parse_args()
    if args.batch < 1 or args.batch > 5000:
        parser.error("--batch 须在 1..5000")
    try:
        return asyncio.run(run(dry_run=args.dry_run,
                               since=args.since_chemical_id,
                               batch=args.batch))
    except KeyboardInterrupt:
        print("[name-index-locales] interrupted; resume with "
              "--since-chemical-id <last printed id>", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
