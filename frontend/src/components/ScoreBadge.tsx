interface ScoreBadgeProps {
  score: number;
  label?: string;
  size?: "sm" | "md";
}

export default function ScoreBadge({ score, label, size = "md" }: ScoreBadgeProps) {
  const color =
    score >= 75 ? "bg-emerald-100 text-emerald-800" :
    score >= 50 ? "bg-amber-100 text-amber-800" :
    "bg-red-100 text-red-800";

  const sz = size === "sm" ? "text-xs px-1.5 py-0.5" : "text-sm px-2 py-1";

  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-medium ${color} ${sz}`}>
      {label && <span className="opacity-70">{label}</span>}
      {Math.round(score)}
    </span>
  );
}
