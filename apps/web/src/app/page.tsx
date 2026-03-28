import { ChatShell } from "../../components/chat-shell";
import { WorkspaceOverview } from "../../components/workspace-overview";

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
