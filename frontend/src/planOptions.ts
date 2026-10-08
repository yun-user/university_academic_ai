import type { Options } from "./types";

export function maxSemesters(options: Options): number {
  if (!Number.isInteger(options.start_year) || options.start_year < 2018 ||
      options.start_year > 2100 || ![1, 2].includes(options.start_term)) return 0;
  return Math.min(12, (2100 - options.start_year) * 2 + 3 - options.start_term);
}

/** Preserve explicitly chosen limits, including a zero-credit break semester. */
export function resizeSemesters(options: Options, count: number): Options {
  return {
    ...options,
    semesters: count,
    semester_limits: options.semester_limits?.length
      ? Array.from({ length: count }, (_, i) => options.semester_limits?.[i] ?? options.credit_limit)
      : [],
  };
}
