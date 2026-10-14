import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import { getReady } from "../api/endpoints";
import { ApiError } from "../api/client";
import { colors } from "../theme";
import { ErrorState, LoadingState } from "../ui/feedback";

/** One QueryClient for the app's lifetime. */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: true } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

export type FlashKind = "success" | "error" | "info";
type FlashState = { kind: FlashKind; message: string };
type FlashApi = { flash: FlashState | null; show: (message: string, kind?: FlashKind) => void; clear: () => void };

const FlashContext = createContext<FlashApi | null>(null);

/** A message that survives a navigation ("Trade saved") and clears itself after a few seconds. */
export function FlashProvider({ children }: { children: ReactNode }) {
  const [flash, setFlash] = useState<FlashState | null>(null);
  useEffect(() => {
    if (flash === null) return;
    const timer = setTimeout(() => setFlash(null), 6_000);
    return () => clearTimeout(timer);
  }, [flash]);
  const api: FlashApi = { flash, show: (message, kind = "success") => setFlash({ kind, message }), clear: () => setFlash(null) };
  return <FlashContext.Provider value={api}>{children}</FlashContext.Provider>;
}

export function useFlash(): FlashApi {
  const api = useContext(FlashContext);
  if (api === null) throw new Error("useFlash needs a FlashProvider");
  return api;
}

export type ServerInfo = { timezone: string; migration: string };
const ServerContext = createContext<ServerInfo | null>(null);

/**
 * Asks /api/ready once before anything renders. The answer carries the time zone the server buckets days
 * in, which every screen needs to format and parse times, and it shows up front when the API is down.
 */
export function ServerProvider({ children }: { children: ReactNode }) {
  const ready = useQuery({ queryKey: ["ready"], queryFn: getReady, retry: false, staleTime: 60_000 });
  if (ready.isPending) {
    return (
      <View style={styles.boot}>
        <LoadingState label="Connecting to the journal server…" testID="boot-loading" />
      </View>
    );
  }
  if (ready.isError) {
    const detail = ready.error instanceof ApiError ? "The server is up but not ready. Check its logs." : "Start the API server, then retry.";
    return (
      <View style={styles.boot}>
        <ErrorState title="Cannot reach the journal server" detail={detail} onRetry={() => void ready.refetch()} testID="boot-error" retryTestID="boot-retry" />
      </View>
    );
  }
  return <ServerContext.Provider value={{ timezone: ready.data.timezone, migration: ready.data.migration }}>{children}</ServerContext.Provider>;
}

export function useServer(): ServerInfo {
  const info = useContext(ServerContext);
  if (info === null) throw new Error("useServer needs a ServerProvider");
  return info;
}

const styles = StyleSheet.create({
  boot: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.page },
});
