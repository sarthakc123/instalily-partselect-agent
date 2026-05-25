/**
 * Minimal SSE frame parser. Yields JSON-parsed payloads from `data:` lines.
 * The backend emits one event per frame, terminated by a blank line.
 *
 * We do NOT depend on `EventSource` because it only supports GET requests
 * and we want POST + headers + cancellation. Hand-rolling the parser is
 * ~40 lines and avoids that constraint.
 *
 * Accepts both `\n\n` and `\r\n\r\n` frame separators because different
 * SSE servers emit different line endings (sse-starlette in particular
 * uses CRLF). Lines within a frame are split on `\r?\n`.
 */

import type { OrchestratorEvent } from "./types";

const FRAME_BOUNDARY = /\r?\n\r?\n/;
const LINE_BOUNDARY = /\r?\n/;

export async function* parseSSE(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<OrchestratorEvent> {
  if (!response.body) {
    throw new Error("Response has no body");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel();
        return;
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Split off every complete frame from the front of the buffer.
      while (true) {
        const match = FRAME_BOUNDARY.exec(buffer);
        if (!match) break;
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);

        for (const line of frame.split(LINE_BOUNDARY)) {
          if (!line.startsWith("data:")) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            yield JSON.parse(json) as OrchestratorEvent;
          } catch {
            // Skip malformed frames silently; backend should never produce these.
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
