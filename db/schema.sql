-- Skema Postgres (Supabase). Idempoten: aman dijalankan berulang (python -m scripts.migrate).
-- Semua tabel di schema `absensi` (bukan `public`) dan RLS aktif tanpa policy, sehingga
-- Supabase Data API (anon/authenticated key) tidak bisa membaca apa pun. Hanya API kita
-- (koneksi role postgres lewat DATABASE_URL) yang mengakses data.

create schema if not exists absensi;

create table if not exists absensi.settings (
    key   text primary key,
    value text not null default ''
);

create table if not exists absensi.session_defs (
    code       text primary key,
    name       text not null,
    start_hhmm text not null check (start_hhmm ~ '^[0-2][0-9]:[0-5][0-9]$'),
    end_hhmm   text not null check (end_hhmm ~ '^[0-2][0-9]:[0-5][0-9]$')
);

create table if not exists absensi.kelas (
    name   text primary key,
    active boolean not null default true
);

create table if not exists absensi.mapel (
    name   text primary key,
    active boolean not null default true
);

create table if not exists absensi.users (
    user_id       text primary key,
    username      text not null,
    name          text not null,
    role          text not null check (role in ('admin', 'guru')),
    pin_hash      text not null,
    token_version integer not null default 0,
    active        boolean not null default true,
    created_at    timestamptz not null
);
create unique index if not exists users_username_lower on absensi.users (lower(username));

create table if not exists absensi.rates (
    id               bigserial primary key,
    user_id          text not null references absensi.users (user_id),
    rate_per_meeting bigint not null check (rate_per_meeting >= 0),
    effective_from   date not null,
    set_by           text not null,
    set_at           timestamptz not null
);
create index if not exists rates_user on absensi.rates (user_id);

create table if not exists absensi.session_instances (
    session_id      text primary key,
    date            date not null,
    code            text not null,
    scheduled_start timestamptz not null,
    scheduled_end   timestamptz not null,
    opened_at       timestamptz,
    opened_by       text not null default '',
    closed_at       timestamptz,
    unique (date, code)
);

create table if not exists absensi.attendance (
    attendance_id text primary key,
    session_id    text not null references absensi.session_instances (session_id),
    date          date not null,
    code          text not null,
    user_id       text not null references absensi.users (user_id),
    teacher_name  text not null,
    kelas         text not null,
    mapel         text not null,
    scanned_at    timestamptz not null,
    submitted_at  timestamptz not null,
    lat           double precision,
    lng           double precision,
    accuracy_m    double precision,
    distance_m    double precision,
    status        text not null check (status in ('on_time', 'late')),
    late_min      integer not null default 0,
    rate_snapshot bigint not null default 0,
    source        text not null check (source in ('scan', 'manual', 'button')),
    voided        boolean not null default false,
    void_reason   text not null default '',
    voided_by     text not null default '',
    ticket_id     text
);
-- Migrasi DB lama: izinkan source 'button' (konfirmasi kehadiran tanpa QR).
alter table absensi.attendance drop constraint if exists attendance_source_check;
alter table absensi.attendance add constraint attendance_source_check
    check (source in ('scan', 'manual', 'button'));
-- Inti aturan "1 guru maksimal 1 absensi valid per sesi": dijamin oleh database.
create unique index if not exists attendance_one_valid
    on absensi.attendance (session_id, user_id) where not voided;
create unique index if not exists attendance_ticket
    on absensi.attendance (ticket_id) where ticket_id is not null;
create index if not exists attendance_date on absensi.attendance (date);
create index if not exists attendance_user_date on absensi.attendance (user_id, date);

create table if not exists absensi.attempts (
    id         bigserial primary key,
    ts         timestamptz not null,
    user_id    text not null,
    session_id text not null default '',
    reason     text not null,
    distance_m double precision,
    accuracy_m double precision,
    detail     text not null default ''
);
create index if not exists attempts_ts on absensi.attempts (ts desc);

create table if not exists absensi.payslips (
    period        text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
    user_id       text not null references absensi.users (user_id),
    meetings      integer not null,
    gross         bigint not null,
    take_home     bigint not null,
    status        text not null check (status in ('draft', 'final')),
    finalized_at  timestamptz,
    finalized_by  text not null default '',
    snapshot_json text not null default '',
    primary key (period, user_id)
);

create table if not exists absensi.audit_log (
    id          bigserial primary key,
    ts          timestamptz not null,
    actor       text not null,
    action      text not null,
    entity      text not null,
    entity_id   text not null,
    before_json text not null default '',
    after_json  text not null default '',
    reason      text not null default ''
);
create index if not exists audit_ts on absensi.audit_log (ts desc);

-- Kunci Data API Supabase: RLS aktif tanpa policy = tidak ada akses untuk anon/authenticated.
alter table absensi.settings          enable row level security;
alter table absensi.session_defs      enable row level security;
alter table absensi.kelas             enable row level security;
alter table absensi.mapel             enable row level security;
alter table absensi.users             enable row level security;
alter table absensi.rates             enable row level security;
alter table absensi.session_instances enable row level security;
alter table absensi.attendance        enable row level security;
alter table absensi.attempts          enable row level security;
alter table absensi.payslips          enable row level security;
alter table absensi.audit_log         enable row level security;
