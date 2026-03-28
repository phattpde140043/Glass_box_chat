"use client";

import { useEffect } from "react";

type ErrorPageProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  useEffect(() => {
    console.error("[App route error]", error);
  }, [error]);

  return (
    <main className="route-state-page">
      <section className="route-state-card route-state-card-error">
        <span className="route-state-kicker">Runtime Error</span>
        <h1>The workspace hit an unexpected UI failure.</h1>
        <p>
          Reload the route state and try again. If this keeps happening, inspect the trace events or backend logs for
          the current session.
        </p>
        <div className="route-state-actions">
          <button className="route-state-button" onClick={() => reset()} type="button">
            Retry route
          </button>
        </div>
        <p className="route-state-digest">Digest: {error.digest ?? "unavailable"}</p>
      </section>
    </main>
  );
}
