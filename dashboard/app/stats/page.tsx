import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border rounded p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
    </div>
  );
}

export default async function StatsPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: listings, error } = await supabase
    .from("listings")
    .select("source, judge_result, match_pct, status");

  if (error) {
    return <main className="p-8">Failed to load stats: {error.message}</main>;
  }

  const rows = listings ?? [];
  const total = rows.length;
  const approved = rows.filter((r) => r.judge_result).length;
  const scored = rows.filter((r) => r.match_pct !== null);
  const avgMatch = scored.length
    ? Math.round(scored.reduce((sum, r) => sum + (r.match_pct ?? 0), 0) / scored.length)
    : null;

  const bySource = rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.source] = (acc[r.source] ?? 0) + 1;
    return acc;
  }, {});

  const byStatus = rows.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <main className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Stats</h1>
        <Link href="/" className="text-sm underline">
          Volver a listings
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <StatTile label="Total scrapeados" value={total} />
        <StatTile label="Aprobados por Jev" value={`${approved} (${total ? Math.round((approved / total) * 100) : 0}%)`} />
        <StatTile label="Scoreados por DeepSeek" value={scored.length} />
        <StatTile label="Match % promedio" value={avgMatch ?? "-"} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
        <div>
          <h2 className="font-semibold mb-2">Por fuente</h2>
          <table className="w-full text-left border-collapse">
            <tbody>
              {Object.entries(bySource).map(([key, count]) => (
                <tr key={key} className="border-b">
                  <td className="p-2">{key}</td>
                  <td className="p-2">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h2 className="font-semibold mb-2">Por status</h2>
          <table className="w-full text-left border-collapse">
            <tbody>
              {Object.entries(byStatus).map(([key, count]) => (
                <tr key={key} className="border-b">
                  <td className="p-2">{key}</td>
                  <td className="p-2">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
