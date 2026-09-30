import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

type StatsRow = { total: number; approved: number; scored: number; avg_match: number | null };
type CountRow = { source?: string; status?: string; count: number };

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

  const [statsResult, bySourceResult, byStatusResult] = await Promise.all([
    supabase.rpc("listing_stats").single(),
    supabase.rpc("listing_counts_by_source"),
    supabase.rpc("listing_counts_by_status"),
  ]);

  if (statsResult.error || bySourceResult.error || byStatusResult.error) {
    const message =
      statsResult.error?.message ?? bySourceResult.error?.message ?? byStatusResult.error?.message;
    return <main className="p-8">Failed to load stats: {message}</main>;
  }

  // Aggregated server-side (via RPC functions) instead of fetching every row -
  // fetching all rows client-side silently truncates past PostgREST's row cap.
  const stats = statsResult.data as unknown as StatsRow | null;
  const bySourceRows = (bySourceResult.data ?? []) as unknown as CountRow[];
  const byStatusRows = (byStatusResult.data ?? []) as unknown as CountRow[];

  const total = Number(stats?.total ?? 0);
  const approved = Number(stats?.approved ?? 0);
  const scoredCount = Number(stats?.scored ?? 0);
  const avgMatch = stats?.avg_match !== null && stats?.avg_match !== undefined
    ? Math.round(Number(stats.avg_match))
    : null;

  const bySource = Object.fromEntries(bySourceRows.map((row) => [row.source as string, Number(row.count)]));
  const byStatus = Object.fromEntries(byStatusRows.map((row) => [row.status as string, Number(row.count)]));

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
        <StatTile label="Scoreados por DeepSeek" value={scoredCount} />
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
