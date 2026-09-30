alter table listings
  add column status text not null default 'new'
    check (status in ('new','applied','interviewing','rejected','discarded')),
  add column user_notes text;

create policy "users update their own listings"
  on listings for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
