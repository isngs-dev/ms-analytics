"use client";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { Chart, COLORS, DEPTH, PALETTE, axes, solid, useChartColors } from "./chart";
import { fmtBucket, fmtInt } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

export const SERIES: Record<string, { label: string; color: string }> = {
  received: { label: "Received", color: COLORS.received },
  edited: { label: "Edited", color: COLORS.edited },
  finalised: { label: "Finalised", color: COLORS.finalised },
  qc_completed: { label: "QC completed", color: COLORS.qc },
  pending_editing: { label: "Pending editing", color: COLORS.pending },
  qc_pending: { label: "QC pending", color: "#8aa397" },
  processed: { label: "Processed", color: COLORS.edited },
};

export function TrendChart({
  points, granularity, keys = ["received", "edited", "qc_completed"], height = 300, bars = false, onClickBucket,
}: {
  points: SeriesPoint[]; granularity: string; keys?: (keyof SeriesPoint)[]; height?: number; bars?: boolean;
  onClickBucket?: (bucket: string) => void;
}) {
  const c = useChartColors();
  const option = useMemo<EChartsOption>(() => ({
    grid: { left: 8, right: 12, top: 36, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: points.map((p) => fmtBucket(p.bucket, granularity)), ...axes(c), splitLine: { show: false }, boundaryGap: bars },
    yAxis: { type: "value", ...axes(c) },
    series: keys.map((k) => ({
      name: SERIES[k as string].label, type: bars ? "bar" : "line", smooth: !bars && granularity !== "day", showSymbol: points.length < 40,
      symbolSize: 6, data: points.map((p) => p[k] as number), color: SERIES[k as string].color,
      areaStyle: bars ? undefined : { opacity: 0.10 },
      lineStyle: { width: 3, shadowBlur: 10, shadowColor: SERIES[k as string].color, shadowOffsetY: 6 },
      itemStyle: bars ? { color: solid(SERIES[k as string].color, false), borderRadius: [5, 5, 0, 0], ...DEPTH } : undefined,
      barMaxWidth: 22,
    })),
  }), [points, granularity, keys, bars, c]);
  const total = keys.map((k) => `${SERIES[k as string].label} ${fmtInt(points.reduce((a, p) => a + (p[k] as number), 0))}`).join(", ");
  return <Chart option={option} height={height} ariaLabel={`Trend by ${granularity}: ${total}`}
    onPointClick={onClickBucket ? (p) => onClickBucket(points[p.dataIndex].bucket) : undefined} />;
}

export interface BarRow { name: string; id?: number | null; values: Record<string, number> }

/** Horizontal ranking bars (names are long); stacked or grouped. */
export function RankBars({
  rows, keys, stacked = false, height, onClick, limit = 15,
}: {
  rows: BarRow[]; keys: string[]; stacked?: boolean; height?: number; limit?: number;
  onClick?: (row: BarRow) => void;
}) {
  const c = useChartColors();
  const data = rows.slice(0, limit);
  const h = height ?? Math.max(180, data.length * (stacked ? 30 : 22 * keys.length) + 56);
  const option = useMemo<EChartsOption>(() => ({
    legend: { show: keys.length > 1 },
    grid: { left: 8, right: 24, top: keys.length > 1 ? 32 : 8, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "value", ...axes(c) },
    yAxis: { type: "category", inverse: true, data: data.map((r) => r.name), axisLabel: { color: c.text, width: 120, overflow: "truncate" }, axisLine: { lineStyle: { color: c.grid } } },
    series: keys.map((k) => ({
      name: SERIES[k]?.label ?? k, type: "bar", stack: stacked ? "s" : undefined, barMaxWidth: 18,
      data: data.map((r) => r.values[k] ?? 0), color: SERIES[k]?.color,
      itemStyle: { color: solid(SERIES[k]?.color ?? PALETTE[0]), borderRadius: stacked ? 0 : [0, 6, 6, 0], ...DEPTH },
    })),
  }), [data, keys, stacked, c]);
  return <Chart option={option} height={h} ariaLabel={`Ranking of ${data.length} items by ${keys.map((k) => SERIES[k]?.label ?? k).join(", ")}`}
    onPointClick={onClick ? (p) => onClick(data[p.dataIndex]) : undefined} />;
}

export function Donut({
  data, height = 260, centerLabel, onClick,
}: { data: { name: string; value: number; color: string }[]; height?: number; centerLabel?: string; onClick?: (name: string) => void }) {
  const c = useChartColors();
  const option = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, top: undefined, textStyle: { color: c.text } },
    series: [{
      type: "pie", radius: ["55%", "78%"], center: ["50%", "44%"], avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: c.tipBg, borderWidth: 2 }, label: { show: false },
      data: data.map((d) => ({ name: d.name, value: d.value, itemStyle: { color: d.color } })),
    }],
    graphic: centerLabel ? [{ type: "text", left: "center", top: "38%", style: { text: centerLabel, fill: c.tipText, font: "600 22px system-ui", textAlign: "center" } }] : undefined,
  }), [data, centerLabel, c]);
  return <Chart option={option} height={height} ariaLabel={`Distribution: ${data.map((d) => `${d.name} ${d.value}`).join(", ")}`}
    onPointClick={onClick ? (p) => onClick(p.name) : undefined} />;
}
