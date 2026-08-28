import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import type { EvidenceQuery, ForecastQuery } from "@/lib/api/types";

/**
 * Query keys and hooks.
 *
 * `retry: false` everywhere is deliberate. The three error classes are all
 * things retrying cannot fix — an unimplemented endpoint, a contract violation,
 * a permission refusal — and silently retrying turns a clear "unavailable" into
 * a spinner that never resolves.
 */

const common = { retry: false, staleTime: 60_000 } as const;

export const queryKeys = {
  snapshot: ["snapshot"] as const,
  districts: ["districts"] as const,
  forecasts: (query: ForecastQuery) => ["forecasts", query] as const,
  forecast: (id: string) => ["forecast", id] as const,
  history: (districtId: string, family: string) => ["history", districtId, family] as const,
  contributions: (id: string) => ["contributions", id] as const,
  evidence: (query: EvidenceQuery) => ["evidence", query] as const,
  evidenceItem: (id: string) => ["evidence-item", id] as const,
  reviewTasks: ["review-tasks"] as const,
  reviewTask: (id: string) => ["review-task", id] as const,
  backtests: ["backtests"] as const,
  backtest: (id: string) => ["backtest", id] as const,
  dataHealth: ["data-health"] as const,
  models: ["models"] as const,
  lineage: (id: string) => ["lineage", id] as const,
};

export const useSnapshot = () =>
  useQuery({ queryKey: queryKeys.snapshot, queryFn: () => apiClient.getSnapshot(), ...common });

export const useDistricts = () =>
  useQuery({ queryKey: queryKeys.districts, queryFn: () => apiClient.listDistricts(), ...common });

export const useForecasts = (query: ForecastQuery) =>
  useQuery({ queryKey: queryKeys.forecasts(query), queryFn: () => apiClient.listForecasts(query), ...common });

export const useForecast = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.forecast(id ?? ""),
    queryFn: () => apiClient.getForecast(id!),
    enabled: !!id,
    ...common,
  });

export const useForecastHistory = (districtId: string | undefined, family: string | undefined) =>
  useQuery({
    queryKey: queryKeys.history(districtId ?? "", family ?? ""),
    queryFn: () => apiClient.getForecastHistory(districtId!, family!),
    enabled: !!districtId && !!family,
    ...common,
  });

export const useContributions = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.contributions(id ?? ""),
    queryFn: () => apiClient.getContributions(id!),
    enabled: !!id,
    ...common,
  });

export const useEvidence = (query: EvidenceQuery) =>
  useQuery({ queryKey: queryKeys.evidence(query), queryFn: () => apiClient.listEvidence(query), ...common });

export const useEvidenceItem = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.evidenceItem(id ?? ""),
    queryFn: () => apiClient.getEvidenceItem(id!),
    enabled: !!id,
    ...common,
  });

export const useReviewTasks = () =>
  useQuery({ queryKey: queryKeys.reviewTasks, queryFn: () => apiClient.listReviewTasks(), ...common });

export const useReviewTask = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.reviewTask(id ?? ""),
    queryFn: () => apiClient.getReviewTask(id!),
    enabled: !!id,
    ...common,
  });

export const useBacktestRuns = () =>
  useQuery({ queryKey: queryKeys.backtests, queryFn: () => apiClient.listBacktestRuns(), ...common });

export const useBacktestRun = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.backtest(id ?? ""),
    queryFn: () => apiClient.getBacktestRun(id!),
    enabled: !!id,
    ...common,
  });

export const useDataHealth = () =>
  useQuery({ queryKey: queryKeys.dataHealth, queryFn: () => apiClient.getDataHealth(), ...common });

export const useModelArtifacts = () =>
  useQuery({ queryKey: queryKeys.models, queryFn: () => apiClient.listModelArtifacts(), ...common });

export const useRunLineage = (id: string | undefined) =>
  useQuery({
    queryKey: queryKeys.lineage(id ?? ""),
    queryFn: () => apiClient.getRunLineage(id!),
    enabled: !!id,
    ...common,
  });
