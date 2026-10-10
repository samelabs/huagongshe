"use client";

/**
 * DevUiDemos — /dev-ui 的交互演示部分（Toast / ConfirmDialog / Tabs /
 * Segmented / 复制）。静态矩阵由页面直接渲染；这里是需要状态的组件。
 * 仅开发预览用，不承载产品文案职责（demo 文案就地书写，镜像参考 HTML）。
 */
import { useState } from "react";
import { useConfirm } from "./ConfirmDialog";
import { useToast } from "./Toast";
import { Button } from "./Button";
import { Segmented } from "./Segmented";
import { Tabs } from "./Tabs";
import { CodeField } from "./CodeField";

export function DevUiInteractive() {
  const toast = useToast();
  const confirm = useConfirm();
  const [seg, setSeg] = useState<"name" | "sub" | "sim">("name");
  const [tab, setTab] = useState("notes");

  async function tryDeleteNote() {
    const ok = await confirm({
      title: "删除这条笔记？",
      body: "「阿司匹林重结晶记录」将被永久删除。此操作无法撤销。",
      confirmLabel: "删除笔记",
      tone: "danger",
    });
    if (ok) toast.success("笔记已删除");
  }

  return (
    <>
      <div className="du-row">
        <Button variant="tonal" size="sm" onClick={() => toast.success("已关注 林一舟", { action: { label: "撤销", onClick: () => toast.success("已取消关注") } })}>
          Toast 成功（带撤销）
        </Button>
        <Button variant="secondary" size="sm" onClick={() => toast.error("保存失败：网络错误，请重试")}>
          Toast 失败（手动关闭）
        </Button>
        <Button variant="danger-quiet" size="sm" onClick={() => void tryDeleteNote()}>
          确认弹窗（试一下）
        </Button>
      </div>

      <div className="du-row">
        <Segmented
          ariaLabel="检索方式"
          value={seg}
          onChange={setSeg}
          options={[
            { value: "name", label: "名称 / CAS" },
            { value: "sub", label: "子结构" },
            { value: "sim", label: "相似" },
          ]}
        />
      </div>

      <Tabs
        ariaLabel="面板"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "notes", label: "笔记", count: 2 },
          { id: "reactions", label: "反应", count: 3 },
          { id: "saved", label: "收藏", count: 3 },
        ]}
      />

      <CodeField value="CC(=O)Oc1ccccc1C(=O)O" />
    </>
  );
}
