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
    .select("source, id, title, company, url, match_pct, notified, reasoning, draft_message, created_at")
    .order("created_at", { ascending: false });

  if (error) {
    return <main className="p-8">Failed to load listings: {error.message}</main>;
  }

  return (
    <main className="p-8">
      <h1 className="text-2xl font-semibold mb-4">job-hunter-agent</h1>
      <ListingsTable listings={listings ?? []} />
    </main>
  );
}
