/**
 * The story's charts, drawn from the facts' own checked numbers. One thing is emphasised
 * (the group or period the sentence is about, in the accent; a standout period in amber),
 * the rest is grey context. Marks are thin, gridlines are hairlines, values are labelled
 * sparingly, and every chart has a table view, so no value is reachable only by hovering.
 */
import { type PointerEvent, type RefObject, useEffect, useId, useMemo, useRef, useState } from "react";
import styles from "./storyteller.module.css";
import { type Chart, type ChartPoint, compact, type Format, formatValue } from "./types";

/** The plot's own width in CSS pixels, so text keeps its size on a phone and a wide screen. */
function useWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(([entry]) => {
      const w = Math.round(entry?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  return [ref, width];
}

/** Value labels at one precision per chart: whole numbers once the values reach the thousands. */
function labeller(chart: Chart): (v: number | null | undefined) => string {
  const big = chart.points.some((p) => Math.abs(p.value) >= 1000);
  const whole = big && chart.format === "number";
  return (v) => formatValue(whole && v != null ? Math.round(v) : v, chart.format, chart.unit);
}

interface Tip {
  x: number;
  y: number;
  title: string;
  lines: string[];
}

function Tooltip({ tip }: { tip: Tip | null }) {
  if (!tip) return null;
  return (
    <div className={styles.tooltip} style={{ left: tip.x, top: tip.y }} role="status" aria-live="polite">
      {tip.lines.map((line) => (
        <strong key={line}>{line}</strong>
      ))}
      <span>{tip.title}</span>
    </div>
  );
}

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(max));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (m * step >= max) return m * step;
  }
  return 10 * step;
}

/** Labels for the x axis that never collide: last, first, highlighted, then evenly between. */
function axisLabels(points: ChartPoint[], x: (i: number) => number): Set<number> {
  const half = (i: number) => ((points[i]?.label.length ?? 0) * 6.6 + 12) / 2; // 12px tabular text
  const last = points.length - 1;
  const wanted = [last, 0, ...points.flatMap((p, i) => (p.highlight ? [i] : []))];
  const step = Math.max(1, Math.round(points.length / 12));
  for (let i = step; i < last; i += step) wanted.push(i);
  const shown = new Set<number>();
  for (const i of wanted) {
    if ([...shown].every((j) => Math.abs(x(i) - x(j)) >= half(i) + half(j))) shown.add(i);
  }
  return shown;
}

// ---- line --------------------------------------------------------------------------------

function LineChart({ chart }: { chart: Chart }) {
  const { points, format, unit } = chart;
  const [plot, W] = useWidth();
  const H = Math.round(Math.min(260, Math.max(180, W * 0.36)));
  const pad = { l: 44, r: 64, t: 18, b: 30 };
  const label = labeller(chart);
  const values = points.map((p) => p.value);
  const low = Math.min(0, ...values);
  const high = niceMax(Math.max(...values));
  const x = (i: number) => pad.l + (points.length < 2 ? 0 : (i / (points.length - 1)) * (W - pad.l - pad.r));
  const y = (v: number) => pad.t + (1 - (v - low) / (high - low || 1)) * (H - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => low + t * (high - low));
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = `${path} L${x(points.length - 1)},${y(Math.max(low, 0))} L${x(0)},${y(Math.max(low, 0))} Z`;
  const labels = axisLabels(points, x);
  const last = points.length - 1;
  const [active, setActive] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);

  const pick = (e: PointerEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    const px = ((e.clientX - box.left) / box.width) * W;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    });
    setActive(best);
  };
  const shown = active === null ? null : points[active];

  return (
    <div ref={plot} className={styles.plot}>
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        role="img"
        aria-label={`${chart.title}: from ${formatValue(points[0]?.value, format, unit)} in ${points[0]?.label} to ${formatValue(points[last]?.value, format, unit)} in ${points[last]?.label}. The table view lists every value.`}
        onPointerMove={pick}
        onPointerLeave={() => setActive(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line className={styles.grid} x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} />
            <text className={styles.tick} x={pad.l - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
              {compact(t, format)}
            </text>
          </g>
        ))}
        <path d={area} className={styles.area} />
        <path d={path} className={styles.line} />
        {points.map((p, i) =>
          labels.has(i) ? (
            <text key={p.label} className={styles.tick} x={x(i)} y={H - 8} textAnchor="middle">
              {p.label}
            </text>
          ) : null,
        )}
        {points.map((p, i) =>
          p.highlight ? (
            <g key={`h-${p.label}`}>
              <circle className={styles.highlightDot} cx={x(i)} cy={y(p.value)} r={5.5} />
              <text className={styles.valueLabel} x={x(i)} y={y(p.value) - 12} textAnchor="middle">
                {label(p.value)}
              </text>
            </g>
          ) : null,
        )}
        {points[last] && !points[last]?.highlight && (
          <g>
            <circle className={styles.endDot} cx={x(last)} cy={y(points[last].value)} r={4.5} />
            <text
              className={styles.valueLabel}
              x={x(last) + 10}
              y={y(points[last].value)}
              dominantBaseline="middle"
            >
              {label(points[last].value)}
            </text>
          </g>
        )}
        {shown && active !== null && (
          <g pointerEvents="none">
            <line className={styles.crosshair} x1={x(active)} x2={x(active)} y1={pad.t} y2={H - pad.b} />
            <circle className={styles.endDot} cx={x(active)} cy={y(shown.value)} r={4.5} />
          </g>
        )}
      </svg>
      <Tooltip
        tip={
          shown && active !== null
            ? {
                x: x(active),
                y: y(shown.value) - 8,
                title: shown.label,
                lines: [formatValue(shown.value, format, unit)],
              }
            : null
        }
      />
    </div>
  );
}

// ---- bars --------------------------------------------------------------------------------

function BarsChart({ chart }: { chart: Chart }) {
  const [plot, W] = useWidth();
  const { points } = chart;
  const label = labeller(chart);
  const row = 32;
  const labelW = Math.min(170, Math.round(W * 0.32));
  const valueW = 76;
  const H = points.length * row + 8;
  const max = Math.max(...points.map((p) => Math.abs(p.value)), 1e-9);
  const width = (v: number) => (Math.abs(v) / max) * (W - labelW - valueW);
  const room = Math.floor(labelW / 7.5); // characters that fit beside the bar
  return (
    <div ref={plot} className={styles.plot}>
      <svg viewBox={`0 0 ${W} ${H}`} className={styles.svg} role="img" aria-label={`${chart.title}, as bars`}>
        {points.map((p, i) => {
          const top = i * row + 6;
          const w = Math.max(width(p.value), 8); // room for the rounded end
          return (
            <g key={p.label}>
              <text
                className={styles.rowLabel}
                x={labelW - 10}
                y={top + 10}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {p.label.length > room ? `${p.label.slice(0, room - 1)}…` : p.label}
              </text>
              <path
                className={p.highlight ? styles.barStrong : styles.bar}
                d={`M${labelW},${top} h${w - 4} a4,4 0 0 1 4,4 v12 a4,4 0 0 1 -4,4 h${-(w - 4)} Z`}
              />
              <text className={styles.valueLabel} x={labelW + w + 8} y={top + 10} dominantBaseline="middle">
                {label(p.value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ---- dumbbell ----------------------------------------------------------------------------

function DumbbellChart({ chart }: { chart: Chart }) {
  const { points, format } = chart;
  const [plot, W] = useWidth();
  const label = labeller(chart);
  const stacked = W < 440; // a narrow plot puts each label above its row, not beside it
  const row = stacked ? 54 : 36;
  const labelW = stacked ? 0 : Math.min(150, Math.round(W * 0.28));
  const pad = stacked ? 56 : 70; // room for the values outside the dots
  const H = points.length * row + 26;
  const all = points.flatMap((p) => [p.value, p.before ?? p.value]);
  const low = Math.min(0, ...all);
  const high = niceMax(Math.max(...all));
  const x = (v: number) => labelW + pad + ((v - low) / (high - low || 1)) * (W - labelW - 2 * pad);

  return (
    <div ref={plot} className={styles.plot}>
      <div className={styles.legend}>
        <span>
          <span className={styles.keyHollow} aria-hidden="true" /> {chart.before_label ?? "Before"}
        </span>
        <span>
          <span className={styles.keySolid} aria-hidden="true" /> {chart.after_label ?? "After"}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.svg}
        role="img"
        aria-label={`${chart.title}, before and after`}
      >
        {[0, 0.5, 1].map((t) => {
          const v = low + t * (high - low);
          return (
            <g key={t}>
              <line className={styles.grid} x1={x(v)} x2={x(v)} y1={4} y2={H - 22} />
              <text className={styles.tick} x={x(v)} y={H - 6} textAnchor="middle">
                {compact(v, format)}
              </text>
            </g>
          );
        })}
        {points.map((p, i) => {
          const cy = i * row + (stacked ? 38 : 20);
          const from = p.before ?? p.value;
          const tone = p.highlight ? styles.strong : styles.soft;
          const up = p.value >= from;
          return (
            <g key={p.label} className={tone}>
              <text
                className={styles.rowLabel}
                x={stacked ? 0 : labelW - 12}
                y={stacked ? cy - 20 : cy}
                textAnchor={stacked ? "start" : "end"}
                dominantBaseline="middle"
              >
                {p.label}
              </text>
              <line className={styles.stem} x1={x(from)} x2={x(p.value)} y1={cy} y2={cy} />
              <circle className={styles.hollow} cx={x(from)} cy={cy} r={5} />
              <circle className={styles.solid} cx={x(p.value)} cy={cy} r={5.5} />
              {p.before != null && (
                <text
                  className={styles.tick}
                  x={x(from) + (up ? -11 : 11)}
                  y={cy}
                  textAnchor={up ? "end" : "start"}
                  dominantBaseline="middle"
                >
                  {label(from)}
                </text>
              )}
              <text
                className={styles.valueLabel}
                x={x(p.value) + (up ? 12 : -12)}
                y={cy}
                textAnchor={up ? "start" : "end"}
                dominantBaseline="middle"
              >
                {label(p.value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ---- meter -------------------------------------------------------------------------------

function Meter({ chart }: { chart: Chart }) {
  const p = chart.points[0];
  if (!p) return null;
  const share = Math.max(0, Math.min(1, p.value));
  return (
    <div className={styles.meter}>
      <p className={styles.meterValue}>{formatValue(p.value, "percent")}</p>
      <meter className="visually-hidden" min={0} max={1} value={share} aria-label={p.label}>
        {formatValue(p.value, "percent")}
      </meter>
      <div className={styles.track} aria-hidden="true">
        <span style={{ width: `${share * 100}%` }} />
      </div>
      <p className="body-m muted">{p.label}</p>
    </div>
  );
}

// ---- the figure --------------------------------------------------------------------------

function TableView({ chart }: { chart: Chart }) {
  const dumbbell = chart.kind === "dumbbell";
  const show = (v: number | null | undefined) => formatValue(v, chart.format as Format, chart.unit);
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">{chart.kind === "line" ? "Period" : "Group"}</th>
          {dumbbell && <th scope="col">{chart.before_label ?? "Before"}</th>}
          <th scope="col">{dumbbell ? (chart.after_label ?? "After") : "Value"}</th>
        </tr>
      </thead>
      <tbody>
        {chart.points.map((p) => (
          <tr key={p.label} data-highlight={p.highlight || undefined}>
            <th scope="row">{p.label}</th>
            {dumbbell && <td>{show(p.before)}</td>}
            <td>{chart.kind === "meter" ? formatValue(p.value, "percent") : show(p.value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const DRAW = { line: LineChart, bars: BarsChart, dumbbell: DumbbellChart, meter: Meter } as const;

export function ChartFigure({ chart, onFact }: { chart: Chart; onFact: (id: string) => void }) {
  const [table, setTable] = useState(false);
  const id = useId();
  const Draw = DRAW[chart.kind];
  const body = useMemo(
    () => (table ? <TableView chart={chart} /> : <Draw chart={chart} />),
    [table, chart, Draw],
  );
  return (
    <figure className={styles.figure} aria-labelledby={id}>
      <figcaption className={styles.figHead}>
        <span id={id} className="title-m">
          {chart.title}
        </span>
        <span className={styles.figActions}>
          <button type="button" className={styles.link} onClick={() => setTable((t) => !t)}>
            {table ? "Show the chart" : "Show as a table"}
          </button>
          <button type="button" className={styles.link} onClick={() => onFact(chart.fact_id)}>
            How it was computed
          </button>
        </span>
      </figcaption>
      {body}
      {chart.note && <p className={`body-s muted ${styles.note}`}>{chart.note}</p>}
    </figure>
  );
}
