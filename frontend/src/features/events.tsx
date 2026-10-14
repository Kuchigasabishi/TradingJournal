import { type Href, useLocalSearchParams, usePathname, useRouter } from "expo-router";
import type { ReactNode } from "react";
import { Linking, Pressable, StyleSheet, View } from "react-native";

import type { EventItem } from "../api/client";
import { useEvents, useRefreshEventsOnSync } from "../api/queries";
import {
  DEFAULT_EVENT_FILTERS,
  type EventFilters,
  type FilterImpact,
  IMPACT_LEVELS,
  IMPACT_NAME,
  applyEventFilters,
  currenciesOf,
  eventQuery,
  eventTimeText,
  groupByDay,
  isFiltered,
  isNews,
  parseEventFilters,
  safeHttpUrl,
} from "../lib/events";
import { useServer } from "../state/providers";
import { colors, radius, space } from "../theme";
import { Button, type PressState, Segmented } from "../ui/controls";
import { ErrorState, LoadingState } from "../ui/feedback";
import { ImpactGlyph, PersonalMark } from "../ui/impact";
import { Card, SectionHeader } from "../ui/layout";
import { AppText } from "../ui/text";
import { first, messageOf } from "./common";

/**
 * The event filters, kept in the address bar like the trade list's: a filtered view can be linked, reloaded and tested.
 * Changing a filter replaces the address (no history entry per click) and keeps the rest of it, such as the month. The
 * address is written the same way the links to a day write it (impact=high&impact=medium), not as the router would write
 * a list, so a view reads the same however it was reached.
 */
export function useEventFilters(): { filters: EventFilters; apply: (next: EventFilters) => void } {
  const params = useLocalSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const filters = parseEventFilters(params);
  const apply = (next: EventFilters) => {
    const month = first(params.month);
    const query = eventQuery(next);
    router.replace((month ? `${pathname}?month=${encodeURIComponent(month)}${query.replace("?", "&")}` : `${pathname}${query}`) as Href);
  };
  return { filters, apply };
}

function FilterChip({ label, selected, onPress, testID, glyph }: { label: string; selected: boolean; onPress: () => void; testID: string; glyph?: ReactNode }) {
  return (
    <Pressable
      role="button"
      aria-pressed={selected}
      aria-label={label}
      testID={testID}
      onPress={onPress}
      style={({ hovered, focused }: PressState) => [styles.chip, selected && styles.chipSelected, !selected && hovered && styles.chipHover, focused && styles.focused]}
    >
      {glyph}
      <AppText variant="small" tone={selected ? "inverse" : "primary"}>
        {label}
      </AppText>
    </Pressable>
  );
}

type FilterBarProps = {
  filters: EventFilters;
  onChange: (next: EventFilters) => void;
  /** Currencies the news in view mentions: the choices for the currency filter. */
  currencies: readonly string[];
  /** Whether the events in view include any news: without news, impact and currency have nothing to narrow. */
  hasNews: boolean;
};

/** Which events to show: everything, only news or only the personal calendar, and for news the impact levels and one currency. */
export function EventFilterBar({ filters, onChange, currencies, hasNews }: FilterBarProps) {
  const toggleImpact = (level: FilterImpact) => {
    const chosen = filters.impacts.includes(level) ? filters.impacts.filter((item) => item !== level) : [...filters.impacts, level];
    onChange({ ...filters, impacts: IMPACT_LEVELS.filter((item) => chosen.includes(item)) });
  };
  const narrowsNews = filters.show !== "personal" && hasNews;
  return (
    <View style={styles.bar} testID="event-filters" role="group" aria-label="Event filters">
      <Segmented
        label="Show"
        value={filters.show}
        onChange={(show) => onChange({ ...filters, show })}
        testID="filter-show"
        options={[
          { value: "all", label: "All events", testID: "filter-show-all" },
          { value: "news", label: "News", testID: "filter-show-news" },
          { value: "personal", label: "Personal", testID: "filter-show-personal" },
        ]}
      />
      {narrowsNews ? (
        <View style={styles.group} role="group" aria-label="News impact">
          <AppText variant="label" tone="secondary">
            Impact
          </AppText>
          {IMPACT_LEVELS.map((level) => (
            <FilterChip key={level} label={IMPACT_NAME[level]} selected={filters.impacts.includes(level)} onPress={() => toggleImpact(level)} testID={`filter-impact-${level}`} glyph={<ImpactGlyph impact={level} />} />
          ))}
        </View>
      ) : null}
      {narrowsNews && currencies.length > 0 ? (
        <View style={styles.group} role="group" aria-label="News currency">
          <AppText variant="label" tone="secondary">
            Currency
          </AppText>
          <FilterChip label="All" selected={filters.currency === undefined} onPress={() => onChange({ ...filters, currency: undefined })} testID="filter-currency-all" />
          {currencies.map((code) => (
            <FilterChip key={code} label={code} selected={filters.currency === code} onPress={() => onChange({ ...filters, currency: filters.currency === code ? undefined : code })} testID={`filter-currency-${code}`} />
          ))}
        </View>
      ) : null}
      {isFiltered(filters) ? <Button label="Clear filters" small variant="ghost" onPress={() => onChange(DEFAULT_EVENT_FILTERS)} testID="filter-clear" /> : null}
    </View>
  );
}

function DetailsLink({ url, label, testID }: { url: string; label: string; testID: string }) {
  return (
    <Pressable role="link" aria-label={label} testID={testID} onPress={() => void Linking.openURL(url)} style={({ focused }: PressState) => (focused ? styles.focused : undefined)}>
      <AppText variant="small" tone="secondary" style={styles.linkText}>
        Details ↗
      </AppText>
    </Pressable>
  );
}

/** One event of the day: when, what kind (impact for news, a ring for the personal calendar), whom it concerns, and what it is. */
function EventRow({ event, timeZone }: { event: EventItem; timeZone: string }) {
  const news = isNews(event);
  const url = safeHttpUrl(event.url);
  const impact = event.impact ?? "unknown";
  const figures = [event.forecast ? `Forecast ${event.forecast}` : null, event.previous ? `Previous ${event.previous}` : null].filter(Boolean).join(" · ");
  return (
    <View style={styles.row} testID={`event-${event.id}`} role="listitem">
      <AppText variant="small" numeric style={styles.time} testID={`event-time-${event.id}`}>
        {eventTimeText(event, timeZone)}
      </AppText>
      <View style={styles.kind}>
        {news ? (
          <>
            <ImpactGlyph impact={impact} />
            <AppText variant="small" testID={`event-impact-${event.id}`}>
              {IMPACT_NAME[impact]}
            </AppText>
          </>
        ) : (
          <>
            <PersonalMark />
            <AppText variant="small" testID={`event-kind-${event.id}`}>
              Calendar
            </AppText>
          </>
        )}
      </View>
      {news ? (
        <AppText variant="label" style={styles.currency} testID={`event-currency-${event.id}`}>
          {event.currency ?? ""}
        </AppText>
      ) : (
        <View style={styles.currency} />
      )}
      <View style={styles.main}>
        <AppText testID={`event-title-${event.id}`}>{event.title}</AppText>
        {event.location ? (
          <AppText variant="tiny" tone="secondary" testID={`event-location-${event.id}`}>
            {event.location}
          </AppText>
        ) : null}
        {event.description ? (
          <AppText variant="small" tone="secondary" numberOfLines={3} testID={`event-description-${event.id}`}>
            {event.description}
          </AppText>
        ) : null}
      </View>
      {figures ? (
        <AppText variant="tiny" tone="secondary" style={styles.figures} testID={`event-figures-${event.id}`}>
          {figures}
        </AppText>
      ) : null}
      {url ? <DetailsLink url={url} label={`Details of ${event.title}`} testID={`event-link-${event.id}`} /> : null}
    </View>
  );
}

function EventSection({ title, testID, events, timeZone }: { title: string; testID: string; events: readonly EventItem[]; timeZone: string }) {
  return (
    <View style={styles.section} testID={testID}>
      <AppText variant="h3" role="heading" testID={`${testID}-heading`}>
        {title}
      </AppText>
      <View role="list" aria-label={title}>
        {events.map((event) => (
          <EventRow key={event.id} event={event} timeZone={timeZone} />
        ))}
      </View>
    </View>
  );
}

/** Everything outside the journal that happens on one day: the economic news first, then the owner's calendar, in the server's zone. */
export function DayEventsCard({ date }: { date: string }) {
  const { timezone } = useServer();
  const { filters, apply } = useEventFilters();
  const events = useEvents({ from: date, to: date });
  useRefreshEventsOnSync();

  const all = events.data?.items ?? [];
  const shown = groupByDay(applyEventFilters(all, filters), date, date).get(date) ?? [];
  const news = shown.filter(isNews);
  const personal = shown.filter((event) => !isNews(event));

  return (
    <Card testID="day-events">
      <View style={styles.card}>
        <SectionHeader title="Events" />
        <AppText variant="tiny" tone="secondary" testID="day-events-zone">
          Times are in {timezone}.
        </AppText>
        {events.isPending ? (
          <LoadingState label="Loading events…" testID="day-events-loading" />
        ) : events.isError ? (
          <ErrorState title="Could not load the events" detail={messageOf(events.error)} onRetry={() => void events.refetch()} testID="day-events-error" retryTestID="day-events-retry" />
        ) : all.length === 0 ? (
          <AppText tone="secondary" testID="day-events-empty">
            No events on this day.
          </AppText>
        ) : (
          <>
            <EventFilterBar filters={filters} onChange={apply} currencies={currenciesOf(all)} hasNews={all.some(isNews)} />
            {shown.length === 0 ? (
              <AppText tone="secondary" testID="day-events-none-match">
                No events match these filters.
              </AppText>
            ) : null}
            {personal.length > 0 ? <EventSection title={`Calendar · ${personal.length}`} testID="day-events-personal" events={personal} timeZone={timezone} /> : null}
            {news.length > 0 ? <EventSection title={`Economic news · ${news.length}`} testID="day-events-news" events={news} timeZone={timezone} /> : null}
          </>
        )}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: space.md },
  bar: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.md },
  group: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.xs, maxWidth: "100%" },
  chip: { flexDirection: "row", alignItems: "center", gap: space.xs, minHeight: 28, paddingVertical: 3, paddingHorizontal: space.sm, borderRadius: radius.pill, backgroundColor: colors.sunken },
  chipSelected: { backgroundColor: colors.ink },
  chipHover: { backgroundColor: colors.hairline },
  focused: { outlineColor: colors.focus, outlineWidth: 2, outlineStyle: "solid", outlineOffset: 1 },
  section: { gap: space.xs },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "flex-start", columnGap: space.md, rowGap: space.xs, paddingVertical: space.sm, borderBottomWidth: 1, borderBottomColor: colors.grid },
  time: { width: 96, flexShrink: 0 },
  kind: { flexDirection: "row", alignItems: "center", gap: space.xs, width: 96, flexShrink: 0 },
  currency: { width: 40, flexShrink: 0 },
  main: { flexGrow: 1, flexBasis: 220, flexShrink: 1, gap: 2 },
  figures: { width: 190, flexShrink: 0 },
  linkText: { textDecorationLine: "underline" },
});
