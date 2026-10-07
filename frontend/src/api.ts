export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-Planner-Request": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(65000),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "서버에 연결할 수 없습니다." }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "입력 내용을 확인하세요.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
