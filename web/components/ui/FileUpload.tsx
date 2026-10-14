"use client";

/**
 * FileUpload — 文件上传（DESIGN_SYSTEM 3.3）。
 * Button secondary 触发隐藏的 file input，旁边显示已选文件名，不露出浏览器原生控件。
 */
import { useRef, useState, type ChangeEvent } from "react";
import { Button } from "./Button";

export function FileUpload({
  id,
  name,
  accept,
  required,
  disabled,
  buttonText = "选择文件",
  placeholder = "未选择文件",
  onChange,
  className,
}: {
  id?: string;
  name?: string;
  accept?: string;
  required?: boolean;
  disabled?: boolean;
  buttonText?: string;
  placeholder?: string;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string>("");

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
