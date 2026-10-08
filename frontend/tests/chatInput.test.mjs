import assert from "node:assert/strict";
import test from "node:test";
import { isChatSendKey } from "../src/chatInput.ts";

test("Enter sends and Shift+Enter keeps a newline", () => {
  assert.equal(isChatSendKey({ key: "Enter" }), true);
  assert.equal(isChatSendKey({ key: "Enter", shiftKey: true }), false);
  assert.equal(isChatSendKey({ key: "a" }), false);
});
test("Korean/Japanese IME confirmation never sends prematurely", () => {
  assert.equal(isChatSendKey({ key: "Enter", isComposing: true }), false);
  assert.equal(isChatSendKey({ key: "Enter", keyCode: 229 }), false);
  assert.equal(isChatSendKey({ key: "Enter" }, true), false);
  assert.equal(isChatSendKey({ key: "Process", keyCode: 229 }), false);
});
test("held Enter and modified shortcuts cannot submit repeatedly", () => {
  for (const modifier of ["repeat", "altKey", "ctrlKey", "metaKey"])
    assert.equal(isChatSendKey({ key: "Enter", [modifier]: true }), false);
});
