import Link from "next/link";
import { GlobalSearch } from "@/components/GlobalSearch";
import t from "@/lib/i18n";

export default async function Home() {
  return (
    <div className="home">
      <section className="hero">
        <h1>{t.home.hero}</h1>
        <p className="hero-subtitle">{t.home.subtitle}</p>
        <GlobalSearch />
        <p className="hero-tagline">{t.home.heroTagline}</p>
      </section>
      <Link className="home-contribute" href="/guide">
        <span><span className="home-contribute-kicker">{t.home.ctaKicker}</span><strong>{t.home.ctaTitle}</strong></span>
        <span>{t.home.ctaBody}</span>
        <span className="home-contribute-link">{t.home.ctaLink}</span>
      </Link>
      <Link className="home-skills-entry" href="/skills">
        <span><span className="home-skills-kicker">{t.home.skillsKicker}</span><strong>{t.home.skillsTitle}</strong></span>
        <span>{t.home.skillsBody}</span>
        <span className="home-skills-link">{t.home.skillsLink}</span>
      </Link>
    </div>
  );
}
