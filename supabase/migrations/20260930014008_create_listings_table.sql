create table listings (
  source text not null,
  id text not null,
  title text not null,
  company text,
  url text not null,
  description text,
  judge_result boolean not null,
  match_pct integer,
  reasoning text,
  draft_message text,
  notified boolean not null default false,
  created_at timestamptz not null default now(),
  user_id uuid not null,
  primary key (source, id)
);

alter table listings enable row level security;

create policy "users read their own listings"
  on listings for select
  using (auth.uid() = user_id);
