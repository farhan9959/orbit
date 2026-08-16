export type HealthLevel = "down" | "saturated" | "busy" | "moderate" | "idle";

export interface HealthEncoding {
  level: HealthLevel;
  label: string;
  colour: string;
  dash: number[];
  glyph: string;
}

const ENCODINGS: Record<HealthLevel, Omit<HealthEncoding, "level">> = {
  down: { label: "down", colour: "#f26a6a", dash: [2, 4], glyph: "✕" },
  saturated: { label: "saturated", colour: "#ffb347", dash: [], glyph: "▲" },
  busy: { label: "busy", colour: "#ffe08a", dash: [], glyph: "◆" },
  moderate: { label: "moderate", colour: "#7fd1ae", dash: [], glyph: "●" },
  idle: { label: "idle", colour: "#5b6b8c", dash: [], glyph: "·" },
};

export function linkHealth(utilisation: number, isDown: boolean): HealthEncoding {
  if (isDown) return { level: "down", ...ENCODINGS.down };
  if (utilisation >= 0.95) return { level: "saturated", ...ENCODINGS.saturated };
  if (utilisation >= 0.7) return { level: "busy", ...ENCODINGS.busy };
  if (utilisation > 0.01) return { level: "moderate", ...ENCODINGS.moderate };
  return { level: "idle", ...ENCODINGS.idle };
}

export function linkWidth(utilisation: number, isDown: boolean): number {
  if (isDown) return 1.5;
  return 1 + Math.min(1, Math.max(0, utilisation)) * 4;
}

export const PRIORITY_COLOUR: Record<string, string> = {
  CRITICAL: "#ff8fa3",
  HIGH: "#ffd166",
  NORMAL: "#8ecae6",
  LOW: "#a8dadc",
};

export const PRIORITY_GLYPH: Record<string, string> = {
  CRITICAL: "◆",
  HIGH: "▲",
  NORMAL: "●",
  LOW: "▪",
};
