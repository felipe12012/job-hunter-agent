import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import ListingsTable, { type Listing } from "@/components/ListingsTable";

const PAGE_SIZE = 1000;

async function fetchAllListings(
  supabase: Awaited<ReturnType<typeof createClient>>
): Promise<{ listings: Listing[]; error: string | null }> {
  // PostgREST caps a single response at PAGE_SIZE rows - a plain .select()
  // silently truncates once the table grows past it, so page through.
  const all: Listing[] = [];
  let from = 0;
  while (true) {
    const { data, error } = await supabase
      .from("listings")
      .select("source, id, title, company, url, match_pct, notified, reasoning, draft_message, created_at, status, user_notes")
      .order("created_at", { ascending: false })
      .range(from, from + PAGE_SIZE - 1);

    if (error) {
      return { listings: all, error: error.message };
    }
    all.push(...(data ?? []));
    if (!data || data.length < PAGE_SIZE) {
      return { listings: all, error: null };
    }
    from += PAGE_SIZE;
  }
}

export default async function Home() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { listings, error } = await fetchAllListings(supabase);

  if (error) {
    return <main className="p-8">Failed to load listings: {error}</main>;
  }

  return (
    <main className="p-8">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">job-hunter-agent</h1>
        <Link href="/stats" className="text-sm underline">
          Ver stats
        </Link>
      </div>
      <ListingsTable listings={listings ?? []} />
    </main>
  );
}
