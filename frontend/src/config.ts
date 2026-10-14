/** Build-time settings. Expo inlines EXPO_PUBLIC_* values when the app is built. */

/** Empty means same origin, which is how the web build is served in verification and production. Native builds and `expo start` need a full URL. */
export const API_BASE_URL: string = process.env.EXPO_PUBLIC_API_URL ?? "";

/** The account currency P&L is shown in. The journal keeps one account, so this is a display setting. */
export const ACCOUNT_CURRENCY: string = (process.env.EXPO_PUBLIC_ACCOUNT_CURRENCY ?? "USD").toUpperCase();

export const PAGE_SIZE = 25;
