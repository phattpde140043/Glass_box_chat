import Link from "next/link";

export default function NotFound() {
  return (
    <main className="route-state-page">
      <section className="route-state-card">
        <span className="route-state-kicker">404</span>
        <h1>That runtime view does not exist.</h1>
        <p>The requested route could not be found. Return to the main chat workspace to continue.</p>
        <Link className="route-state-link" href="/">
          Back to chat
        </Link>
      </section>
    </main>
  );
}
