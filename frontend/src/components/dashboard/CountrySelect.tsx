"use client";

import type { Locale } from "@/i18n/types";
import { getCountryOptions } from "@/lib/countries";

type CountrySelectProps = {
  label: string;
  name: string;
  placeholder: string;
  value: string;
  locale: Locale;
  onChange: (countryCode: string) => void;
  disabled?: boolean;
};

export default function CountrySelect({
  label,
  name,
  placeholder,
  value,
  locale,
  onChange,
  disabled,
}: CountrySelectProps) {
  const id = name;
  const countries = getCountryOptions(locale);

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={id}
        className="text-sm font-medium"
        style={{ color: "var(--text-secondary)" }}
      >
        {label}
      </label>
      <select
        id={id}
        name={name}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="w-full rounded-lg border py-2.5 text-sm outline-none transition focus:ring-2 px-3.5"
        style={{
          backgroundColor: "var(--bg-input)",
          borderColor: "var(--border-default)",
          color: "var(--text-primary)",
        }}
      >
        <option value="">{placeholder}</option>
        {countries.map(({ code, label: countryLabel }) => (
          <option key={code} value={code}>
            {countryLabel}
          </option>
        ))}
      </select>
    </div>
  );
}
