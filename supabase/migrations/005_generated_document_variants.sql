alter table public.generated_documents
  add column if not exists theme_id text,
  add column if not exists variant_key text,
  add column if not exists variant_label text,
  add column if not exists variant_group_id uuid;

create index if not exists idx_generated_documents_variant_group
  on public.generated_documents(variant_group_id)
  where variant_group_id is not null;
