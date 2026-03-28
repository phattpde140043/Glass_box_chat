export function WorkspaceOverview() {
  return (
    <aside className="workspace-overview" aria-label="Workspace overview">
      <article className="workspace-card workspace-card-accent">
        <span className="workspace-card-label">Mission</span>
        <h2>Understand the full runtime path of every answer.</h2>
        <p>
          The workspace combines live chat, agent state, and trace branches so debugging happens in one place.
        </p>
      </article>

      <article className="workspace-card">
        <span className="workspace-card-label">What you can inspect</span>
        <ul className="workspace-list">
          <li>Assistant responses with supporting sources</li>
          <li>Per-session execution branches and tool events</li>
          <li>Runtime health and aggregate execution metrics</li>
        </ul>
      </article>

      <article className="workspace-card">
        <span className="workspace-card-label">Operator hints</span>
        <ul className="workspace-list">
          <li>Use Enter to submit and Shift + Enter for multi-line prompts</li>
          <li>Expand supporting events when the main branch is too condensed</li>
          <li>Use the floating button to jump back to the latest trace activity</li>
        </ul>
      </article>
    </aside>
  );
}
