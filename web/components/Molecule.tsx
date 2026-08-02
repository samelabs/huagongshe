import { molSvgUrl } from "@/lib/api";
import t from "@/lib/i18n";

export function Molecule({ chemicalId, smiles, width = 260, height = 180 }: { chemicalId: number; smiles?: string | null; width?: number; height?: number }) {
  if (!chemicalId) return <span className="result-sub">{t.reaction.noStructure}</span>;
  // SVG is rendered by our validated RDKit endpoint; no remote image host is involved.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={molSvgUrl(chemicalId, width, height)} width={width} height={height} alt={smiles ? t.reaction.smiles + "：" + smiles : `HCID ${chemicalId}`} loading="lazy" />;
}
