# CB 判定总览重构 — 判据网络分层方案(2026-09-02)

## 现状问题(总览)

当前判定散在三处、各管一段,边界靠"字节大小+模板形态"猜,没有统一的身份锚:

| 路径 | 现行判定 | 洞 |
|---|---|---|
| CAS 页(zh) | `looks_like_not_found`(模板形态:无Basicsl壳/无英文名称行) | >10KB 验证码页无 Basicsl 壳 → 误判 not_found |
| CPP 页 | `cpp_page_state`: <10KB error / ≥10KB ok(解析空=not_found) | 同上:大验证码页会被当真页→解析空→not_found |
| CAS 页提号 | `extract_cb_number`(GN/MSDS/Price 链接) | 只在"过掉 not 判定后"才执行,没参与判定 |

**根因混淆**:把"网络层拿没拿到真页面"和"数据层有没有收录"压在同一个字节阈值上。
收录的语义锚从来只有一个——**cb_number**(收录=CB 给这个 CAS 建了 CPP 页,页上必有自身链接;未收录模板页实测 cb_number=None)。

## 判据分层(方案核心)

三问严格分开,每问一个独立信号,不许互相顶替:

**Q1 网络通吗?**(传输层)
- 信号:HTTP 状态 + 字节量。非200/超时/<10KB → `error`(留记录重试)。
- 这层只回答"拿到的是不是一个完整页面",不猜内容。

**Q2 页面是真页面吗?**(页面层,新加)
- 信号:页面身份标记。CB 真页必带站内结构(真收录CAS页有 cb 链接;真CPP页有 ChemicalProperties 表/基本框架)。
- 验证码/质询页不论多大,**没有站内数据结构** → `error`。
- 判据:能提取到至少一种身份标记(cb_number / ChemicalProperties 表 / Basicsl 容器)。三者全无 = 不是真页 → error。

**Q3 收录了吗?**(数据层)
- 信号:**cb_number 存在性**(身份判据,不是文本特征)。
- 真页面 + 无 cb_number → `not_found`(CB 没收录,网络通了、页是真的、没数据)。
- 真页面 + 有 cb_number → `ok` 路径(照旧提号→CPP 拼装)。
- 例外保留:管制明示"本站不显示该产品信息"(有 Basicsl 壳)→ not_found(这是 CB 主动声明的收录拒绝,不是模板)。

## 判定流(伪码)

```
fetch CAS 页
├─ 非200/超时 → error                     (Q1)
├─ <10KB → error                          (Q1: 拦截页全是小页, 实测13B~1KB)
├─ cb = extract_cb_number(html)
├─ cb 命中 → ok 路径(提号→CPP→mol)        (Q3 收录)
├─ cb 为空:
│   ├─ 有 Basicsl 壳 + "本站不显示" → not_found   (Q3: 管制拒绝, 保留)
│   ├─ 有 Basicsl 壳 + 无英文名称行 → not_found   (Q3: 未收录模板, 实测36KB cb=None)
│   └─ 无 Basicsl 壳(>10KB) → error        (Q2: 大页但无任何身份标记=验证码/改版页)
CPP 页(路径A/语言页)同构:
├─ 非200/超时 → error                     (Q1)
├─ <10KB → error                          (Q1)
├─ 无 ChemicalProperties 表且无 dt/dl 结构 → error  (Q2: 大拦截页)
├─ 有结构 → ok / 解析空 → not_found        (Q3)
```

`ok(no_cb)` 分支(详情页正常但无号,定案"条目ok供应商空")**维持不动**——它有 Basicsl 壳(过了 Q2),无号是 CB 的真实状态。

## 为什么这版成立

- not_found 的落判从"字节+模板猜测"收紧为"**真页面身份验证通过 + cb_number 缺席**"——验证码页无论多大,没有 Basicsl 壳/站内结构,进不了 not_found。
- error 桶扩大(大拦截页改判 error):error 会触发闸门/重试,拦截事件**可观测**,不再静默。
- 与 cb_number 模型(收录锚点,与 cid 对称)完全同构,不引入新概念。
- 0902 血案教训对齐:"判据=页面有无对用户有效信息"+"禁文本特征"——Basicsl 壳/cb 链接/ChemicalProperties 表都是**站内结构标记**,非关键词匹配。

## 实施步骤(每步 diff 审批,不动生产)

1. **`caslib/parse.py`**:新增 `page_identity(html) -> "real"|"alien"`(Basicsl 壳 / ChemicalProperties 表 / cb 链接,三选一)。纯函数,单测。
2. **`caslib/fetch.py`**:`fetch_cas` 路径B 收紧——现 `looks_like_not_found` 的第3形态(无Basicsl壳)从 not_found 改判 error。路径A 及 `fetch_cpp_locale` 的 `cpp_page_state` 加 identity 检查:大页+无结构=error。
3. **`worker/main.py`**:零改动(三态直译不变)。
4. **fixture 补样本**:验证码大页(手工构造/抓真样本)、未收录模板(已有 CAS_99999-99-9)、真页(已有)。三态单测覆盖新分界。
5. **观察窗口**:上线后 24h 盯 error 率与闸门——若 Googlebot 路径稳定,新 error 分支应近似零;一旦出现即捕获了以前静默错杀的拦截页。

## 风险

- 若 CB 改版把 Basicsl壳/cb 链接改名,`page_identity` 误判 alien → 全线 error → 闸门熔断(可观测、可回退,优于静默 not_found 错杀)。
- 队列尚有 ~1.2 万历史回补在跑,方案不插队——等跑完再上,判定口径中途变更会污染比照审计。
