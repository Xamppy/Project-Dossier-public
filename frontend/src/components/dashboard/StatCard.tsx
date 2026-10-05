import { useId } from "react";

type StatCardProps = {
  value: string | number;
  label: string;
  trend?: string;
  trendVariant?: "default" | "positive" | "warning";
  /** Líneas auxiliares bajo el rótulo (periodo, conteos, causa de un estado). */
  details?: string[];
  /** Explicación para lectores de pantalla; no se muestra en pantalla. */
  description?: string;
  /** Mientras carga: lo anuncia como ocupado. */
  busy?: boolean;
};

export default function StatCard({
  value,
  label,
  trend,
  trendVariant = "default",
  details,
  description,
  busy,
}: StatCardProps) {
  const uid = useId();
  const labelId = `${uid}-label`;
  const descId = `${uid}-desc`;
  const trendColor =
    trendVariant === "positive"
      ? "var(--status-success)"
      : trendVariant === "warning"
      ? "var(--status-warning)"
      : "var(--text-muted)";

  return (
    <div
      role="group"
      aria-labelledby={labelId}
      aria-describedby={description ? descId : undefined}
      aria-busy={busy ? true : undefined}
      className="flex min-w-0 flex-col gap-2 rounded-xl border p-5"
      style={{
        borderColor: "var(--border-default)",
        backgroundImage:
          "linear-gradient(180deg, var(--bg-card-start) 0%, var(--bg-card-end) 100%)",
      }}
    >
      <span
        className="text-3xl font-bold tracking-tight"
        style={{ color: "var(--text-primary)" }}
      >
        {value}
      </span>
      <span id={labelId} className="text-sm" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      {details?.map((line) => (
        <span key={line} className="text-xs leading-snug" style={{ color: "var(--text-muted)" }}>
          {line}
        </span>
      ))}
      {trend && (
        <span className="text-xs font-medium" style={{ color: trendColor }}>
          {trend}
        </span>
      )}
      {description ? (
        <span id={descId} className="sr-only">
          {description}
        </span>
      ) : null}
    </div>
  );
}
