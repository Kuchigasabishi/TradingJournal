import { usePathname, type Href } from "expo-router";
import type { ReactNode } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { useHealth } from "../api/queries";
import { useFlash } from "../state/providers";
import { colors, radius, space, useLayout } from "../theme";
import { LinkButton, PressableLink } from "../ui/controls";
import { Banner } from "../ui/feedback";
import { ErrorIcon } from "../ui/status";
import { AppText } from "../ui/text";

function NavLink({ href, label, active, testID }: { href: Href; label: string; active: boolean; testID: string }) {
  return (
    <PressableLink
      href={href}
      testID={testID}
      role="link"
      aria-label={label}
      aria-current={active ? "page" : undefined}
      style={({ hovered, focused }) => [styles.navLink, active && styles.navLinkActive, hovered && !active && styles.navLinkHover, focused && styles.navLinkFocus]}
    >
      <AppText variant="label" tone={active ? "primary" : "secondary"}>
        {label}
      </AppText>
    </PressableLink>
  );
}

/** Liveness of the API, checked every 30 seconds. Press it to check right now. */
function StatusChip() {
  const health = useHealth();
  const offline = health.isError;
  const label = health.isPending ? "Checking API…" : offline ? "API offline" : "API online";
  return (
    <Pressable testID="api-status" role="button" aria-label={`${label}. Press to check again.`} onPress={() => void health.refetch()} style={styles.chip}>
      {offline ? <ErrorIcon /> : <View style={[styles.dot, health.isPending && styles.dotPending]} />}
      <AppText variant="small" tone={offline ? "critical" : "secondary"} testID="api-status-label">
        {label}
      </AppText>
    </Pressable>
  );
}

function Header() {
  const pathname = usePathname();
  const { narrow } = useLayout();
  const section = pathname === "/" ? "dashboard" : pathname.startsWith("/calendar") || pathname.startsWith("/day") ? "calendar" : pathname.startsWith("/trades") || pathname.startsWith("/notes") ? "trades" : "";
  return (
    <View style={styles.header} role="banner">
      <View style={[styles.headerInner, narrow && styles.headerNarrow]}>
        <PressableLink href="/" testID="nav-brand" role="link" aria-label="Trading Journal home" style={({ focused }) => (focused ? styles.navLinkFocus : undefined)}>
          <AppText variant="h3">Trading Journal</AppText>
        </PressableLink>
        <View style={styles.nav} role="navigation" aria-label="Main">
          <NavLink href="/" label="Dashboard" active={section === "dashboard"} testID="nav-dashboard" />
          <NavLink href="/calendar" label="Calendar" active={section === "calendar"} testID="nav-calendar" />
          <NavLink href="/trades" label="Trades" active={section === "trades"} testID="nav-trades" />
        </View>
        <View style={styles.actions}>
          <StatusChip />
          <LinkButton href="/trades/new" label="New trade" variant="primary" small testID="nav-new-trade" />
        </View>
      </View>
    </View>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { flash, clear } = useFlash();
  return (
    <View style={styles.root} testID="app-shell">
      <Header />
      {flash ? (
        <View style={styles.flash}>
          <Banner kind={flash.kind} message={flash.message} testID="flash-message" onDismiss={clear} />
        </View>
      ) : null}
      <View style={styles.content} testID="app-ready">
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.page },
  header: { backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.hairline, alignItems: "center" },
  headerInner: { width: "100%", maxWidth: 1180, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.lg, paddingHorizontal: space.lg, paddingVertical: space.md },
  headerNarrow: { flexWrap: "wrap" },
  nav: { flexDirection: "row", gap: space.xs },
  navLink: { paddingVertical: space.sm, paddingHorizontal: space.md, borderRadius: radius.md },
  navLinkActive: { backgroundColor: colors.sunken },
  navLinkHover: { backgroundColor: colors.hairline },
  navLinkFocus: { outlineColor: colors.focus, outlineWidth: 2, outlineStyle: "solid", outlineOffset: 1 },
  actions: { flexDirection: "row", alignItems: "center", gap: space.md },
  chip: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: space.xs, paddingHorizontal: space.sm },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.inkSecondary },
  dotPending: { backgroundColor: colors.baseline },
  flash: { alignItems: "center", paddingHorizontal: space.lg, paddingTop: space.md },
  content: { flex: 1 },
});
