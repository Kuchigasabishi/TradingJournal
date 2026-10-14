import { Link, type Href } from "expo-router";
import { useState, type ReactNode } from "react";
import { Pressable, StyleSheet, TextInput, View, type PressableProps, type PressableStateCallbackType, type StyleProp, type TextInputProps, type ViewStyle } from "react-native";

import { dedupeTags, normalizeTag } from "../lib/validation";
import { colors, radius, space } from "../theme";
import { ErrorText } from "./status";
import { AppText } from "./text";

// react-native-web adds hovered and focused to Pressable's state; native has only pressed.
export type PressState = PressableStateCallbackType & { hovered?: boolean; focused?: boolean };

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<ButtonVariant, { container: ViewStyle; hover: ViewStyle; text: string }> = {
  primary: { container: { backgroundColor: colors.ink, borderColor: colors.ink }, hover: { backgroundColor: "#2b2b2a" }, text: colors.white },
  secondary: { container: { backgroundColor: colors.surface, borderColor: colors.baseline }, hover: { backgroundColor: colors.sunken }, text: colors.ink },
  danger: { container: { backgroundColor: colors.surface, borderColor: colors.critical }, hover: { backgroundColor: colors.criticalWash }, text: colors.critical },
  ghost: { container: { backgroundColor: "transparent", borderColor: "transparent" }, hover: { backgroundColor: colors.sunken }, text: colors.ink },
};

function buttonStyle(variant: ButtonVariant, small: boolean, disabled: boolean) {
  return ({ pressed, hovered, focused }: PressState): StyleProp<ViewStyle> => [
    styles.button,
    small && styles.buttonSmall,
    VARIANTS[variant].container,
    (hovered || pressed) && !disabled && VARIANTS[variant].hover,
    focused && styles.focused,
    disabled && styles.disabled,
  ];
}

export function Button({
  label,
  onPress,
  variant = "secondary",
  disabled = false,
  loading = false,
  small = false,
  testID,
  ariaLabel,
}: {
  label: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  loading?: boolean;
  small?: boolean;
  testID?: string;
  /** The name read out for the button, when the visible label alone would be ambiguous ("Delete" in every table row). */
  ariaLabel?: string;
}) {
  const inactive = disabled || loading;
  return (
    <Pressable testID={testID} role="button" aria-label={ariaLabel ?? label} aria-disabled={inactive} disabled={inactive} onPress={onPress} style={buttonStyle(variant, small, inactive)}>
      <AppText variant="label" style={{ color: VARIANTS[variant].text }}>
        {loading ? "Working…" : label}
      </AppText>
    </Pressable>
  );
}

export type LinkState = { hovered: boolean; focused: boolean };

type PressableLinkProps = Omit<PressableProps, "style" | "children" | "onHoverIn" | "onHoverOut" | "onFocus" | "onBlur"> & {
  href: Href;
  style?: (state: LinkState) => StyleProp<ViewStyle>;
  children: ReactNode | ((state: LinkState) => ReactNode);
};

/**
 * A pressable that navigates. Every link in the app goes through here because expo-router's `<Link asChild>`
 * merges the child's `style` with an object spread: an array or a function there becomes {0: ...} in a
 * production build and crashes the page. This component tracks hover and focus itself and always hands
 * the child one flat style object.
 */
export function PressableLink({ href, style, children, ...rest }: PressableLinkProps) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const state: LinkState = { hovered, focused };
  return (
    <Link href={href} asChild>
      <Pressable
        {...rest}
        onHoverIn={() => setHovered(true)}
        onHoverOut={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={StyleSheet.flatten(style?.(state))}
      >
        {typeof children === "function" ? children(state) : children}
      </Pressable>
    </Link>
  );
}

export function LinkButton({ href, label, variant = "secondary", small = false, testID, ariaLabel }: { href: Href; label: string; variant?: ButtonVariant; small?: boolean; testID?: string; ariaLabel?: string }) {
  const style = buttonStyle(variant, small, false);
  return (
    <PressableLink href={href} testID={testID} role="link" aria-label={ariaLabel ?? label} style={({ hovered, focused }) => style({ pressed: false, hovered, focused })}>
      <AppText variant="label" style={{ color: VARIANTS[variant].text }}>
        {label}
      </AppText>
    </PressableLink>
  );
}

/** An in-text link: ink with an underline, so it reads as a link without borrowing a data color. */
export function TextLink({ href, label, testID, variant = "body" }: { href: Href; label: string; testID?: string; variant?: "body" | "small" | "label" }) {
  return (
    <PressableLink href={href} testID={testID} role="link" style={({ focused }) => (focused ? styles.focused : undefined)}>
      <AppText variant={variant} style={styles.linkText}>
        {label}
      </AppText>
    </PressableLink>
  );
}

/** Sizing for a field that shares a row with others: grows to fill, wraps when narrow. Stacked fields leave it off. */
export const rowField: ViewStyle = { flexGrow: 1, flexBasis: 220 };

type FieldProps = {
  label: string;
  style?: StyleProp<ViewStyle>;
  value: string;
  onChangeText: (text: string) => void;
  testID: string;
  error?: string;
  hint?: string;
  prefix?: string;
  multiline?: boolean;
  placeholder?: string;
  inputMode?: TextInputProps["inputMode"];
  autoCapitalize?: TextInputProps["autoCapitalize"];
  onSubmitEditing?: () => void;
  onBlur?: () => void;
};

export function TextField({ label, style, value, onChangeText, testID, error, hint, prefix, multiline, placeholder, inputMode, autoCapitalize = "none", onSubmitEditing, onBlur }: FieldProps) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={[styles.field, style]}>
      <AppText variant="label" tone="secondary">
        {label}
      </AppText>
      <View style={[styles.inputWrap, focused && styles.inputFocused, !!error && styles.inputError]}>
        {prefix ? (
          <AppText tone="secondary" style={styles.prefix}>
            {prefix}
          </AppText>
        ) : null}
        <TextInput
          testID={testID}
          aria-label={label}
          aria-invalid={!!error}
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.inkMuted}
          multiline={multiline}
          inputMode={inputMode}
          autoCapitalize={autoCapitalize}
          autoCorrect={false}
          onSubmitEditing={onSubmitEditing}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            onBlur?.();
          }}
          style={[styles.input, multiline && styles.multiline]}
        />
      </View>
      {error ? <ErrorText testID={`${testID}-error`}>{error}</ErrorText> : hint ? <AppText variant="tiny" tone="secondary">{hint}</AppText> : null}
    </View>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  testID,
}: {
  options: { value: T; label: string; testID: string }[];
  value: T;
  onChange: (value: T) => void;
  label?: string;
  testID?: string;
}) {
  return (
    <View role="radiogroup" aria-label={label} style={styles.segmented} testID={testID}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            role="radio"
            aria-checked={selected}
            aria-label={option.label}
            testID={option.testID}
            onPress={() => onChange(option.value)}
            style={({ hovered, focused }: PressState) => [styles.segment, selected && styles.segmentSelected, !selected && hovered && styles.segmentHover, focused && styles.focused]}
          >
            <AppText variant="label" tone={selected ? "inverse" : "primary"}>
              {option.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Toggle({ label, value, onChange, testID }: { label: string; value: boolean; onChange: (value: boolean) => void; testID: string }) {
  return (
    <Pressable role="switch" aria-checked={value} aria-label={label} testID={testID} onPress={() => onChange(!value)} style={({ focused }: PressState) => [styles.toggleRow, focused && styles.focused]}>
      <View style={[styles.track, value && styles.trackOn]}>
        <View style={[styles.thumb, value && styles.thumbOn]} />
      </View>
      <AppText variant="label">{label}</AppText>
    </Pressable>
  );
}

export function Chip({ label, selected = false, onPress, onRemove, testID, removeTestID }: { label: string; selected?: boolean; onPress?: () => void; onRemove?: () => void; testID?: string; removeTestID?: string }) {
  const body = (
    <View style={[styles.chip, selected && styles.chipSelected]}>
      <AppText variant="small" tone={selected ? "inverse" : "primary"}>
        {label}
      </AppText>
      {onRemove ? (
        <Pressable role="button" aria-label={`Remove ${label}`} testID={removeTestID} onPress={onRemove} hitSlop={8}>
          <AppText variant="small" tone={selected ? "inverse" : "secondary"}>
            ×
          </AppText>
        </Pressable>
      ) : null}
    </View>
  );
  if (!onPress) return <View testID={testID}>{body}</View>;
  return (
    <Pressable role="button" aria-pressed={selected} aria-label={label} testID={testID} onPress={onPress}>
      {body}
    </Pressable>
  );
}

export function TagEditor({ tags, onChange, suggestions, error, testID = "field-tags", style }: { tags: string[]; onChange: (tags: string[]) => void; suggestions: string[]; error?: string; testID?: string; style?: StyleProp<ViewStyle> }) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const tag = normalizeTag(raw);
    if (tag !== "") onChange(dedupeTags([...tags, tag]));
    setDraft("");
  };
  const unused = suggestions.filter((name) => !tags.some((tag) => tag.toLowerCase() === name.toLowerCase())).slice(0, 8);
  return (
    <View style={[styles.field, style]}>
      <AppText variant="label" tone="secondary">
        Tags
      </AppText>
      <View style={[styles.tagBox, !!error && styles.inputError]} testID={testID}>
        {tags.map((tag) => (
          <Chip key={tag} label={tag} onRemove={() => onChange(tags.filter((other) => other !== tag))} testID={`tag-chip-${tag}`} removeTestID={`tag-remove-${tag}`} />
        ))}
        <TextInput
          testID={`${testID}-input`}
          aria-label="Add a tag"
          value={draft}
          onChangeText={setDraft}
          onSubmitEditing={() => add(draft)}
          onBlur={() => add(draft)}
          blurOnSubmit={false}
          placeholder={tags.length === 0 ? "Add a tag, press Enter" : "Add another"}
          placeholderTextColor={colors.inkMuted}
          autoCapitalize="none"
          autoCorrect={false}
          style={styles.tagInput}
        />
      </View>
      {unused.length > 0 ? (
        <View style={styles.suggestions}>
          <AppText variant="tiny" tone="secondary">
            Used before:
          </AppText>
          {unused.map((name) => (
            <Chip key={name} label={name} onPress={() => add(name)} testID={`tag-suggest-${name}`} />
          ))}
        </View>
      ) : null}
      {error ? <ErrorText testID={`${testID}-error`}>{error}</ErrorText> : null}
    </View>
  );
}

/** A labelled value, for read-only detail views. */
export function Detail({ label, children, testID }: { label: string; children: ReactNode; testID?: string }) {
  return (
    <View style={styles.detail}>
      <AppText variant="small" tone="secondary">
        {label}
      </AppText>
      <View testID={testID}>{typeof children === "string" ? <AppText>{children}</AppText> : children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  button: { minHeight: 40, paddingHorizontal: space.lg, borderRadius: radius.md, borderWidth: 1, alignItems: "center", justifyContent: "center", flexDirection: "row" },
  buttonSmall: { minHeight: 32, paddingHorizontal: space.md },
  disabled: { opacity: 0.5 },
  linkText: { textDecorationLine: "underline" },
  focused: { outlineColor: colors.focus, outlineWidth: 2, outlineStyle: "solid", outlineOffset: 1 },
  field: { gap: space.xs },
  inputWrap: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.baseline, borderRadius: radius.md, paddingHorizontal: space.md },
  inputFocused: { borderColor: colors.focus },
  inputError: { borderColor: colors.critical },
  prefix: { marginRight: space.xs },
  input: { flex: 1, minHeight: 40, fontSize: 15, color: colors.ink, outlineStyle: "none" } as object,
  multiline: { minHeight: 96, paddingVertical: space.sm, textAlignVertical: "top" },
  segmented: { flexDirection: "row", borderWidth: 1, borderColor: colors.baseline, borderRadius: radius.md, overflow: "hidden", alignSelf: "flex-start" },
  segment: { minHeight: 38, paddingHorizontal: space.lg, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  segmentSelected: { backgroundColor: colors.ink },
  segmentHover: { backgroundColor: colors.sunken },
  toggleRow: { flexDirection: "row", alignItems: "center", gap: space.sm, alignSelf: "flex-start" },
  track: { width: 40, height: 24, borderRadius: 12, backgroundColor: colors.baseline, padding: 2, justifyContent: "center" },
  trackOn: { backgroundColor: colors.ink },
  thumb: { width: 20, height: 20, borderRadius: 10, backgroundColor: colors.white },
  thumbOn: { alignSelf: "flex-end" },
  chip: { flexDirection: "row", alignItems: "center", gap: space.xs, paddingVertical: 3, paddingHorizontal: space.sm, borderRadius: radius.pill, backgroundColor: colors.sunken },
  chipSelected: { backgroundColor: colors.ink },
  tagBox: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.xs, minHeight: 44, paddingHorizontal: space.sm, paddingVertical: space.xs, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.baseline, borderRadius: radius.md },
  tagInput: { flexGrow: 1, flexBasis: 120, minHeight: 32, fontSize: 15, color: colors.ink, outlineStyle: "none" } as object,
  suggestions: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.xs },
  detail: { gap: 2, minWidth: 140 },
});
