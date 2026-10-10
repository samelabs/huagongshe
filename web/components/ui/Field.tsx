"use client";

/**
 * Field / Input / Textarea / Select — v1.7 表单控件（参考 §6）。
 *
 * Field 负责 label、必填星号、help 与 error 文字，并把 id / aria-invalid /
 * aria-describedby 注入子控件（cloneElement，调用方传 ref 不受影响）。
 * 控件本身也可脱离 Field 单独使用。手机上输入字号 16（ui.css，防 iOS 缩放）。
 */
import { useId, isValidElement, cloneElement, type ReactNode } from "react";

function classesOf(base: string, extra: (string | false | undefined)[], className?: string): string {
  return [base, ...extra.filter(Boolean), className ?? ""].filter(Boolean).join(" ");
}

export function Input({ invalid, mono, className, ...rest }: React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; mono?: boolean; ref?: React.Ref<HTMLInputElement> }) {
  return <input className={classesOf("hg-input", [mono && "mono", invalid && "is-error"], className)} {...rest} />;
}

export function Textarea({ invalid, className, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }) {
  return <textarea className={classesOf("hg-textarea", [invalid && "is-error"], className)} {...rest} />;
}

export function Select({ invalid, className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }) {
  return (
    <select className={classesOf("hg-input", ["hg-select", invalid && "is-error"], className)} {...rest}>
      {children}
    </select>
  );
}

export type FieldProps = {
  /** 字段名（label 文字） */
  label: ReactNode;
  /** 必填：label 后加红色星号（装饰性，语义用控件自身 required） */
  required?: boolean;
  /** 说明文字；error 存在时被替换 */
  help?: ReactNode;
  /** 错误文字：控件变红边 + aria-invalid + aria-describedby 关联 */
  error?: ReactNode;
  /** 子控件（Input/Textarea/Select 或任意透传 id 的元素）；缺省时只渲染 label */
  children?: ReactNode;
  /** 显式控件 id（否则自动生成） */
  htmlFor?: string;
  className?: string;
};

export function Field({ label, required, help, error, children, htmlFor, className }: FieldProps) {
  const autoId = useId();
  const id = htmlFor ?? autoId;
  const helpId = error || help ? `${id}-help` : undefined;

  const control = isValidElement(children)
    ? cloneElement(children as React.ReactElement<Record<string, unknown>>, {
        id,
        ...(error ? { "aria-invalid": true } : {}),
        ...(helpId ? { "aria-describedby": helpId } : {}),
      })
    : children;

  return (
    <div className={["hg-field", className ?? ""].filter(Boolean).join(" ")}>
      <label className="hg-label" htmlFor={id}>
        {label}
        {required && <em aria-hidden="true">*</em>}
      </label>
      {control}
      {(error || help) && (
        <span className={["hg-help", error ? "err" : ""].filter(Boolean).join(" ")} id={helpId}>
          {error ?? help}
        </span>
      )}
    </div>
  );
}
