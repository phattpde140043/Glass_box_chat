export default function Loading() {
  return (
    <main className="route-state-page" aria-busy="true" aria-live="polite">
      <section className="route-state-card">
        <span className="route-state-kicker">Glass Box Runtime</span>
        <div className="route-state-spinner" aria-hidden="true" />
        <h1>Loading the runtime workspace...</h1>
        <p>The chat shell and trace panel are being prepared for this session.</p>
      </section>
    </main>
  );
}
