-- Таблиця історії перевірок для Supabase (PostgreSQL).
-- Виконати один раз: Supabase → SQL Editor → New query → вставити весь файл → Run.

create table if not exists public.reviews (
    id                  bigint generated always as identity primary key,
    created_at          timestamptz not null default now(),
    language            text,
    model               text,
    filename            text,
    score               integer check (score between 0 and 100),
    issues_count        integer not null default 0,
    errors_count        integer not null default 0,
    bad_practice_count  integer not null default 0,
    style_count         integer not null default 0,
    code_lines          integer,
    duration_ms         integer,
    input_tokens        integer,
    output_tokens       integer,
    cost_usd            numeric(12, 6),
    summary             text,
    result              jsonb
);

create index if not exists reviews_created_at_idx on public.reviews (created_at desc);

-- Безпека: вмикаємо Row Level Security і НЕ додаємо політик.
-- Тоді публічний (publishable/anon) ключ не бачить таблицю взагалі,
-- а сервер працює із секретним ключем (sb_secret_...), який обходить RLS.
alter table public.reviews enable row level security;

-- Явні права для серверного (секретного) ключа: потрібні, якщо в проєкті вимкнено
-- автоматичне відкриття нових таблиць для Data API. Публічні ролі прав не отримують.
grant select, insert on public.reviews to service_role;
revoke all on public.reviews from anon, authenticated;

-- Зручне представлення для перевірки на захисті (SQL Editor → select * from review_stats;)
create or replace view public.review_stats
with (security_invoker = true) as
select
    count(*)                                   as total_reviews,
    round(avg(score), 1)                       as avg_score,
    round(avg(duration_ms))                    as avg_duration_ms,
    sum(errors_count)                          as errors,
    sum(bad_practice_count)                    as bad_practices,
    sum(style_count)                           as style_issues,
    round(avg(cost_usd)::numeric, 6)           as avg_cost_usd
from public.reviews;

grant select on public.review_stats to service_role;
revoke all on public.review_stats from anon, authenticated;
