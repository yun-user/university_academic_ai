import assert from "node:assert/strict";
import test from "node:test";
import { mergeMessages } from "../src/chatMessages.ts";

test("late history cannot overwrite an answer that completed while history loaded", () => {
  const answer = { id: "one", sequence: 1, revision: 1, status: "complete", answer: "완료" };
  const pending = { id: "one", sequence: 1, revision: 1, status: "pending" };
  assert.deepEqual(mergeMessages([answer], [pending]), [answer]);
  assert.deepEqual(mergeMessages([pending], [answer]), [answer]);
});

test("overlapping pages retain order and latest feedback without duplicates", () => {
  const reviewed = { id: "b", sequence: 2, revision: 2, status: "complete", feedback: { rating: "unhelpful" } };
  const old = { ...reviewed, revision: 1, feedback: {} };
  const earlier = { id: "a", sequence: 1, revision: 1, status: "complete" };
  const current = [reviewed];
  assert.deepEqual(mergeMessages(current, [old, earlier]), [earlier, reviewed]);
  assert.deepEqual(current, [reviewed]);
});
