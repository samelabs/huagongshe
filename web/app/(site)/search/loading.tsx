import { Skeleton } from "@/components/ui/Skeleton";

/** /search 路由加载态（Step 10 §9.3）：Skeleton card × 3（IX-4 列表骨架）。 */
export default function SearchLoading() {
  return (
    <div className="content-page search-page">
      <div className="search-skeleton" aria-hidden="true">
        <Skeleton variant="card" />
        <Skeleton variant="card" />
        <Skeleton variant="card" />
      </div>
    </div>
  );
}
