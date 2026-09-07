import { postStream } from "@/lib/api";
import type { AnyStrategy, StrategySource } from "./api";

/**
 * Reading the generation stream.
 *
 * The wire format is server-sent events: `event: <name>`, then `data: <json>`,
 * then a blank line. Four events, and every one of them carries JSON -- even
 * `chunk`, whose payload is a single string. That is not decoration. A frame
 * ends at the first blank line, so a bare newline inside a `data:` line would
 * cut the frame short and everything after it would be read as a new frame.
 * Model output is full of newlines, and the symptom would look like the model
 * writing broken markdown rather than like a transport problem.
 */

export interface StartData {
  assistant_message_id: string;
  /** What actually ran, which is not always what the conversation defaults to. */
  strategy: AnyStrategy;
  source: StrategySource;
  model: string;
}

export interface ChunkData {
  text: string;
}

export interface DoneData {
  generation_id: string;
  /** Null when the provider reported no usage; never counted locally. */
  input_tokens: number | null;
  output_tokens: number | null;
  degradations: string[];
}

export interface ErrorData {
  detail: string;
}

export type StreamEvent =
  | { type: "start"; data: StartData }
  | { type: "chunk"; data: ChunkData }
  | { type: "done"; data: DoneData }
  | { type: "error"; data: ErrorData };

const FRAME_END = "\n\n";

/** One frame's `event:` name and its joined `data:` payload. */
function parseFrame(frame: string): { event: string; data: string } | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    // A line starting with a colon is a keep-alive comment, not a field.
    if (line === "" || line.startsWith(":")) continue;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    // The spec allows exactly one optional space after the colon.
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }

  if (dataLines.length === 0) return null;
  // Multi-line data is joined with newlines by the spec. The backend always
  // writes one line, so this is here to be correct rather than because it fires.
  return { event, data: dataLines.join("\n") };
}

function toEvent(event: string, data: string): StreamEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    throw new Error(`The stream sent a ${event} frame that is not JSON.`);
  }

  switch (event) {
    case "start":
      return { type: "start", data: payload as StartData };
    case "chunk":
      return { type: "chunk", data: payload as ChunkData };
    case "done":
      return { type: "done", data: payload as DoneData };
    case "error":
      return { type: "error", data: payload as ErrorData };
    default:
      // An event name this client does not know is ignored rather than fatal,
      // so a new one added on the server does not break an old tab.
      return null;
  }
}

/**
 * Open the stream and yield its events in order.
 *
 * One run is zero or more `chunk` events and then exactly one terminal event,
 * `done` or `error`. `start` always arrives first, before any text, because it
 * carries the id of the assistant row the reply is being written into -- the
 * client needs that id to render the reply in the right place and to keep it
 * after a reload.
 */
export async function* readGeneration(
  path: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const body = await postStream(path, signal);
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();

      if (value !== undefined) {
        // `stream: true` keeps a multi-byte character that straddles two
        // chunks intact instead of decoding it as two replacement characters.
        buffer += decoder.decode(value, { stream: true });
        // CRLF is legal in the protocol. A lone trailing \r stays in the
        // buffer and is normalised once its \n arrives in the next chunk.
        buffer = buffer.replace(/\r\n/g, "\n");
      }

      let boundary = buffer.indexOf(FRAME_END);
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + FRAME_END.length);

        const parsed = parseFrame(frame);
        if (parsed !== null) {
          const streamEvent = toEvent(parsed.event, parsed.data);
          if (streamEvent !== null) yield streamEvent;
        }

        boundary = buffer.indexOf(FRAME_END);
      }

      if (done) break;
    }
  } finally {
    // Releasing the lock is not enough on an early exit: the caller navigating
    // away has to actually cancel the body, or the request stays open. The
    // server then finishes the generation with nobody listening, which is why
    // an abandoned reply can stay unfinished in the database.
    await reader.cancel().catch(() => undefined);
  }
}
