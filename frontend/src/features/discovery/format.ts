/** "3 Nov" from an ISO week-start date (the date is a calendar day, so it is read as UTC). */
export function weekLabel(isoDate: string): string {
  const date = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDate;
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/** "+4 pts" / "−3 pts" from a share difference (0.04 -> +4 percentage points). */
export function pointsChange(change: number): string {
  const points = Math.round(change * 100);
  return `${points > 0 ? "+" : points < 0 ? "−" : "±"}${Math.abs(points)} pts`;
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}
