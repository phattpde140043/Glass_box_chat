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
          <div className={`message-bubble ${message.role}`}>
            <div>{message.content}</div>

            {message.role === "assistant" && ((message.sourceDetails?.length ?? 0) > 0 || (message.sources?.length ?? 0) > 0) ? (
              <div className="message-sources">
                <strong>Sources</strong>

                <div className="message-source-list">
                  {message.sourceDetails?.map((source) => (
                    <a key={`${message.id}-${source.url}`} href={source.url} rel="noreferrer" target="_blank">
                      {source.title}
                      {source.freshness ? <span className="message-source-meta">{source.freshness}</span> : null}
                    </a>
                  ))}

                  {(message.sourceDetails?.length ?? 0) === 0
                    ? message.sources?.map((sourceUrl) => (
                        <a key={`${message.id}-${sourceUrl}`} href={sourceUrl} rel="noreferrer" target="_blank">
                          {sourceUrl}
                        </a>
                      ))
                    : null}
                </div>
              </div>
            ) : null}
          </div>
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
