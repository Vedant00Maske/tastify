"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * Single-series charts in the SONIQUEO palette: one hue (the accent), thin bars with rounded data
 * ends, a recessive grid, one axis, and a hover tooltip. Every chart is paired with a text
 * summary or table by its caller, so nothing is conveyed by the picture alone.
 */
const AXIS = { fontSize: 12, fill: "var(--color-fg-muted)" };

export interface ColumnDatum {
  key: string;
  value: number;
}

function ChartTooltip({
  active,
  payload,
  format,
}: {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
  format: (datum: ColumnDatum) => string;
}) {
  const datum = payload?.[0]?.payload as ColumnDatum | undefined;
  if (!active || !datum) return null;
  return (
    <div className="rounded-button border border-border bg-surface-elevated px-3 py-2 text-support shadow-elevated">
      {format(datum)}
    </div>
  );
}

export function ColumnChart({
  data,
  label,
  formatTick,
  formatTooltip,
  height = 200,
}: {
  data: ColumnDatum[];
  label: string;
  formatTick?: (key: string) => string;
  formatTooltip: (datum: ColumnDatum) => string;
  height?: number;
}) {
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 8, right: 4, bottom: 0, left: -16 }}
          barCategoryGap={2}
        >
          <CartesianGrid vertical={false} stroke="var(--color-border)" />
          <XAxis
            dataKey="key"
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            tickFormatter={formatTick}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={40}
          />
          <Tooltip
            cursor={{ fill: "var(--color-surface-hover)" }}
            content={(props) => (
              <ChartTooltip
                active={props.active}
                payload={props.payload}
                format={formatTooltip}
              />
            )}
          />
          <Bar
            dataKey="value"
            fill="var(--color-accent)"
            radius={[4, 4, 0, 0]}
            maxBarSize={28}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal share bars as plain HTML: readable labels at any width, no chart library needed. */
export function ShareBars({
  items,
  label,
  format = (v) => `${Math.round(v * 100)}%`,
}: {
  items: { key: string; label: string; value: number }[];
  label: string;
  format?: (value: number) => string;
}) {
  const max = Math.max(...items.map((i) => i.value), 1e-9);
  return (
    <ul aria-label={label} className="flex flex-col gap-2.5">
      {items.map((item) => (
        <li
          key={item.key}
          className="grid grid-cols-[minmax(0,9rem)_1fr_3rem] items-center gap-3"
        >
          <span className="truncate text-support capitalize" title={item.label}>
            {item.label}
          </span>
          <span className="h-2.5 overflow-hidden rounded-full bg-surface-hover">
            <span
              className="block h-full rounded-full bg-accent"
              style={{ width: `${Math.max((item.value / max) * 100, 2)}%` }}
            />
          </span>
          <span className="text-right text-meta text-fg-secondary tabular-nums">
            {format(item.value)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A headline number with its label (hero stats on the taste page). */
export function StatTile({
  value,
  label,
  hint,
}: {
  value: string;
  label: string;
  hint?: string;
}) {
  return (
    <div className="rounded-card bg-surface p-4 shadow-card">
      <p className="font-display text-page leading-none font-bold tabular-nums">
        {value}
      </p>
      <p className="mt-2 text-support font-semibold">{label}</p>
      {hint ? <p className="mt-0.5 text-meta text-fg-muted">{hint}</p> : null}
    </div>
  );
}
