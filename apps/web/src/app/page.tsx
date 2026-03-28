import { RuntimeStatusCard } from "../components/runtime-status-card";

export default function Home() {
  return (
    <main className="landing-page">
      <section className="hero-card">
        <p className="eyebrow">Glass Box Runtime</p>
        <h1>Observe how your agent thinks in real time.</h1>
        <p className="hero-copy">
          This UI surfaces runtime health and execution traces so your team can debug behavior faster.
        </p>
        <RuntimeStatusCard />
      </section>
    </main>
  );
}
