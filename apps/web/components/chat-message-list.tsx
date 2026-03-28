import type { ChatMessageRecord } from "../validation/chat-schemas";

type ChatMessageListProps = {
  isSending: boolean;
  messages: ChatMessageRecord[];
};

export function ChatMessageList({ isSending, messages }: ChatMessageListProps) {
  const readDomain = (url: string): string => {
    try {
      return new URL(url).hostname;
    } catch {
      return url;
    }
  };

  return (
    <div className="chat-messages" role="log" aria-live="polite">
      {messages.map((message) => (
        <article key={message.id} className={`message-row ${message.role}`}>
          <div className={`message-bubble ${message.role}`}>
            <div>{message.content}</div>
            {message.role === "assistant" && message.sourceDetails && message.sourceDetails.length > 0 ? (
              <div className="message-sources">
                <strong>Nguon tham khao:</strong>
                <div className="message-source-list">
                  {message.sourceDetails.map((sourceDetail) => (
                    <a key={sourceDetail.url} href={sourceDetail.url} target="_blank" rel="noreferrer">
                      {sourceDetail.title}
                      <span className="message-source-meta">{readDomain(sourceDetail.url)} | {sourceDetail.freshness}</span>
                    </a>
                  ))}
                </div>
              </div>
            ) : message.role === "assistant" && message.sources && message.sources.length > 0 ? (
              <div className="message-sources">
                <strong>Nguon tham khao:</strong>
                <div className="message-source-list">
                  {message.sources.map((source) => (
                    <a key={source} href={source} target="_blank" rel="noreferrer">
                      {source}
                    </a>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </article>
      ))}

      {isSending ? (
        <article className="message-row assistant">
          <div className="message-bubble assistant loading">Đang nhận phản hồi...</div>
        </article>
      ) : null}
    </div>
  );
}