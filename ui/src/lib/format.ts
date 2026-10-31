const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** "2 minutes ago", "yesterday"... */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), "hour");
  return relative.format(Math.round(seconds / 86400), "day");
}

/** 0.4 -> "0.4 s", 75 -> "1 min 15 s". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 0.1) return "under 0.1 s";
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m} min ${s} s` : `${m} min`;
}

export function secondsBetween(start: string | null | undefined, end?: string | null): number | null {
  if (!start) return null;
  const stop = end ? new Date(end).getTime() : Date.now();
  return Math.max(0, (stop - new Date(start).getTime()) / 1000);
}

export function ordinal(n: number): string {
  const rules = new Intl.PluralRules("en", { type: "ordinal" });
  const suffix = { one: "st", two: "nd", few: "rd", other: "th", zero: "th", many: "th" }[rules.select(n)];
  return `${n}${suffix}`;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

export function download(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 1234567 -> "1.2 MB" */
export function fileSize(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let n = bytes / 1000;
  let unit = 0;
  while (n >= 1000 && unit < units.length - 1) {
    n /= 1000;
    unit += 1;
  }
  return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${units[unit]}`;
}
