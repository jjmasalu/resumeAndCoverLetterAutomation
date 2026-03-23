alter table public.generated_documents
  add column if not exists filename text;

with ranked_documents as (
  select
    id,
    (
      case
        when doc_type = 'cover_letter' then 'cover-letter'
        else 'resume'
      end
      || '-'
      || to_char(created_at at time zone 'utc', 'YYYY-MM-DD')
    ) as base_filename,
    row_number() over (
      partition by
        user_id,
        (
          case
            when doc_type = 'cover_letter' then 'cover-letter'
            else 'resume'
          end
          || '-'
          || to_char(created_at at time zone 'utc', 'YYYY-MM-DD')
        )
      order by created_at, id
    ) as version_number
  from public.generated_documents
)
update public.generated_documents as docs
set filename = case
  when ranked.version_number = 1 then ranked.base_filename || '.docx'
  else ranked.base_filename || '-v' || ranked.version_number || '.docx'
end
from ranked_documents as ranked
where docs.id = ranked.id
  and (docs.filename is null or btrim(docs.filename) = '');

alter table public.generated_documents
  alter column filename set not null;

create unique index if not exists idx_generated_documents_user_filename
  on public.generated_documents(user_id, filename);
