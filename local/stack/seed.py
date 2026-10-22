#!/usr/bin/env python3
"""seed.py — 本地栈种子数据。

只通过 HTTP API(默认 http://127.0.0.1:8000)写入, 不直接碰数据库。
可重复执行: 注册 409 视为已存在; 反应用固定 Idempotency-Key 重放;
笔记先查重再创建; follow 类端点本身 ON CONFLICT DO NOTHING。

账号(密码在 .env.local, 随机生成, 非真实账号):
  hgs_demo  展示名 SUN Demo
  hgs_peer  展示名 Lin Demo
  hgs_admin 展示名 Admin Demo（role=admin，供 /samelabs 管理页验收；
            角色经本地 docker psql 授予，只存在于本 seed，不进生产脚本）

内容:
  hgs_demo: 2 条公开反应 + 1 条私有反应(阿司匹林合成等真实简单 SMILES),
            2 篇笔记(公开关联 HCID+HRID / 私有关联 HCID), 收藏 3 个化合物,
            关注 hgs_peer(在 peer 建反应之前, 以触发 new_reaction 动态)
  hgs_peer: 2 条公开反应, 关注 hgs_demo

用法: python3 seed.py [--base http://127.0.0.1:8000]
输出: JSON 摘要写到 stdout; 幂等重跑数据不变。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

STACK = Path(__file__).resolve().parent
ENV = dict(
    line.split("=", 1) for line in (STACK / ".env.local").read_text().splitlines()
    if line and not line.startswith("#")
)

API = "http://127.0.0.1:8000/api"
TIMEOUT = 60


def call(method: str, path: str, body: dict | None = None, token: str | None = None,
         headers: dict | None = None) -> tuple[int, dict | list | bytes]:
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Cookie", f"hgs_session={token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read()
            # login 的会话令牌只经 Set-Cookie 下发, 从这里取
            for sc in res.headers.get_all("Set-Cookie") or []:
                if sc.startswith("hgs_session="):
                    SESSION_COOKIES["latest"] = sc.split(";", 1)[0].split("=", 1)[1]
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


SESSION_COOKIES: dict[str, str] = {}


def register(username: str, email: str, password: str) -> None:
    status, body = call("POST", "/auth/register", {
        "username": username, "email": email,
        "password": password, "confirm_password": password,
    })
    if status == 201:
        print(f"registered {username}")
    elif status == 409:
        print(f"{username} already registered")
    else:
        sys.exit(fregister(username, status, body))


def fregister(username, status, body):
    return f"register {username} failed: {status} {body!r}"


def login(username: str, password: str) -> str:
    SESSION_COOKIES.pop("latest", None)
    status, body = call("POST", "/auth/login", {"account": username, "password": password})
    if status != 200:
        sys.exit(f"login {username} failed: {status} {body!r}")
    token = SESSION_COOKIES.get("latest")
    if not token:
        sys.exit(f"login {username} set no hgs_session cookie")
    return token


def set_display_name(token: str, display_name: str, email: str) -> None:
    # ProfileBody 必填 display_name+email, 其余可空; 重复 PATCH 同值幂等
    status, body = call("PATCH", "/users/me", {
        "display_name": display_name, "email": email,
    }, token)
    if status != 200:
        sys.exit(f"set display_name failed: {status} {body!r}")


def create_reaction(token: str, payload: dict, idem_key: str) -> dict:
    status, body = call("POST", "/reactions", payload, token,
                        {"Idempotency-Key": idem_key})
    if status == 201:
        return body
    if status == 200:  # 幂等重放
        return body
    sys.exit(f"create reaction {idem_key} failed: {status} {body!r}")


def search_chemical(token: str, smiles: str) -> dict | None:
    from urllib.parse import quote
    status, body = call("GET", f"/search?q={quote(smiles)}&mode=exact&page=1&page_size=5",
                        token=token)
    if status != 200:
        sys.exit(f"search {smiles} failed: {status} {body!r}")
    chems = body.get("chemicals") if isinstance(body, dict) else None
    if not chems:
        return None
    # SMILES canonical 命中可能带同构近邻, 取 smiles 完全一致的第一行
    for c in chems:
        if c.get("smiles", "").replace(" ", "") == smiles:
            return c
    return chems[0]


def ensure_note(token: str, content: str, visibility: str,
                chemical_ids: list[int], reaction_ids: list[int]) -> dict:
    status, body = call("GET", "/users/me/notes?page=1&page_size=50", token=token)
    if status == 200:
        for n in body.get("items", []):
            if n.get("content") == content:
                return n  # 已存在, 幂等跳过
    status, body = call("POST", "/notes", {
        "visibility": visibility, "content": content,
        "chemical_ids": chemical_ids, "reaction_ids": reaction_ids,
    }, token)
    if status != 201:
        sys.exit(f"create note failed: {status} {body!r}")
    return body


def follow_user(token: str, username: str) -> None:
    status, _ = call("POST", f"/users/{username}/follow", {}, token)
    if status not in (204, 409):
        sys.exit(f"follow {username} failed: {status}")


def follow_chemical(token: str, chemical_id: int) -> None:
    status, _ = call("POST", f"/chemicals/{chemical_id}/follow", {}, token)
    if status not in (204, 409):
        sys.exit(f"follow chemical {chemical_id} failed: {status}")


# ── 化学内容(真实、简单的经典反应) ────────────────────────────────────────────
SALICYLIC = "O=C(O)c1ccccc1O"          # 水杨酸
ACETIC_ANHYDRIDE = "CC(=O)OC(C)=O"     # 乙酸酐
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"      # 乙酰水杨酸(阿司匹林)
ACETIC_ACID = "CC(=O)O"                # 乙酸
METHANOL = "CO"                        # 甲醇
BENZOIC = "OC(=O)c1ccccc1"             # 苯甲酸
METHYL_BENZOATE = "COC(=O)c1ccccc1"    # 苯甲酸甲酯
ETHANOL = "CCO"                        # 乙醇
ETHYL_ACETATE = "CCOC(C)=O"            # 乙酸乙酯
METHYL_SALICYLATE = "COC(=O)c1ccccc1O" # 水杨酸甲酯(冬青油)

RX_DEMO_ASPIRIN = {
    "visibility": "public",
    "source_type": "self",
    "participants": [
        {"role": "REACTANT", "smiles": SALICYLIC, "amount_value": 2.0, "amount_unit": "g"},
        {"role": "REACTANT", "smiles": ACETIC_ANHYDRIDE, "amount_value": 3.0, "amount_unit": "mL"},
        {"role": "CATALYST", "smiles": ACETIC_ACID, "amount_value": 2, "amount_unit": "drops"},
        {"role": "PRODUCT", "smiles": ASPIRIN, "yield_percent": 78.5},
        {"role": "PRODUCT", "smiles": ACETIC_ACID},
    ],
    "procedure_details": "水杨酸与乙酸酐混合, 少量硫酸催化, 水浴加热约 20 分钟, 冷却析晶, 重结晶提纯。(本地演示数据)",
    "conditions_detail": "水浴 80–85 °C",
    "temperature_value": 82, "temperature_unit": "CELSIUS",
    "duration_value": 1, "duration_unit": "HOUR",
    "note": "阿司匹林经典合成 — hgs_demo 演示反应 #1",
}
RX_DEMO_PRIVATE = {
    "visibility": "private",
    "source_type": "self",
    "participants": [
        {"role": "REACTANT", "smiles": BENZOIC, "amount_value": 1.0, "amount_unit": "g"},
        {"role": "REACTANT", "smiles": METHANOL, "amount_value": 20, "amount_unit": "mL"},
        {"role": "PRODUCT", "smiles": METHYL_BENZOATE, "yield_percent": 71},
    ],
    "procedure_details": "苯甲酸在过量甲醇中回流, 演示用私有记录。(本地演示数据)",
    "note": "苯甲酸甲酯回流 — hgs_demo 私有演示反应",
}
RX_DEMO_FISCHER = {
    "visibility": "public",
    "source_type": "self",
    "participants": [
        {"role": "REACTANT", "smiles": ACETIC_ACID, "amount_value": 1, "amount_unit": "eq"},
        {"role": "REACTANT", "smiles": ETHANOL, "amount_value": 1.2, "amount_unit": "eq"},
        {"role": "PRODUCT", "smiles": ETHYL_ACETATE, "yield_percent": 65},
    ],
    "procedure_details": "乙酸与乙醇在浓硫酸催化下回流酯化, 蒸馏收集产物。(本地演示数据)",
    "note": "乙酸乙酯 Fischer 酯化 — hgs_demo 演示反应 #2",
}
RX_PEER_1 = {
    "visibility": "public",
    "source_type": "self",
    "participants": [
        {"role": "REACTANT", "smiles": SALICYLIC, "amount_value": 2.0, "amount_unit": "g"},
        {"role": "REACTANT", "smiles": METHANOL, "amount_value": 25, "amount_unit": "mL"},
        {"role": "PRODUCT", "smiles": METHYL_SALICYLATE, "yield_percent": 80},
    ],
    "procedure_details": "水杨酸与甲醇硫酸催化回流, 得水杨酸甲酯(冬青油)。(本地演示数据)",
    "note": "水杨酸甲酯合成 — hgs_peer 演示反应 #1",
}
RX_PEER_2 = {
    "visibility": "public",
    "source_type": "self",
    "participants": [
        {"role": "REACTANT", "smiles": ASPIRIN, "amount_value": 0.5, "amount_unit": "g"},
        {"role": "REACTANT", "smiles": "O", "amount_value": 30, "amount_unit": "mL"},
        {"role": "PRODUCT", "smiles": SALICYLIC, "yield_percent": 90},
        {"role": "PRODUCT", "smiles": ACETIC_ACID},
    ],
    "procedure_details": "阿司匹林在酸性水溶液中加热水解回水杨酸。(本地演示数据)",
    "note": "阿司匹林酸性水解 — hgs_peer 演示反应 #2",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    # 本地演示数据的硬边界：目标只允许回环地址 —— 由代码保证，不靠说明文字
    from urllib.parse import urlsplit
    host = (urlsplit(args.base).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit(f"seed 只允许本机地址（得到 {host}）；本地演示数据不得写入远端")
    global API
    API = args.base.rstrip("/") + "/api"

    demo_pw = ENV["SEED_HGS_DEMO_PASSWORD"]
    peer_pw = ENV["SEED_HGS_PEER_PASSWORD"]
    admin_pw = ENV["SEED_HGS_ADMIN_PASSWORD"]

    register("hgs_demo", "hgs_demo@example.test", demo_pw)
    register("hgs_peer", "hgs_peer@example.test", peer_pw)
    register("hgs_admin", "hgs_admin@example.test", admin_pw)
    demo = login("hgs_demo", demo_pw)
    peer = login("hgs_peer", peer_pw)
    admin = login("hgs_admin", admin_pw)
    set_display_name(demo, "SUN Demo", "hgs_demo@example.test")
    set_display_name(peer, "Lin Demo", "hgs_peer@example.test")
    set_display_name(admin, "Admin Demo", "hgs_admin@example.test")
    # admin 角色只能经 DB 授予（注册 API 不接受 role）——仅本地栈 compose，
    # 不出现在任何生产迁移/部署脚本；幂等（重复 UPDATE 同值）。
    promote_admin = subprocess.run(
        ["docker", "compose", "--env-file", ".env.local", "exec", "-T", "db", "su", "postgres", "-s", "/bin/bash", "-c",
         f"/usr/lib/postgresql/16/bin/psql -d {ENV.get('HGS_DB_NAME', 'hgs_local')} -c \"UPDATE community.users SET role='admin' WHERE username='hgs_admin'\""],
        cwd=str(STACK), capture_output=True, text=True)
    if promote_admin.returncode != 0:
        sys.exit(f"promote hgs_admin failed: {promote_admin.stderr[:200]}")
    print("hgs_admin role=admin (local stack only)")

    # demo 先关注 peer → peer 的公开反应会触发 demo 的 new_reaction 动态
    follow_user(demo, "hgs_peer")

    rx_demo_aspirin = create_reaction(demo, RX_DEMO_ASPIRIN, "seed-hgs-demo-aspirin-1")
    rx_demo_private = create_reaction(demo, RX_DEMO_PRIVATE, "seed-hgs-demo-private-1")
    rx_demo_fischer = create_reaction(demo, RX_DEMO_FISCHER, "seed-hgs-demo-fischer-1")

    aspirin = search_chemical(demo, ASPIRIN)
    salicylic = search_chemical(demo, SALICYLIC)
    methyl_salicylate = search_chemical(demo, METHYL_SALICYLATE)
    missing = [n for n, c in [("aspirin", aspirin), ("salicylic", salicylic),
                              ("methyl_salicylate", methyl_salicylate)] if c is None]
    if missing:
        sys.exit(f"expected chemicals not found after reaction creation: {missing}")

    ensure_note(demo,
                "阿司匹林合成演示笔记: 水杨酸 + 乙酸酐, 82 °C 水浴 1 h, 收率约 78%。(本地演示数据)",
                "public", [aspirin["id"], salicylic["id"]], [rx_demo_aspirin["id"]])
    ensure_note(demo,
                "私有备注: 冬青油香气成分的替代路线评估。(本地演示数据)",
                "private", [methyl_salicylate["id"]], [])

    for c in (aspirin, salicylic, methyl_salicylate):
        follow_chemical(demo, c["id"])

    rx_peer_1 = create_reaction(peer, RX_PEER_1, "seed-hgs-peer-methylsal-1")
    create_reaction(peer, RX_PEER_2, "seed-hgs-peer-hydrolysis-1")
    follow_user(peer, "hgs_demo")

    status, me = call("GET", "/users/me", token=demo)
    if status != 200:
        sys.exit(f"/users/me failed: {status}")
    status, notes = call("GET", "/users/me/notes?page=1&page_size=50", token=demo)
    status_notif, notif = call("GET", "/users/me/notifications", token=demo)
    print(json.dumps({
        "hgs_demo": {
            "display_name": me.get("display_name"),
            "public_reactions": [rx_demo_aspirin["id"], rx_demo_fischer["id"]],
            "private_reaction": rx_demo_private["id"],
            "notes": [n["id"] for n in notes.get("items", [])],
            "followed_chemicals": [aspirin["id"], salicylic["id"], methyl_salicylate["id"]],
            "aspirin_hcid": aspirin["id"],
            "notifications": notif.get("total") if status_notif == 200 else f"http {status_notif}",
        },
        "hgs_peer": {
            "public_reactions": [rx_peer_1["id"]],
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
