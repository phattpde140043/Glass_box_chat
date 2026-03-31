import EventEmitter from "eventemitter3";

export type RuntimeEvent<TPayload = unknown> = {
  id: string;
  type: string;
  payload: TPayload;
};

export class RuntimeEventBus {
  private readonly emitter = new EventEmitter<{ event: [RuntimeEvent] }>();

  emit(event: RuntimeEvent) {
    this.emitter.emit("event", event);
  }

  subscribe(listener: (event: RuntimeEvent) => void) {
    this.emitter.on("event", listener);

    return () => {
      this.emitter.off("event", listener);
    };
  }
}