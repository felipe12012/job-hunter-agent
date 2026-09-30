import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import ListingsTable from "@/components/ListingsTable";

export default async function Home() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: listings, error } = await supabase
    .from("listings")
    .select("source, id, title, company, url, match_pct, notified, reasoning, draft_message, created_at, status, user_notes")
    .order("created_at", { ascending: false });

  if (error) {
    return <main className="p-8">Failed to load listings: {error.message}</main>;
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
