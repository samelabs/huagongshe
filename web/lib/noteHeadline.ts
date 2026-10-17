/**
 * 笔记呈现规则（DESIGN_SYSTEM 6.5 / I-080 / I-081）：
 * 笔记保持只有正文、没有标题字段，不改数据结构；只改呈现规则。整站共用一个函数：
 * - 笔记有两行及以上、且首行不超过 60 字：首行作为标题，其余作为正文。
 * - 其他情况（单行笔记，或首行太长）：整段作为正文，标题用中性写法——
 *   关联了实体时写“关于 {实体名} 的笔记”，没有关联时写“{作者显示名} 的笔记”。不要再把整段内容当 H1。
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
 * 笔记列表行（工作台列表、首页面板、公开主页）共用的呈现派生：
 * 标题按上面的规则；摘要恒为正文（自定义标题时是余下正文，中性标题时
 * 是整段），由各列表用两行截断渲染。有关联实体时中性标题指名首个关联
 * 实体（徽标同款的 HCID/HRID 标签），无关联时落到作者名。
 */
/** 列表呈现所需的最小字典面（Dictionary 结构满足） */
type NoteListDictionary = {
  common: { hcidLabel: (id: number) => string; hridLabel: (id: number) => string };
  notes?: { aboutEntityNote?: (name: string) => string; authorNote?: (author: string) => string };
};

export function noteListPresentation(
  note: {
    content: string;
    username?: string;
    display_name?: string | null;
    chemical_ids?: number[];
    reaction_ids?: number[];
  },
  t: NoteListDictionary,
): { title: string; summary: string } {
  const linkedEntityName = note.chemical_ids?.length
    ? t.common.hcidLabel(note.chemical_ids[0])
    : note.reaction_ids?.length
      ? t.common.hridLabel(note.reaction_ids[0])
      : null;
  const authorName = note.display_name || (note.username ? `@${note.username}` : null);
  const presentation = resolveNotePresentation(note.content, { authorName, linkedEntityName, t });
  return { title: presentation.title, summary: presentation.body };
}
