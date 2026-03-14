-- Create profiles table (extends auth.users)
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text,
  email text,
  created_at timestamptz default now()
);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, full_name, email)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', ''),
    new.email
  );
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- User context (progressive profile)
create table public.user_context (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  category text not null,
  content jsonb not null default '{}',
  source_conversation_id uuid,
  updated_at timestamptz default now()
);

-- Conversations
create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  mode text not null check (mode in ('job_to_resume', 'find_jobs')),
  title text default 'New conversation',
  status text default 'active' check (status in ('active', 'completed')),
  created_at timestamptz default now()
);

-- Messages
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Jobs
create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  title text not null,
  company text,
  url text,
  description_md text,
  created_at timestamptz default now()
);

-- Generated documents
create table public.generated_documents (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  doc_type text not null check (doc_type in ('resume', 'cover_letter')),
  file_url text not null,
  created_at timestamptz default now()
);

-- Add FK from user_context to conversations
alter table public.user_context
  add constraint fk_user_context_conversation
  foreign key (source_conversation_id)
  references public.conversations(id) on delete set null;

-- Indexes
create index idx_user_context_user on public.user_context(user_id);
create index idx_conversations_user on public.conversations(user_id);
create index idx_messages_conversation on public.messages(conversation_id);
create index idx_jobs_conversation on public.jobs(conversation_id);
create index idx_generated_documents_job on public.generated_documents(job_id);
create index idx_generated_documents_user on public.generated_documents(user_id);

-- Enable RLS
alter table public.profiles enable row level security;
alter table public.user_context enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.jobs enable row level security;
alter table public.generated_documents enable row level security;

-- RLS policies
create policy "Users can view own profile" on public.profiles for select using (auth.uid() = id);
create policy "Users can update own profile" on public.profiles for update using (auth.uid() = id);
create policy "Users can manage own context" on public.user_context for all using (auth.uid() = user_id);
create policy "Users can manage own conversations" on public.conversations for all using (auth.uid() = user_id);
create policy "Users can manage own messages" on public.messages for all using (
  auth.uid() = (select user_id from public.conversations where id = conversation_id)
);
create policy "Users can manage own jobs" on public.jobs for all using (auth.uid() = user_id);
create policy "Users can manage own documents" on public.generated_documents for all using (auth.uid() = user_id);

-- Storage bucket
insert into storage.buckets (id, name, public) values ('documents', 'documents', false);

create policy "Users can upload own documents"
  on storage.objects for insert
  with check (bucket_id = 'documents' and auth.uid()::text = (storage.foldername(name))[1]);

create policy "Users can read own documents"
  on storage.objects for select
  using (bucket_id = 'documents' and auth.uid()::text = (storage.foldername(name))[1]);
