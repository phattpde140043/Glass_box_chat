import type { ChatMessageRecord } from "../validation/chat-schemas";

type ChatMessageListProps = {
  isSending: boolean;
  messages: ChatMessageRecord[];
};

export function ChatMessageList({ isSending, messages }: ChatMessageListProps) {
  return (
    <div className="chat-messages" role="log" aria-live="polite">
      {messages.map((message) => (
        <article key={message.id} className={`message-row ${message.role}`}>
          <div className={`message-bubble ${message.role}`}>{message.content}</div>
        </article>
      ))}

      {isSending ? (
        <article className="message-row assistant">
          <div className="message-bubble assistant loading">Receiving response...</div>
        </article>
      ) : null}
    </div>
  );
}
