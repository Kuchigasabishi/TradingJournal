/** React Query hooks over src/api/endpoints.ts. Lists keep their previous page on screen while the next one loads. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  type EventListQuery,
  type NoteListQuery,
  type TradeListQuery,
  createNote,
  createTrade,
  deleteNote,
  deleteTrade,
  getHealth,
  getMonth,
  getNote,
  getSourcesStatus,
  getTrade,
  listEvents,
  listNotes,
  listTags,
  listTrades,
  requestSync,
  updateNote,
  updateTrade,
} from "./endpoints";
import { ApiError, type EventItem, type NoteCreate, type SourceName, type TradeCreate, type TradeUpdate } from "./client";

/** Server errors are final (retrying a 4xx or 5xx changes nothing); only a missing connection is retried, once. */
const retryNetworkOnce = (failures: number, error: unknown): boolean => !(error instanceof ApiError) && failures < 1;

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 30_000, retry: false });
}

export function useTrades(query: TradeListQuery) {
  return useQuery({ queryKey: ["trades", query], queryFn: () => listTrades(query), placeholderData: keepPreviousData, retry: retryNetworkOnce });
}

const isId = (id: number): boolean => Number.isInteger(id) && id >= 1;

// A malformed address such as /trades/abc never reaches the server: the screen shows "not found" itself.
export function useTrade(id: number) {
  return useQuery({ queryKey: ["trade", id], queryFn: () => getTrade(id), enabled: isId(id), retry: retryNetworkOnce });
}

export function useTags() {
  return useQuery({ queryKey: ["tags"], queryFn: listTags, retry: retryNetworkOnce });
}

export function useMonth(year: number, month: number) {
  return useQuery({ queryKey: ["month", year, month], queryFn: () => getMonth(year, month), placeholderData: keepPreviousData, retry: retryNetworkOnce });
}

export function useNotes(query: NoteListQuery) {
  return useQuery({ queryKey: ["notes", query], queryFn: () => listNotes(query), placeholderData: keepPreviousData, retry: retryNetworkOnce });
}

const EVENT_PAGE = 500; // the most the API returns at once
const EVENT_PAGES_MAX = 10;

/** Every event of a range, however many pages it takes: a month of news can hold more than one page. */
async function listAllEvents(query: Omit<EventListQuery, "limit" | "offset">): Promise<{ items: EventItem[]; total: number }> {
  const items: EventItem[] = [];
  let total = 0;
  for (let page = 0; page < EVENT_PAGES_MAX; page += 1) {
    const result = await listEvents({ ...query, limit: EVENT_PAGE, offset: page * EVENT_PAGE });
    items.push(...result.items);
    total = result.total;
    if (items.length >= total || result.items.length === 0) break;
  }
  return { items, total };
}

export function useEvents(query: Omit<EventListQuery, "limit" | "offset">) {
  return useQuery({ queryKey: ["events", query], queryFn: () => listAllEvents(query), placeholderData: keepPreviousData, retry: retryNetworkOnce });
}

/** Where each feed stands. While a sync is waiting or running it looks again every second, so the screen follows it to the end. */
export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: getSourcesStatus,
    retry: retryNetworkOnce,
    refetchInterval: (query) => (query.state.data?.some((source) => source.state !== "idle") ? 1_000 : false),
  });
}

/**
 * Reloads the events whenever a feed finishes a sync. A sync runs on the server's own schedule (at startup, every
 * few minutes, and when someone presses "Sync now"), so the screen learns about it from the feed status: the
 * moment a feed's last success or event count changes, what was loaded is out of date.
 */
export function useRefreshEventsOnSync(): void {
  const client = useQueryClient();
  const sources = useSources();
  const seen = useRef<string | null>(null);
  const signature = sources.data?.map((source) => `${source.source}:${source.last_success_at ?? ""}:${source.event_count}`).join("|") ?? null;
  useEffect(() => {
    if (signature === null) return;
    if (seen.current !== null && seen.current !== signature) void client.invalidateQueries({ queryKey: ["events"] });
    seen.current = signature;
  }, [signature, client]);
}

export function useNote(id: number) {
  return useQuery({ queryKey: ["note", id], queryFn: () => getNote(id), enabled: isId(id), retry: retryNetworkOnce });
}

function useInvalidating<TArgs, TResult>(run: (args: TArgs) => Promise<TResult>, keys: readonly string[]) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: async () => {
      await Promise.all(keys.map((key) => client.invalidateQueries({ queryKey: [key] })));
    },
  });
}

// Each write refreshes what it can have changed and nothing else. A delete must NOT refresh its own
// detail query: the screen showing it would refetch a trade that no longer exists and log a 404.
export const useCreateTrade = () => useInvalidating((body: TradeCreate) => createTrade(body), ["trades", "month", "tags"]);
export const useUpdateTrade = () => useInvalidating((args: { id: number; body: TradeUpdate }) => updateTrade(args.id, args.body), ["trades", "trade", "month", "tags"]);
export const useDeleteTrade = () => useInvalidating((id: number) => deleteTrade(id), ["trades", "month", "tags"]);

export const useCreateNote = () => useInvalidating((body: NoteCreate) => createNote(body), ["notes"]);
export const useUpdateNote = () => useInvalidating((args: { id: number; body: { day?: string; body?: string } }) => updateNote(args.id, args.body), ["notes", "note"]);
export const useDeleteNote = () => useInvalidating((id: number) => deleteNote(id), ["notes"]);

// Asking for a sync changes nothing the screens show until the feed finishes: the feed status starts being watched,
// and the events follow when it ends (see useRefreshEventsOnSync).
export const useSync = () => useInvalidating((sources?: SourceName[]) => requestSync(sources), ["sources"]);
