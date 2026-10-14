/**
 * The typed API client. Types come from src/api/schema.d.ts, generated from the server's OpenAPI document
 * (`npm run gen:api`); scripts/verify.py fails the run if that file is stale.
 */
import createClient, { type Middleware } from "openapi-fetch";

import { API_BASE_URL } from "../config";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Trade = Schemas["TradeRead"];
export type TradeCreate = Schemas["TradeCreate"];
export type TradeUpdate = Schemas["TradeUpdate"];
export type Note = Schemas["NoteRead"];
export type NoteCreate = Schemas["NoteCreate"];
export type MonthSummary = Schemas["MonthSummary"];
export type DaySummary = Schemas["DaySummary"];
export type TagUsage = Schemas["TagUsage"];
export type Ready = Schemas["Ready"];
export type EventItem = Schemas["EventRead"];
export type SourceStatus = Schemas["SourceStatus"];
export type SourceName = SourceStatus["source"];
export type SyncResponse = Schemas["SyncResponse"];
export type SyncResult = Schemas["SyncResult"];

/** The server answered, with an error. `detail` is FastAPI's body: a message, or a list of {loc, msg, type}. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `The server answered ${status}.`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** The request never got an answer. */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("Cannot reach the server.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

const randomHex = (length: number): string => Array.from({ length }, () => Math.floor(Math.random() * 16).toString(16)).join("");

// Every request carries an ID the server echoes into its logs. The "web-" prefix marks requests that
// came from the app itself, which lets verification prove the UI exercises every endpoint.
const requestId: Middleware = {
  onRequest({ request }) {
    request.headers.set("X-Request-ID", `web-${randomHex(12)}`);
    return request;
  },
};

// A 204 has no body for openapi-fetch to read, and a response whose body is never read keeps its request
// open as far as Chromium is concerned (it is reported as aborted when the page closes). Reading the empty
// body lets the request finish.
const finishEmptyResponses: Middleware = {
  async onResponse({ response }) {
    if (response.status === 204) await response.arrayBuffer();
    return undefined;
  },
};

export const client = createClient<paths>({ baseUrl: API_BASE_URL });
client.use(requestId);
client.use(finishEmptyResponses);

type Outcome<T> = { data?: T; error?: unknown; response: Response };

/** Resolves with the data, or throws ApiError (the server said no) or NetworkError (no answer). */
export async function unwrap<T>(request: Promise<Outcome<T>>): Promise<T> {
  let outcome: Outcome<T>;
  try {
    outcome = await request;
  } catch (cause) {
    throw new NetworkError(cause);
  }
  if (outcome.error !== undefined || !outcome.response.ok) {
    const body = outcome.error as { detail?: unknown } | undefined;
    throw new ApiError(outcome.response.status, body?.detail ?? outcome.error);
  }
  return outcome.data as T;
}
