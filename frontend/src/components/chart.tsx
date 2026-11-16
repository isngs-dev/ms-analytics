"use client";
import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { DatasetComponent, GraphicComponent, GridComponent, LegendComponent, TooltipComponent, MarkLineComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { useTheme } from "./theme";
import { cn } from "@/lib/utils";

echarts.use([BarChart, LineChart, PieChart, DatasetComponent, GraphicComponent, GridComponent, LegendComponent,
  TooltipComponent, MarkLineComponent, CanvasRenderer]);

/** Colour-blind-safe categorical palette that also reads on dark and light backgrounds. */
// Green family for volume / progress, red for problems, amber and slate as quiet extras.
export const PALETTE = ["#3fc47e", "#ff6b73", "#9be8bb", "#f0b040", "#1f9d5a", "#8aa397"];
export const COLORS = { received: "#3fc47e", edited: "#9be8bb", qc: "#2bb5a0", pending: "#f0b040", bad: "#ff6b73", finalised: "#1f9d5a" };

/** Pseudo-3D fill: light top-left to full colour, so bars read as lit solids rather than flat blocks. */
export function solid(color: string, horizontal = true) {
  return {
    type: "linear" as const, x: 0, y: 0, x2: horizontal ? 1 : 0, y2: horizontal ? 0 : 1,
    colorStops: [{ offset: 0, color: color + "66" }, { offset: 0.35, color }, { offset: 1, color: color + "cc" }],
  };
}
export const DEPTH = { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.35)", shadowOffsetX: 3, shadowOffsetY: 4 };

export function useChartColors() {
  const { theme } = useTheme();
  return useMemo(
    () => ({
      text: theme === "dark" ? "#a9bdb2" : "#4b5f55",
      grid: theme === "dark" ? "rgba(160,190,175,0.16)" : "rgba(60,90,75,0.14)",
      tipBg: theme === "dark" ? "#13201a" : "#ffffff",
      tipText: theme === "dark" ? "#e6f1ea" : "#112018",
    }),
    [theme],
  );
}

export function Chart({
  option, height = 280, onPointClick, className, ariaLabel,
}: {
  option: EChartsOption; height?: number; className?: string; ariaLabel: string;
  onPointClick?: (p: { name: string; dataIndex: number; seriesName?: string }) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const c = useChartColors();
  const click = useRef(onPointClick);
  click.current = onPointClick;

  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    inst.current = chart;
    chart.on("click", (p) => click.current?.({ name: String(p.name), dataIndex: p.dataIndex, seriesName: p.seriesName }));
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.dispose(); inst.current = null; };
  }, []);

  useEffect(() => {
    inst.current?.setOption(
      {
        color: PALETTE,
        textStyle: { color: c.text },
        animationDuration: 500,
        tooltip: { backgroundColor: c.tipBg, borderColor: c.grid, textStyle: { color: c.tipText }, confine: true },
        legend: { textStyle: { color: c.text }, type: "scroll", top: 0 },
        ...option,
      },
      true,
    );
  }, [option, c]);

  return <div ref={el} role="img" aria-label={ariaLabel} className={cn("w-full", className)} style={{ height }} />;
}

/** Shared axis styling. */
export function axes(c: ReturnType<typeof useChartColors>) {
  return {
    axisLine: { lineStyle: { color: c.grid } },
    axisLabel: { color: c.text },
    splitLine: { lineStyle: { color: c.grid } },
  };
}
