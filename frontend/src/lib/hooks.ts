"use client";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { toApiParams } from "./filters";
import { useFilterStore } from "./store";
import type * as T from "./types";

const base = { placeholderData: keepPreviousData, staleTime: 30_000 } as const;

export function useApiFilters() {
  return toApiParams(useFilterStore((s) => s.filters));
}

/** Query bound to the global filters (they are part of the cache key). */
export function useFiltered<R>(key: string, path: string, extra?: Record<string, string | number | undefined>, enabled = true) {
  const f = useApiFilters();
  return useQuery({
    queryKey: [key, path, f, extra],
    queryFn: () => api<R>(path, { ...f, ...extra }),
    enabled,
    ...base,
  });
}

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<T.Me>("/auth/me"), staleTime: 300_000, retry: false });
export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: () => api<T.MetaResp>("/meta/filters"), staleTime: 120_000 });

export const useOverview = () => useFiltered<T.OverviewResp>("overview", "/analytics/overview");
export const useBreakdown = (by: string) => useFiltered<T.BreakdownResp>("breakdown", "/analytics/breakdown", { by });
export const useTimeseries = (granularity: string) => useFiltered<T.TimeseriesResp>("ts", "/analytics/timeseries", { granularity });
export const useCompare = (mode: string, anchor?: string, enabled = true) =>
  useFiltered<T.CompareResp>("compare", "/analytics/compare", { mode, anchor }, enabled);
export const useQuality = (by: "client" | "project") => useFiltered<T.QualityResp>("quality", "/analytics/quality", { by });
export const useAlerts = () => useFiltered<{ alerts: T.Alert[]; anchor: string }>("alerts", "/analytics/alerts");
export const useEditors = () => useFiltered<T.EditorsResp>("editors", "/people/editors");
export const useEditorDetail = (id: number | undefined, granularity: string) =>
  useFiltered<T.EditorDetail>("editor", `/people/editors/${id}`, { granularity }, id != null);
export const useQc = () => useFiltered<T.QcResp>("qc", "/people/qc");
export const useEscSummary = () => useFiltered<T.EscSummary>("esc-sum", "/escalations/summary");
export const useFormsCompare = (vs: "previous" | "yoy", enabled = true) =>
  useFiltered<T.FormsCompareResp>("forms-compare", "/analytics/forms-compare", { vs }, enabled);
export const useMonthDrivers = (metric: string) => useFiltered<T.MonthDriversResp>("month-drivers", "/analytics/month-drivers", { metric });
export const useFormsMonths = (metric: string, enabled = true) =>
  useFiltered<T.FormsMonthsResp>("forms-months", "/analytics/forms-months", { metric }, enabled);
export const useWeekGrid = (metric: string) => useFiltered<T.WeekGridResp>("week-grid", "/analytics/week-grid", { metric });
export interface DriverQuery { metric: string; cur: [string, string]; prev: [string, string]; projectId?: number }
export const useChangeDrivers = (q: DriverQuery, enabled: boolean) =>
  useFiltered<T.ChangeDriversResp>("change-drivers", "/analytics/change-drivers", {
    metric: q.metric, cur_from: q.cur[0], cur_to: q.cur[1], prev_from: q.prev[0], prev_to: q.prev[1],
    ...(q.projectId != null ? { project_id: q.projectId } : {}),
  }, enabled);
