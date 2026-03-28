alter table public.generated_documents
  add column if not exists source_sections jsonb,
  add column if not exists source_conversation_id uuid references public.conversations(id) on delete set null,
  add column if not exists superseded_at timestamptz,
  add column if not exists superseded_by_id uuid references public.generated_documents(id) on delete set null;

create index if not exists idx_generated_documents_active_variant
  on public.generated_documents(variant_group_id, variant_key, created_at desc)
  where superseded_at is null and variant_group_id is not null;

create index if not exists idx_generated_documents_active_user
  on public.generated_documents(user_id, created_at desc)
  where superseded_at is null;
