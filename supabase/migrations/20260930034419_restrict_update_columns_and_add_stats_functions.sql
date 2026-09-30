-- Post-review hardening: the UPDATE RLS policy scopes rows to their owner,
-- but the default table-level GRANT UPDATE covers every column - a client
-- could change source/id/match_pct/etc. on their own row, not just the two
-- columns the dashboard is meant to let them edit.
revoke update on listings from authenticated, anon;
grant update (status, user_notes) on listings to authenticated;

-- Post-review fix: the dashboard was fetching all rows client-side to
-- compute stats, which silently truncates at PostgREST's row cap once the
-- table grows past it. Aggregate server-side instead.
create function listing_stats()
returns table (total bigint, approved bigint, scored bigint, avg_match numeric)
language sql
security invoker
stable
as $$
  select
    count(*) as total,
    count(*) filter (where judge_result) as approved,
    count(*) filter (where match_pct is not null) as scored,
    avg(match_pct) as avg_match
  from listings
$$;

create function listing_counts_by_source()
returns table (source text, count bigint)
language sql
security invoker
stable
as $$
  select source, count(*) from listings group by source
$$;

create function listing_counts_by_status()
returns table (status text, count bigint)
language sql
security invoker
stable
as $$
  select status, count(*) from listings group by status
$$;
