"use client";

import { useEffect, useState } from "react";
import { loadRuntimeStatus, type RuntimeStatus } from "../services/runtime-status";

const INITIAL_STATUS: RuntimeStatus = {
  status: "offline",
  backendReachable: false,
  backendStatusCode: null,
  checkedAt: null,
};

export function RuntimeStatusCard() {
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>(INITIAL_STATUS);

  useEffect(() => {
    let isMounted = true;
    let isFetching = false;

    const refresh = async () => {
      if (isFetching) {
        return;
      }

      isFetching = true;
      const nextStatus = await loadRuntimeStatus();

      if (isMounted) {
        setRuntimeStatus(nextStatus);
      }

      isFetching = false;
    };

    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, 10000);

    return () => {
      isMounted = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <article className="status-card" aria-live="polite">
      <div className="status-row">
        <strong>Runtime status</strong>
        <span className={`status-badge ${runtimeStatus.status}`}>{runtimeStatus.status}</span>
      </div>
      <p className="status-detail">Backend reachable: {runtimeStatus.backendReachable ? "Yes" : "No"}</p>
      <p className="status-detail">Status code: {runtimeStatus.backendStatusCode ?? "n/a"}</p>
      <p className="status-detail">Last check: {runtimeStatus.checkedAt ?? "pending"}</p>
    </article>
  );
}
