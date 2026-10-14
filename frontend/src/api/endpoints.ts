/** One function per backend operation: the 17 endpoints of the API, and nothing else talks to the server. */
import { client, unwrap } from "./client";
import type { NoteCreate, SourceName, TradeCreate, TradeUpdate } from "./client";
import type { paths } from "./schema";

export type TradeListQuery = NonNullable<paths["/api/trades"]["get"]["parameters"]["query"]>;
export type NoteListQuery = NonNullable<paths["/api/notes"]["get"]["parameters"]["query"]>;
export type EventListQuery = NonNullable<paths["/api/events"]["get"]["parameters"]["query"]>;

// health
export const getHealth = () => unwrap(client.GET("/api/health"));
export const getReady = () => unwrap(client.GET("/api/ready"));

// trades
export const listTrades = (query: TradeListQuery) => unwrap(client.GET("/api/trades", { params: { query } }));
export const getTrade = (id: number) => unwrap(client.GET("/api/trades/{trade_id}", { params: { path: { trade_id: id } } }));
export const createTrade = (body: TradeCreate) => unwrap(client.POST("/api/trades", { body }));
export const updateTrade = (id: number, body: TradeUpdate) => unwrap(client.PATCH("/api/trades/{trade_id}", { params: { path: { trade_id: id } }, body }));
export const deleteTrade = (id: number) => unwrap(client.DELETE("/api/trades/{trade_id}", { params: { path: { trade_id: id } } }));

// day notes (a day can have several)
export const listNotes = (query: NoteListQuery) => unwrap(client.GET("/api/notes", { params: { query } }));
export const getNote = (id: number) => unwrap(client.GET("/api/notes/{note_id}", { params: { path: { note_id: id } } }));
export const createNote = (body: NoteCreate) => unwrap(client.POST("/api/notes", { body }));
export const updateNote = (id: number, body: { day?: string; body?: string }) => unwrap(client.PATCH("/api/notes/{note_id}", { params: { path: { note_id: id } }, body }));
export const deleteNote = (id: number) => unwrap(client.DELETE("/api/notes/{note_id}", { params: { path: { note_id: id } } }));

// tags and calendar
export const listTags = () => unwrap(client.GET("/api/tags"));
export const getMonth = (year: number, month: number) => unwrap(client.GET("/api/calendar/month", { params: { query: { year, month } } }));

// events from outside calendars, and the feeds that supply them
export const listEvents = (query: EventListQuery) => unwrap(client.GET("/api/events", { params: { query } }));
export const getSourcesStatus = () => unwrap(client.GET("/api/sources/status"));
/** Asks for a refresh of the named feeds (all of them when none are named). The answer is immediate: the fetch runs on the server's own time. */
export const requestSync = (sources?: SourceName[]) => unwrap(client.POST("/api/sync", { params: { query: { source: sources } } }));
