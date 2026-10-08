type ChatKey = {
  key: string;
  shiftKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
  repeat?: boolean;
  isComposing?: boolean;
  keyCode?: number;
};

/** IME confirmation and Shift+Enter belong to the text editor, never to send. */
export function isChatSendKey(event: ChatKey, composing = false): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.ctrlKey &&
    !event.altKey && !event.metaKey && !event.repeat && !event.isComposing &&
    !composing && event.keyCode !== 229;
}
