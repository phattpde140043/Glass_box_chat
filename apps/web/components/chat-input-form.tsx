import type { FormEvent, KeyboardEvent } from "react";

type ChatInputFormProps = {
  canSend: boolean;
  currentLength: number;
  inputError: string | null;
  isSending: boolean;
  maxLength: number;
  onChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => Promise<void>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  value: string;
};

export function ChatInputForm({
  canSend,
  currentLength,
  inputError,
  isSending,
  maxLength,
  onChange,
  onKeyDown,
  onSubmit,
  value,
}: ChatInputFormProps) {
  return (
    <form className="chat-input-area" onSubmit={onSubmit} noValidate>
      <div className="chat-input-stack">
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Enter your message..."
          rows={1}
          maxLength={maxLength}
          disabled={isSending}
          aria-invalid={inputError ? true : false}
          aria-describedby="chat-input-meta chat-input-error"
        />
        <div className="chat-input-meta" id="chat-input-meta">
          <span>Enter to send, Shift + Enter for new line</span>
          <span>
            {currentLength}/{maxLength}
          </span>
        </div>
        {inputError ? (
          <p className="chat-input-error" id="chat-input-error" role="alert">
            {inputError}
          </p>
        ) : null}
      </div>

      <button type="submit" disabled={!canSend}>
        Send
      </button>
    </form>
  );
}
