import type { Message } from "./types";

// A delayed history response must not replace a completed answer or newer review.
export function mergeMessages(current: Message[], incoming: Message[]): Message[] {
  const merged = new Map(current.map((message) => [message.id, message]));
  const statusRank = (status?: string) => status === "complete" ? 2 : status === "interrupted" ? 1 : 0;
  for (const message of incoming) {
    const previous = merged.get(message.id);
    if (!previous || (message.revision ?? 1) > (previous.revision ?? 1) ||
        ((message.revision ?? 1) === (previous.revision ?? 1) && statusRank(message.status) >= statusRank(previous.status))) {
      merged.set(message.id, message);
    }
  }
  return [...merged.values()].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));
}
