import { notFound } from "next/navigation";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Button } from "@/components/ui/Button";
import { Tag } from "@/components/ui/Tag";
import { Field, Input } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Avatar } from "@/components/ui/Avatar";
import { DevUiInteractive } from "@/components/ui/DevUiDemos";
import { IconStar, IconUsers, IconLock, IconTrash, IconOk } from "@/components/ui/icons";
import "./dev-ui.css";

/**
 * /dev-ui — v1.7 组件库开发预览页（仅非 production）。
 * 结构与 docs/design/hgs-ui-reference.html §5（#badge）、§6（#comp）一一对应，
 * 用于像素级对照（pair.mjs）与键盘走查（ix-check.mjs）。
 * 按钮矩阵的 hover/pressed/focus 用 class 强制展示，同参考 HTML 做法。
 */
export default function DevUiPage() {
  if (process.env.NODE_ENV === "production") notFound();

  const buttonVariants = [
    { key: "primary", label: "保存反应", loading: "保存中" },
    { key: "secondary", label: "分享", loading: "分享" },
    { key: "tonal", label: "关注", loading: "关注" },
    { key: "danger", label: "删除", loading: "删除中" },
  ] as const;

  return (
    <div className="du-wrap">
      <section id="dev-badge">
        <h2>HCID / HRID 徽标 <small>EntityBadge · 4 尺寸 × 2 实体 × 全部状态</small></h2>
        <div className="du-box">
          <div className="du-eb-grid">
            <span></span><span className="h">HCID · 化合物</span><span className="h">HRID · 反应</span>
            <span className="lbl">lg 32 · 详情页头部</span>
            <span><EntityBadge kind="chemical" id={2244} size="lg" href="#dev-badge" copyable /></span>
            <span><EntityBadge kind="reaction" id={18628} size="lg" href="#dev-badge" copyable /></span>
            <span className="lbl">md 28 · 卡片标题</span>
            <span><EntityBadge kind="chemical" id={178758197} size="md" href="#dev-badge" /></span>
            <span><EntityBadge kind="reaction" id={2428383} size="md" href="#dev-badge" /></span>
            <span className="lbl">sm 24 · 默认</span>
            <span><EntityBadge kind="chemical" id={2244} href="#dev-badge" /></span>
            <span><EntityBadge kind="reaction" id={18628} href="#dev-badge" /></span>
            <span className="lbl">xs 20 · 列表、行内</span>
            <span><EntityBadge kind="chemical" id={2244} size="xs" href="#dev-badge" /></span>
            <span><EntityBadge kind="reaction" id={18628} size="xs" href="#dev-badge" /></span>
            <span className="lbl">compact · 表格列</span>
            <span><EntityBadge kind="chemical" id={2244} href="#dev-badge" compact /></span>
            <span><EntityBadge kind="reaction" id={18628} href="#dev-badge" compact /></span>
            <span className="lbl">可复制</span>
            <span><EntityBadge kind="chemical" id={2244} size="md" href="#dev-badge" copyable /></span>
            <span><EntityBadge kind="reaction" id={18628} size="md" href="#dev-badge" copyable /></span>
            <span className="lbl">私有</span>
            <span className="note">化合物没有私有状态</span>
            <span><EntityBadge kind="reaction" id={2428383} state="private" href="#dev-badge" /></span>
            <span className="lbl">已合并（重定向）</span>
            <span><EntityBadge kind="chemical" id={178844901} state="merged" redirectTo={2244} /></span>
            {/* deleted 的「已删除」尾注由 EntityBadge 组件内渲染（common.deletedEntity），此处不再重复 */}
            <span><EntityBadge kind="reaction" id={2428390} state="deleted" /></span>
          </div>
        </div>
        <div className="du-g2">
          <div className="du-box">
            <p className="du-inline-demo">
              用 <EntityBadge kind="chemical" id={2244} size="xs" href="#dev-badge" /> 乙酰水杨酸做原料，按{" "}
              <EntityBadge kind="reaction" id={18628} size="xs" href="#dev-badge" /> 的条件完成酯化，产率比文献低 6%。
            </p>
            <p className="du-note">在笔记、动态等正文里使用 xs 尺寸，徽标和文字基线对齐。</p>
          </div>
        </div>
      </section>

      <section id="dev-comp">
        <h2>组件 <small>.hg- 前缀 · 与参考 §6 一一对应</small></h2>

        <div className="du-box">
          <div className="du-matrix">
            <span></span>
            <span className="h">default</span><span className="h">hover</span><span className="h">pressed</span>
            <span className="h">focus-visible</span><span className="h">loading</span><span className="h">disabled</span>
            {buttonVariants.map((v) => (
              <span key={v.key} style={{ display: "contents" }}>
                <span className="lbl">{v.key}</span>
                <span><Button variant={v.key}>{v.label}</Button></span>
                <span><Button variant={v.key} className="is-hover">{v.label}</Button></span>
                <span><Button variant={v.key} className="is-active">{v.label}</Button></span>
                <span><Button variant={v.key} className="is-focus">{v.label}</Button></span>
                <span><Button variant={v.key} loading>{v.loading}</Button></span>
                <span><Button variant={v.key} disabled>{v.label}</Button></span>
              </span>
            ))}
          </div>
          <div className="du-row" style={{ marginTop: 24 }}>
            <Button variant="primary" size="sm">sm 32</Button>
            <Button variant="primary">md 40</Button>
            <Button variant="primary" size="lg">lg 48</Button>
            <Button variant="ghost" iconOnly aria-label="收藏"><IconStar /></Button>
            <Button variant="danger-quiet" size="sm"><IconTrash />删除笔记</Button>
          </div>
        </div>

        <div className="du-g2">
          <div className="du-box du-stack">
            <Field label="产物 SMILES" required error="SMILES 无法解析：第 19 个字符后缺少右括号">
              <Input mono invalid defaultValue="CC(=O)Oc1ccccc1C(=O)" />
            </Field>
            <Field label="收率" help="不确定就留空，不要估计">
              <Input className="is-focus" defaultValue="82 %" />
            </Field>
          </div>
          <div className="du-box du-stack">
            <div className="du-row" style={{ gap: 8 }}>
              <Tag>C9H8O4</Tag>
              <Tag>CAS 50-78-2</Tag>
              <Tag tone="blue">公开</Tag>
              <Tag icon={<IconLock />}>私有</Tag>
              <Tag tone="ok" dot>已补全</Tag>
              <Tag tone="warn" dot>来源冲突</Tag>
              <Tag tone="src">PubChem</Tag>
            </div>
            <DevUiInteractive />
            <Notice tone="warn" title="熔点在两个来源之间不一致">
              两个值并列显示，没有合并。
            </Notice>
          </div>
        </div>

        <div className="du-g3">
          <div className="hg-stage">
            <div className="hg-toast">
              <IconOk className="ok" />
              已关注 林一舟<button type="button">撤销</button>
            </div>
          </div>
          <div className="hg-stage">
            <div className="hg-modal" role="alertdialog" aria-labelledby="dev-modal-t" aria-describedby="dev-modal-b">
              <h3 id="dev-modal-t">删除这条笔记？</h3>
              <p id="dev-modal-b">「阿司匹林重结晶记录」将被永久删除。此操作无法撤销。</p>
              <footer>
                <Button variant="secondary">取消</Button>
                <Button variant="danger">删除笔记</Button>
              </footer>
            </div>
          </div>
          <div className="du-box" style={{ padding: 0 }}>
            <EmptyState icon={<IconUsers />} title="还没有关注任何人" action={{ label: "去发现用户" }}>
              关注其他用户后，他们发布的公开反应会出现在这里。
            </EmptyState>
          </div>
        </div>

        <h3>骨架屏 · 头像</h3>
        <div className="du-box du-stack">
          <div className="du-row">
            <Skeleton variant="row" style={{ width: 220 }} />
            <Skeleton variant="row" style={{ width: 160 }} />
          </div>
          <Skeleton variant="card" />
          <div className="du-row">
            <Avatar id={1} name="SUN Demo" size={24} />
            <Avatar id={2} name="Lin Demo" size={32} />
            <Avatar id={3} name="Mia Chen" size={40} />
            <Avatar id={4} name="Avery" size={80} />
            <Avatar id={5} name="Bo" size={40} />
            <Avatar id={6} name="Cy" size={40} />
            <Avatar id={7} name="Di" size={40} />
          </div>
        </div>
      </section>
    </div>
  );
}
