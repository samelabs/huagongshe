"use client";

/**
 * FileUpload — 文件上传（DESIGN_SYSTEM 3.3）。
 * Button secondary 触发隐藏的 file input，旁边显示已选文件名，不露出浏览器原生控件。
 * 按钮与占位文案由调用方按字典传入（无内置字面量）；ref 指向内部 input，
 * 供调用方读取所选文件或从别处（如空态动作）触发选择。
 */
import { useImperativeHandle, useRef, useState, type ChangeEvent, type Ref } from "react";
import { Button } from "./Button";

export function FileUpload({
  id,
  name,
  accept,
  required,
  disabled,
  buttonText,
  placeholder,
  onChange,
  className,
  ref,
}: {
  id?: string;
  name?: string;
  accept?: string;
  required?: boolean;
  disabled?: boolean;
  buttonText: string;
  placeholder: string;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  className?: string;
  ref?: Ref<HTMLInputElement | null>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string>("");
  useImperativeHandle<HTMLInputElement | null, HTMLInputElement | null>(ref, () => inputRef.current, []);

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    setFileName(file ? file.name : "");
    onChange?.(e);
  }

  return (
    <div className={`hg-file-upload${className ? ` ${className}` : ""}`}>
      <input
        ref={inputRef}
        id={id}
        name={name}
        type="file"
        accept={accept}
        required={required}
        disabled={disabled}
        tabIndex={-1}
        style={{ display: "none" }}
        onChange={handleChange}
      />
      <Button
        type="button"
        variant="secondary"
        size="md"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {buttonText}
      </Button>
      <span className={`hg-file-upload-name${!fileName ? " empty" : ""}`}>
        {fileName || placeholder}
      </span>
    </div>
  );
}
