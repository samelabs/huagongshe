export function EntityId({ kind, id, compact = false }: {
  kind: "chemical" | "reaction";
  id: number | string;
  compact?: boolean;
}) {
  const prefix = kind === "chemical" ? "HCID" : "HRID";
  return (
    <span className={`entity-id ${kind}${compact ? " compact" : ""}`} aria-label={`${prefix} ${id}`}>
      <span>{prefix}</span><strong>{id}</strong>
    </span>
  );
}
