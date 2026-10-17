/**
 * 笔记呈现规则（DESIGN_SYSTEM 6.5 / /)：
 * 笔记保持只有正文、没有标题字段，不改数据结构；只改呈现规则。整站共用一个函数：
 * - 笔记有两行及以上、且首行不超过 60 字：首行作为标题，其余作为正文。
 * - 其他情况（单行笔记，或首行太长）：整段作为正文，标题用中性写法——
 * 关联了实体时写“关于 {实体名} 的笔记”，没有关联时写“{作者显示名} 的笔记”。不要再把整段内容当 H1。
 */

export type NotePresentation = {
  title: string;
  body: string;
  isCustomTitle: boolean;
};

export function resolveNotePresentation(
  content: string,
  options?: {
    authorName?: string | null;
    linkedEntityName?: string | null;
    fallbackTitle?: string;
    t?: {
      notes?: {
        aboutEntityNote?: (name: string) => string;
        authorNote?: (author: string) => string;
        detailTitle?: string;
      };
    };
  }
): NotePresentation {
  const lines = (content || "").split("\n");
  let firstIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().length > 0) {
      firstIdx = i;
      break;
    }
  }

  const aboutEntity = options?.t?.notes?.aboutEntityNote || ((name: string) => `关于 ${name} 的笔记`);
  const authorNote = options?.t?.notes?.authorNote || ((author: string) => `${author} 的笔记`);
  const neutralTitle = options?.linkedEntityName
    ? aboutEntity(options.linkedEntityName)
    : options?.authorName
    ? authorNote(options.authorName)
    : options?.fallbackTitle || options?.t?.notes?.detailTitle || "笔记";

  if (firstIdx === -1) {
    return { title: neutralTitle, body: "", isCustomTitle: false };
  }

  const firstLine = lines[firstIdx].trim();
  const remainingLines = lines.slice(firstIdx + 1);
  const remainingText = remainingLines.join("\n").trim();

  // 有两行及以上、且首行不超过 60 字
  if (remainingText.length > 0 && firstLine.length <= 60) {
    return {
      title: firstLine,
      body: remainingLines.join("\n").trim(),
      isCustomTitle: true,
    };
  }

  // 其他情况（单行笔记，或首行太长）：整段作为正文，标题用中性写法
  return {
    title: neutralTitle,
    body: (content || "").trim(),
    isCustomTitle: false,
  };
}

/** 兼容旧代码调用：返回首行或中性标题 */
export function noteHeadline(content: string, options?: Parameters<typeof resolveNotePresentation>[1]): string {
  return resolveNotePresentation(content, options).title;
}

/**
 * 笔记列表行（工作台列表、概览面板、公开主页）共用的呈现派生。
 * 列表接口拿不到关联实体的真实名称，不造模板标题：
 * - 多行且首行不超过 60 字：首行作标题，其余作摘要（各列表两行截断）；
 * - 其他（单行，或首行超长）：没有标题，正文整段即行主文本（两行截断），
 *   不出现"关于…的笔记"这类占位文字；
 * - 关联实体只由行内实体徽标表达。
 * 详情页标题规则（resolveNotePresentation）不受本函数影响。
 */
export type NoteListPresentation = { title: string | null; body: string };

export function noteListPresentation(note: { content: string }): NoteListPresentation {
  const lines = (note.content || "").split("\n");
  let firstIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().length > 0) {
      firstIdx = i;
      break;
    }
  }
  if (firstIdx === -1) {
    return { title: null, body: "" };
  }
  const firstLine = lines[firstIdx].trim();
  const remaining = lines.slice(firstIdx + 1).join("\n").trim();
  if (remaining.length > 0 && firstLine.length <= 60) {
    return { title: firstLine, body: remaining };
  }
  return { title: null, body: (note.content || "").trim() };
}
