import { TraceEventModel } from "../models/trace-event";
import type { TraceEventRecord } from "../validation/chat-schemas";

const DATABASE_NAME = "glass-box-trace-db";
const DATABASE_VERSION = 1;
const STORE_NAME = "runtime-trace";
const TRACE_KEY = "all-events";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION);

    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME);
      }
    };

    request.onsuccess = () => {
      resolve(request.result);
    };

    request.onerror = () => {
      reject(request.error ?? new Error("Failed to open IndexedDB."));
    };
  });
}

class IndexedDbTraceStorage {
  async load(): Promise<TraceEventRecord[]> {
    if (typeof window === "undefined") {
      return [];
    }

    const database = await openDatabase();

    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readonly");
      const store = transaction.objectStore(STORE_NAME);
      const request = store.get(TRACE_KEY);

      request.onsuccess = () => {
        const rawValue = request.result;
        if (!rawValue) {
          resolve([]);
          return;
        }

        resolve(TraceEventModel.parseList(rawValue));
      };

      request.onerror = () => {
        reject(request.error ?? new Error("Failed to read trace events from IndexedDB."));
      };
    });
  }

  async save(events: TraceEventRecord[]): Promise<void> {
    if (typeof window === "undefined") {
      return;
    }

    const validatedEvents = TraceEventModel.parseList(events);
    const database = await openDatabase();

    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      const store = transaction.objectStore(STORE_NAME);
      const request = store.put(validatedEvents, TRACE_KEY);

      request.onsuccess = () => {
        resolve();
      };

      request.onerror = () => {
        reject(request.error ?? new Error("Failed to write trace events to IndexedDB."));
      };
    });
  }
}

export const traceStorage = new IndexedDbTraceStorage();
