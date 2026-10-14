"use client";

import { EntityBadge } from "@/components/ui/EntityBadge";
import { Button } from "@/components/ui/Button";
import { TextLink } from "@/components/ui/TextLink";
import { Tag } from "@/components/ui/Tag";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { FileUpload } from "@/components/ui/FileUpload";
import { CopyButton } from "@/components/ui/CopyButton";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { Notice } from "@/components/ui/Notice";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Avatar } from "@/components/ui/Avatar";
import { DevUiInteractive } from "@/components/ui/DevUiDemos";
import { IconStar, IconUsers, IconLock, IconTrash, IconOk, IconInfo, IconWarn, IconCheck } from "@/components/ui/icons";
import "./dev-ui.css";

/**
 * /dev-ui — v2.0 组件库开发预览页（仅非 production）。
 * 组件活样张，规则见 docs/DESIGN_SYSTEM.md 第三层，
 * 用于像素级对照与键盘走查。
 * 按钮矩阵的 hover/pressed/focus 用 class 强制展示。
 */
export default function DevUiPage() {
  const buttonVariants = [
    { key: "primary", label: "保存反应", loading: "保存中" },
    { key: "secondary", label: "分享", loading: "分享" },
    { key: "tonal", label: "关注", loading: "关注" },
    { key: "ghost", label: "翻页", loading: "翻页" },
    { key: "danger", label: "删除", loading: "删除中" },
    { key: "danger-quiet", label: "撤销 Key", loading: "撤销中" },
  ] as const;

  return (
    <div className="du-wrap">
      {/* 3.8 Breadcrumb */}
      <section id="dev-breadcrumb">
        <h2>面包屑 <small>Breadcrumb (DESIGN_SYSTEM 3.8) · 首页 / 栏目 / 当前</small></h2>
        <div className="du-box">
          <Breadcrumb
            items={[
              { label: "首页", href: "#dev-breadcrumb" },
              { label: "化合物" },
              { label: "阿司匹林 Aspirin" },
            ]}
          />
        </div>
      </section>

      {/* 3.4 EntityBadge */}
      <section id="dev-badge">
        <h2>HCID / HRID 徽标 <small>EntityBadge (DESIGN_SYSTEM 3.4) · 4 尺寸 × 2 实体 × 全部状态</small></h2>
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

      {/* 3.1 Button & 3.2 TextLink */}
      <section id="dev-comp">
        <h2>按钮与链接 <small>Button (3.1) · TextLink (3.2)</small></h2>

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
          <div className="du-row" style={{ marginTop: 24, alignItems: "center" }}>
            <Button variant="primary" size="sm">sm 32</Button>
            <Button variant="primary">md 40</Button>
            <Button variant="primary" size="lg">lg 48</Button>
            <Button variant="ghost" iconOnly aria-label="收藏"><IconStar /></Button>
            <Button variant="danger-quiet" size="sm"><IconTrash />删除笔记</Button>
            <TextLink href="#dev-comp">返回首页</TextLink>
            <TextLink disabled>禁用操作</TextLink>
          </div>
        </div>

        {/* 3.3 Field / Input / Select / Textarea / FileUpload */}
        <h3>表单输入控件 <small>Field · Input · Select · Textarea · FileUpload (3.3)</small></h3>
        <div className="du-g2">
          <div className="du-box du-stack">
            <Field label="产物 SMILES" required error="SMILES 无法解析：第 19 个字符后缺少右括号">
              <Input mono invalid defaultValue="CC(=O)Oc1ccccc1C(=O)" />
            </Field>
            <Field label="收率" help="不确定就留空，不要估计">
              <Input className="is-focus" defaultValue="82 %" />
            </Field>
            <Field label="参与角色">
              <Select defaultValue="reactant">
                <option value="reactant">主要反应物 (Reactant)</option>
                <option value="catalyst">催化剂 / 助剂 (Catalyst)</option>
                <option value="product">产物 (Product)</option>
              </Select>
            </Field>
            <Field label="实验步骤备注">
              <Textarea placeholder="输入实验操作步骤及观察现象..." rows={2} />
            </Field>
          </div>
          <div className="du-box du-stack">
            <Field label="头像上传 (FileUpload)">
              <FileUpload buttonText="选择图片" placeholder="未选择任何文件" />
            </Field>
            {/* 3.6 Tag */}
            <div className="du-row" style={{ gap: 8 }}>
              <Tag>C9H8O4</Tag>
              <Tag>CAS 50-78-2</Tag>
              <Tag tone="blue">公开</Tag>
              <Tag icon={<IconLock />}>私有</Tag>
              <Tag tone="ok" dot>已补全</Tag>
              <Tag tone="warn" dot>来源冲突</Tag>
              <Tag tone="err" dot>验证失败</Tag>
            </div>
            {/* 3.5 CopyButton standalone */}
            <div className="du-row" style={{ alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: "var(--fs-14)", color: "var(--text-2)" }}>InChIKey: BSYNRYMUTXBXSQ-UHFFFAOYSA-N</span>
              <CopyButton value="BSYNRYMUTXBXSQ-UHFFFAOYSA-N" ariaLabel="复制 InChIKey" />
            </div>
            {/* 3.7 / 3.9 / 3.10 交互演示 */}
            <DevUiInteractive />
          </div>
        </div>

        {/* 3.9 Notice */}
        <h3>页面通知 <small>Notice (3.9) · info · ok · warn · err</small></h3>
        <div className="du-stack">
          <Notice tone="info" title="新功能提示">
            MCP 服务端已支持 Chemistry Tools 协议，前往接入指南查看配置方法。
          </Notice>
          <Notice tone="ok" title="反应已成功提交">
            HRID 18628 已完成事实核验并录入公开知识库。
          </Notice>
          <Notice tone="warn" title="熔点在两个来源之间不一致">
            两个值并列显示，没有合并。
          </Notice>
          <Notice tone="err" title="读取化合物数据失败" action={{ label: "重试", onClick: () => {} }}>
            网络连接超时，请检查您的网络连接或稍后重试。
          </Notice>
        </div>

        {/* 3.14 DataRow */}
        <h3>数据分区行 <small>DataRow (3.14) · dl 两列布局</small></h3>
        <div className="du-box">
          <dl className="chem-kv" style={{ display: "grid", gap: 0, margin: 0 }}>
            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <dt style={{ color: "var(--text-muted)", fontSize: "var(--fs-13)" }}>CAS 号</dt>
              <dd style={{ margin: 0, display: "inline-flex", alignItems: "center", gap: 8 }}>
                <code>50-78-2</code>
                <CopyButton value="50-78-2" ariaLabel="复制 CAS" />
              </dd>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <dt style={{ color: "var(--text-muted)", fontSize: "var(--fs-13)" }}>分子式</dt>
              <dd style={{ margin: 0 }}>C9H8O4</dd>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, padding: "8px 0" }}>
              <dt style={{ color: "var(--text-muted)", fontSize: "var(--fs-13)" }}>分子量</dt>
              <dd style={{ margin: 0 }}>180.16 g/mol</dd>
            </div>
          </dl>
        </div>

        {/* 3.9 Toast & 3.10 ConfirmDialog & 3.11 EmptyState */}
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

        {/* 3.11 Skeleton & 3.12 Avatar */}
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
