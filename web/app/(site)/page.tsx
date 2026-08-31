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
      </section>
      <div className="home-cards-kicker">{t.home.cardsKicker}</div>
      <div className="home-cards">
        <Link className="home-card home-card-mcp" href="/mcp-guide">
          <span className="home-card-kicker">{t.home.card1Kicker}</span>
          <strong>{t.home.card1Title}</strong>
          <span>{t.home.card1Body}</span>
          <span className="home-card-link">{t.home.card1Link}</span>
        </Link>
        <Link className="home-card home-card-skills" href="/skills">
          <span className="home-card-kicker">{t.home.card2Kicker}</span>
          <strong>{t.home.card2Title}</strong>
          <span>{t.home.card2Body}</span>
          <span className="home-card-link">{t.home.card2Link}</span>
        </Link>
        <Link className="home-card home-card-work" href="/aichem">
          <span className="home-card-kicker">{t.home.card3Kicker}</span>
          <strong>{t.home.card3Title}</strong>
          <span>{t.home.card3Body}</span>
          <span className="home-card-link">{t.home.card3Link}</span>
        </Link>
      </div>
    </div>
  );
}
