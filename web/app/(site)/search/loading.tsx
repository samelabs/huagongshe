import { PageFrame } from "@/components/ui/PageFrame";
import { Skeleton } from "@/components/ui/Skeleton";

/** /search 路由加载态：与结果页同一页框，Skeleton card × 3（列表骨架）。 */
export default function SearchLoading() {
  return (
    <PageFrame className="search-page">
      <div className="search-skeleton" aria-hidden="true">
        <Skeleton variant="card" />
        <Skeleton variant="card" />
        <Skeleton variant="card" />
      </div>
    </PageFrame>
  );
}
