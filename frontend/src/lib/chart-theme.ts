"use client";

import { useEffect, useState } from "react";

/**
 * Theme-aware colors for recharts. Reads the DataScope CSS tokens from
 * getComputedStyle so charts adapt when the `.light` class flips on <html>,
 * instead of hardcoding dark-only hex values. A MutationObserver keeps the
 * palette live across theme toggles.
 */

export interface ChartTheme {
  accent: string;
  accentStrong: string;
  muted: string;
  grid: string;
  background: string;
  border: string;
  ticks: string;
  tooltipCursor: string;
  onAccent: string;
  palette: string[];
}

const DARK_PALETTE = [
  "#818cf8",
  "#34d399",
  "#f472b6",
  "#fbbf24",
  "#60a5fa",
  "#a78bfa",
  "#f87171",
  "#2dd4bf",
];

const LIGHT_PALETTE = [
  "#4f46e5",
  "#059669",
  "#db2777",
  "#d97706",
  "#2563eb",
  "#7c3aed",
  "#dc2626",
  "#0d9488",
];

function isLight(): boolean {
  return (
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("light")
  );
}

function readVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

function readTheme(): ChartTheme {
  const light = isLight();
  return {
    accent: readVar("--color-accent", light ? "#4f46e5" : "#6366f1"),
    accentStrong: readVar(
      "--color-accent-strong",
      light ? "#4338ca" : "#818cf8"
    ),
    muted: readVar("--color-text-muted", light ? "#6b6b74" : "#8b8b94"),
    grid: light ? "#e4e4e9" : "#1f1f1f",
    background: readVar(
      "--color-bg-secondary",
      light ? "#f5f5f7" : "#0f0f13"
    ),
    border: readVar("--color-border", light ? "#e4e4e9" : "#26262f"),
    ticks: light ? "#6b6b74" : "#888888",
    tooltipCursor: light
      ? "rgba(17,17,20,0.06)"
      : "rgba(250,250,250,0.06)",
    onAccent: light ? "#111114" : "#fafafa",
    palette: light ? LIGHT_PALETTE : DARK_PALETTE,
  };
}

export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(readTheme);

  useEffect(() => {
    const apply = () => setTheme(readTheme());
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    window.addEventListener("datascope-theme-change", apply);
    return () => {
      observer.disconnect();
      window.removeEventListener("datascope-theme-change", apply);
    };
  }, []);

  return theme;
}
