"""MCP 边界错误映射：领域/校验异常 → 中性英文 ToolError 文案。"""

from mcp.server.mcpserver.exceptions import ToolError

def _render_busy() -> ToolError:
    return ToolError("Rendering concurrency limit reached. Try again shortly.")

# MCP validation translator:
# reaction schemas raise Chinese ValueError messages for the REST/Web surface.
# The MCP boundary maps those known messages to English; unknown messages get a
# safe neutral fallback instead of leaking raw text. Field locations are kept.
_VALIDATION_MESSAGE_MAP = {
    "只有产物可以填写收率": "yield is only allowed for PRODUCT participants",
    "投料数值和单位必须同时填写": "amount_value and amount_unit must be provided together",
    "浓度数值和单位必须同时填写": "concentration_value and concentration_unit must be provided together",
    "DOI 格式不正确": "invalid DOI format",
    "至少需要一个反应物和一个产物": "at least one REACTANT and one PRODUCT are required",
    "温度数值和单位必须同时填写": "temperature_value and temperature_unit must be provided together",
    "反应时间数值和单位必须同时填写": "duration_value and duration_unit must be provided together",
    "压力数值和单位必须同时填写": "pressure_value and pressure_unit must be provided together",
    "来源链接必须以 http:// 或 https:// 开头": "source_url must start with http:// or https://",
}


def _english_validation_message(raw: str) -> str:
    """Map a known schema validation message to English; neutral fallback otherwise."""
    text = raw.strip()
    if text.startswith("Value error, "):
        text = text[len("Value error, "):]
    if text in _VALIDATION_MESSAGE_MAP:
        return _VALIDATION_MESSAGE_MAP[text]
    if text.startswith("来源类型") and "缺少对应的来源信息" in text:
        # f-string message: 来源类型 {source_type} 缺少对应的来源信息
        # (the f-string gap may render as a regular or full-width space)
        source_type = text[len("来源类型"):].split("缺少", 1)[0].strip() or "value"
        return f"source_type '{source_type}' is missing its required source evidence"
    if not text:
        return "invalid value"
    # Unknown message: keep neutral English, never leak the raw text.
    return "invalid value"


def _validation_error_message(prefix: str, exc: Exception) -> str:
    """Keep field-level Pydantic context while exposing an English MCP error."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        parts: list[str] = []
        for item in errors()[:4]:
            loc = ".".join(str(value) for value in item.get("loc", ()))
            msg = _english_validation_message(str(item.get("msg", "invalid value")))
            parts.append(f"{loc}: {msg}" if loc else msg)
        if parts:
            return f"{prefix}: " + "; ".join(parts)
    return prefix


def _detail_tail(detail: str, marker: str) -> str:
    if marker not in detail:
        return ""
    return detail.split(marker, 1)[1].strip()


def _rate_error_message(exc: Exception) -> str:
    """English MCP boundary for neutral rate/resource errors."""
    name = type(exc).__name__
    if name == "RateLimited":
        return "Too many requests. Try again shortly."
    if name == "LimiterUnavailable":
        return "Rate-limit service is temporarily unavailable. Try again shortly."
    if name == "ResourceBusy":
        return "Structure-search concurrency limit reached. Try again shortly."
    return "The request could not be admitted by the resource limiter."


def _search_error_message(exc: Exception) -> str:
    kind = getattr(exc, "kind", "")
    if kind == "invalid_structure":
        return "The SMILES structure could not be recognized."
    if kind == "query_too_short":
        return "Name queries require at least 3 characters, or at least 2 CJK characters."
    if kind == "substructure_too_small":
        return "The substructure query is too small; provide a more specific structure."
    if kind == "invalid_doi":
        return "The DOI is invalid."
    if kind == "invalid_cas":
        return "The CAS number check digit is incorrect."
    if kind == "backend_unavailable":
        return "Search timed out. Use a more specific name, identifier, or structure."
    return "The chemistry search could not be completed."


def _reaction_error_message(exc: Exception) -> str:
    kind = getattr(exc, "kind", "")
    detail = str(getattr(exc, "detail", "") or "")
    if kind == "invalid_structure":
        value = _detail_tail(detail, "的结构无法解析：")
        return (
            f"Could not parse reaction participant structure: {value}"
            if value else "Could not parse a reaction participant structure."
        )
    if kind == "duplicate_participant":
        return "Merge duplicate entries with the same compound and role, then set occurrence_count."
    if kind == "invalid_reaction":
        return "The reaction structure could not be parsed by RDKit."
    status = getattr(exc, "status", "")
    if status == "CONFLICT":
        return "Chemical identity conflict prevents automatic reaction creation."
    if status == "AMBIGUOUS":
        return "Chemical identity is ambiguous; multiple candidates require manual resolution."
    name = type(exc).__name__
    if name == "MissingIdempotencyKeyError":
        return "idempotency_key is required for authenticated reaction creation."
    if name == "IdempotencyKeyTooLongError":
        return "idempotency_key must not exceed 200 characters."
    return "The reaction request could not be completed."


def _stoichiometry_error_message(exc: Exception) -> str:
    detail = str(exc)
    if detail.startswith("基准 index ") and detail.endswith(" 超出组分范围"):
        value = detail[len("基准 index "):-len(" 超出组分范围")]
        return f"Basis index {value} is outside the component range."
    if detail.startswith("组分 ") and "）缺少 eq（仅溶剂可留空）" in detail:
        middle = detail[len("组分 "):].split("）缺少 eq", 1)[0]
        if "（" in middle:
            index, role = middle.split("（", 1)
            return f"Component {index} ({role}) is missing eq; only solvent rows may omit eq."
    if detail == "按浓度定容仅支持单一溶剂行":
        return "Concentration-based volume calculation supports only one solvent row."
    if detail.startswith("组分 ") and "）的 SMILES 无法解析：" in detail:
        left, smiles = detail.split("）的 SMILES 无法解析：", 1)
        middle = left[len("组分 "):]
        if "（" in middle:
            index, role = middle.split("（", 1)
            return f"Component {index} ({role}) has an unparseable SMILES: {smiles}"
    return "Stoichiometry input is invalid."


def _skill_error_message(exc: Exception) -> str:
    name = type(exc).__name__
    detail = str(getattr(exc, "detail", "") or "")
    if name == "SkillNotAccessibleError":
        return "Skill not found or not accessible."
    if name == "SkillCategoryError":
        return "The requested skill category does not exist or is disabled."
    if name == "SkillSlugConflictError":
        return "A skill with the same slug already exists for this user."
    if name == "MissingSkillIdempotencyKeyError":
        return "idempotency_key is required for authenticated skill creation."
    if name == "SkillIdempotencyKeyTooLongError":
        return "idempotency_key must not exceed 200 characters."
    if name == "SkillArchiveValidationError":
        kind = getattr(exc, "kind", "")
        tail = detail.split("：", 1)[1].strip() if "：" in detail else ""
        if kind == "archive_too_large":
            return "The skill archive exceeds the allowed ZIP size."
        if kind == "invalid_archive":
            return "The supplied file is not a valid ZIP archive."
        if kind == "unsafe_path":
            if detail.startswith("目录层级过深："):
                return f"Archive path is nested too deeply: {tail}"
            if detail.startswith("不允许符号链接："):
                return f"Symbolic links are not allowed in skill archives: {tail}"
            return f"Unsafe archive path: {tail}" if tail else "The skill archive contains an unsafe path."
        if kind == "decompression":
            return (
                f"Suspicious compression ratio detected for archive entry: {tail}"
                if tail else "The skill archive failed decompression safety checks."
            )
        if kind == "empty_archive":
            return "The skill archive contains no files."
        if kind == "archive_limit":
            if detail.startswith("文件数超过 "):
                value = detail[len("文件数超过 "):].split(" ", 1)[0]
                return f"The skill archive exceeds the {value}-file limit."
            if detail.startswith("解包后总量超过 "):
                value = detail[len("解包后总量超过 "):].split(" ", 1)[0]
                return f"The extracted skill archive exceeds the {value} total-size limit."
            if detail.startswith("单文件超过 "):
                rest = detail[len("单文件超过 "):]
                limit, _, path = rest.partition(" 上限：")
                return f"Archive entry {path} exceeds the {limit} per-file limit."
            return "The skill archive exceeds a file or content limit."
        if kind == "manifest_invalid":
            if detail == "压缩包根目录必须包含 SKILL.md":
                return "SKILL.md must exist at the root of the archive."
            if detail == "SKILL.md frontmatter 必须包含 name 和 description":
                return "SKILL.md frontmatter must include name and description."
            if detail.startswith("二进制文件只能放在 assets/ 或 examples/ 目录："):
                return f"Binary files are allowed only under assets/ or examples/: {tail}"
            if detail.startswith("技能名无法转为合法 slug："):
                return f"The skill name cannot be converted to a valid slug: {tail}"
            return "SKILL.md or its manifest metadata is invalid."
    return "The skill request could not be completed."
