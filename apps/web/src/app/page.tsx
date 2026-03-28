import { ChatShell } from "../../components/chat-shell";
import { WorkspaceOverview } from "../../components/workspace-overview";
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
import Image from "next/image";

export default function Home() {
  return (
    <main className="workspace-page">
      <section className="workspace-hero">
        <p className="workspace-kicker">Glass Box Runtime</p>
        <h1>Operate the chat runtime like a visible system, not a black box.</h1>
        <p className="workspace-copy">
          Review agent output, inspect trace activity, and keep operators aligned on what the runtime is doing in each
          session.
        </p>
      </section>

      <section className="workspace-grid">
        <WorkspaceOverview />
        <ChatShell />
      </section>
    </main>
  );
}
