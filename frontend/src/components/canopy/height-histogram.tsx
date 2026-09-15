import { useMemo } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/** 2 m bins, so the chart never implies more precision than a shadow measurement has. */
const BIN_M = 2;

export function HeightHistogram({ heights }: { heights: number[] }) {
  const data = useMemo(() => {
    if (!heights.length) return [];
    const max = Math.max(...heights);
    const bins = Math.max(1, Math.ceil(max / BIN_M));
    const counts = new Array(bins).fill(0);
    for (const h of heights) counts[Math.min(bins - 1, Math.floor(h / BIN_M))]++;
    return counts.map((count, i) => ({ label: `${i * BIN_M}–${(i + 1) * BIN_M}`, count }));
  }, [heights]);

  return (
    <div className="h-[120px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: -28 }}>
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }} />
          <Tooltip
            cursor={{ fill: "var(--color-chart-cursor)" }}
            contentStyle={{
              background: "var(--color-background-primary-default)",
              border: "1px solid var(--color-border-button-default)",
              borderRadius: 10,
              fontSize: 12,
            }}
            labelStyle={{ color: "var(--color-text-secondary)" }}
            itemStyle={{ color: "var(--color-text-primary)" }}
            labelFormatter={(l) => `${l} m`}
            formatter={(v) => [`${v} crowns`, ""]}
            separator=""
          />
          <Bar dataKey="count" fill="var(--color-canopy)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
