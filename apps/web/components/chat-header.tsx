import type { AgentStatus } from "../validation/chat-schemas";

type ChatHeaderProps = {
  agentStatus: AgentStatus;
};

export function ChatHeader({ agentStatus }: ChatHeaderProps) {
  return (
    <header className="chat-header">
      <div>
        <h1>Glass Box Chat</h1>
        <p>Chat-first UI with runtime trace visibility</p>
      </div>
      <span className={`status-pill ${agentStatus}`}>{agentStatus}</span>
    </header>
  );
}
