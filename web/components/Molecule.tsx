import { molSvgUrl } from "@/lib/api";

export function Molecule({ smiles, width = 260, height = 180 }: { smiles: string | null; width?: number; height?: number }) {
  if (!smiles) return <span className="result-sub">无结构</span>;
  // SVG is rendered by our validated RDKit endpoint; no remote image host is involved.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={molSvgUrl(smiles, width, height)} width={width} height={height} alt={`结构：${smiles}`} loading="lazy" />;
}
