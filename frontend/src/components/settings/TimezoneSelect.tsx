"use client";

import { useSyncExternalStore } from "react";
import type { Locale, TranslationKey } from "@/i18n/types";
import {
  SYSTEM_TIMEZONE_VALUE,
  formatBrowserTimezoneHint,
  formatGeneralTimezoneLabel,
  getBrowserTimezone,
  getGeneralTimezoneOptions,
} from "@/lib/timezones";

type Props = {
  id?: string;
  name?: string;
  timezone: string;
  followSystem: boolean;
  onChange: (next: { timezone: string; followSystem: boolean }) => void;
  locale: Locale;
  systemLabel: string;
  t: (key: TranslationKey, params?: Record<string, string>) => string;
  className?: string;
  style?: React.CSSProperties;
  title?: string;
  disabled?: boolean;
};

const subscribeToHydration = () => () => {};
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

export default function TimezoneSelect({
  id,
  name,
  timezone,
  followSystem,
  onChange,
  locale,
  systemLabel,
  t,
  className,
  style,
  title,
  disabled,
}: Props) {
  // El HTML inicial debe ser idéntico aunque servidor y navegador tengan
  // versiones distintas de Intl, otra zona local o cambie el horario de verano.
  const hydrated = useSyncExternalStore(
    subscribeToHydration,
    getClientSnapshot,
    getServerSnapshot,
  );
  const options = getGeneralTimezoneOptions(
    followSystem ? [] : [timezone].filter(Boolean),
  );
  const selected = followSystem ? SYSTEM_TIMEZONE_VALUE : timezone;
  const systemLabelText = hydrated
    ? systemLabel.replace("{hint}", formatBrowserTimezoneHint(locale))
    : systemLabel.replace(/\s*\(\{hint\}\)/, "");

  return (
    <select
      id={id}
      name={name}
      value={selected}
      title={title}
      disabled={disabled}
      onChange={(e) => {
        const v = e.target.value;
        if (v === SYSTEM_TIMEZONE_VALUE) {
          onChange({ timezone: getBrowserTimezone(), followSystem: true });
        } else {
          onChange({ timezone: v, followSystem: false });
        }
      }}
      className={className}
      style={style}
    >
      <option value={SYSTEM_TIMEZONE_VALUE}>
        {systemLabelText}
      </option>
      {options.map(({ value, labelKey }) => {
        const label = labelKey ? t(labelKey) : value.replace(/_/g, " ");
        return (
          <option key={value} value={value}>
            {hydrated ? formatGeneralTimezoneLabel(value, locale, label) : label}
          </option>
        );
      })}
    </select>
  );
}
