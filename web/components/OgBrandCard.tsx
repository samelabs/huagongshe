import { ogColors } from "@/lib/ogTokens";

/**
 * OgBrandCard — 实体页 OG 品牌卡 1200×630（G4 收口）。
 *
 * HGS 标志 + 名称 + HCID/HRID 徽标 + 结构图（/api/mol/{id}/png 拉成 data URL）。
 * 只在 opengraph-image 路由里被 next/og 渲染: satori 仅支持 flex 布局、
 * 颜色来自 ogTokens 镜像（tokens.css 的 canvas 侧副本）。
 * imageUrl 为空（无结构可渲染/兜底卡）时退化为整宽文字卡。
 */
export function OgBrandCard({ title, badge, note, imageUrl, logoSrc, wordmark }: {
  title: string;
  badge: string;
  note: string;
  imageUrl?: string | null;
  logoSrc: string | null;
  /** 品牌字标文案（随请求字典 t.brand.name，不硬编码单语） */
  wordmark: string;
}) {
  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      backgroundColor: ogColors.page, padding: "56px 64px 48px",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          {logoSrc
            ? <img src={logoSrc} width={88} height={88} alt="" style={{ borderRadius: 20 }} />
            : <div style={{ display: "flex", width: 88, height: 88, borderRadius: 20, backgroundColor: ogColors.brand }} />}
          <div style={{ display: "flex", fontSize: 40, fontWeight: 700, color: ogColors.text }}>{wordmark}</div>
        </div>
        <div style={{ display: "flex", fontSize: 26, color: ogColors.muted }}>huagongshe.com</div>
      </div>
      <div style={{ display: "flex", flex: 1, alignItems: "center", gap: 48, minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", flex: 1, gap: 24, minWidth: 0 }}>
          <div style={{
            display: "flex", alignSelf: "flex-start", padding: "10px 28px",
            backgroundColor: ogColors.blue50, color: ogColors.actionInk,
            borderRadius: 999, fontSize: 28, fontWeight: 600,
          }}>{badge}</div>
          <div style={{
            display: "flex", fontSize: title.length > 24 ? 56 : 72, fontWeight: 700,
            color: ogColors.text, lineHeight: 1.15,
          }}>{title}</div>
          <div style={{ display: "flex", fontSize: 26, color: ogColors.muted }}>{note}</div>
        </div>
        {imageUrl ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            width: 420, height: 380, backgroundColor: ogColors.subtle,
            border: `1px solid ${ogColors.border}`, borderRadius: 24,
          }}>
            <img src={imageUrl} width={372} height={332} alt="" style={{ objectFit: "contain" }} />
          </div>
        ) : null}
      </div>
      <div style={{ display: "flex", width: "100%", height: 8, backgroundColor: ogColors.brand, borderRadius: 4 }} />
    </div>
  );
}
