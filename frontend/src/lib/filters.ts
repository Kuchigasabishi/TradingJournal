/** Trade-list filters as a URL: the address bar is the state, so a filtered view can be linked, reloaded and tested. */

export type TradeSort = "journal_at" | "opened_at" | "closed_at" | "pnl";

export type TradeFilters = {
  status?: "open" | "closed";
  instrument?: string;
  side?: "long" | "short";
  tags: string[];
  from?: string;
  to?: string;
  sort: TradeSort;
  order: "asc" | "desc";
  page: number; // 1-based
};

export const DEFAULT_FILTERS: TradeFilters = { tags: [], sort: "journal_at", order: "desc", page: 1 };

export type Params = Record<string, string | string[] | undefined>;

const first = (value: string | string[] | undefined): string | undefined => (Array.isArray(value) ? value[0] : value);
// The router writes several values of one parameter as a single comma-joined value (tag=a%2Cb) and reads a hand-written
// ?tag=a&tag=b as a list, so a list parameter is split on commas whichever way it arrived. Tags cannot contain commas.
const list = (value: string | string[] | undefined): string[] => (Array.isArray(value) ? value : value === undefined ? [] : [value]).flatMap((item) => item.split(","));
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function parseFilters(params: Params): TradeFilters {
  const status = first(params.status);
  const side = first(params.side);
  const sort = first(params.sort);
  const order = first(params.order);
  const from = first(params.from);
  const to = first(params.to);
  const page = Number(first(params.page));
  const instrument = first(params.instrument)?.trim();
  const filters: TradeFilters = {
    tags: list(params.tag).filter(Boolean),
    sort: sort === "opened_at" || sort === "closed_at" || sort === "pnl" ? sort : "journal_at",
    order: order === "asc" ? "asc" : "desc",
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
  // Unset filters are left out entirely, so an empty address equals DEFAULT_FILTERS.
  if (status === "open" || status === "closed") filters.status = status;
  if (instrument) filters.instrument = instrument;
  if (side === "long" || side === "short") filters.side = side;
  if (from && DAY.test(from)) filters.from = from;
  if (to && DAY.test(to)) filters.to = to;
  return filters;
}

/** The URL parameters for a filter set. Defaults are omitted so addresses stay short. */
export function toParams(filters: TradeFilters): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  if (filters.status) params.status = filters.status;
  if (filters.instrument) params.instrument = filters.instrument;
  if (filters.side) params.side = filters.side;
  if (filters.tags.length > 0) params.tag = filters.tags;
  if (filters.from) params.from = filters.from;
  if (filters.to) params.to = filters.to;
  if (filters.sort !== DEFAULT_FILTERS.sort) params.sort = filters.sort;
  if (filters.order !== DEFAULT_FILTERS.order) params.order = filters.order;
  if (filters.page > 1) params.page = String(filters.page);
  return params;
}

/** The query the API expects for one page of a filter set. */
export function toApiQuery(filters: TradeFilters, pageSize: number) {
  return {
    status: filters.status,
    instrument: filters.instrument,
    side: filters.side,
    tag: filters.tags.length > 0 ? filters.tags : undefined,
    from: filters.from,
    to: filters.to,
    sort: filters.sort,
    order: filters.order,
    limit: pageSize,
    offset: (filters.page - 1) * pageSize,
  };
}
