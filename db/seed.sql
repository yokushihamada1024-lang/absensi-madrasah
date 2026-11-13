-- Data default (idempoten). Jalankan SETELAH db/schema.sql, mis. di Supabase SQL Editor.
-- Sama dengan yang diisi `python -m scripts.migrate`. Aman dijalankan berulang: data yang sudah ada tidak diubah.

insert into absensi.session_defs (code, name, start_hhmm, end_hhmm) values
    ('S1', 'Sesi 1', '13:30', '15:45'),
    ('S2', 'Sesi 2', '16:15', '17:30')
on conflict (code) do nothing;

insert into absensi.kelas (name, active) values
    ('Utsman', true), ('Aisyah', true), ('Abu Bakar', true), ('Khadijah', true),
    ('Fatimah', true), ('Hafsah', true), ('Umar', true), ('Ali', true)
on conflict (name) do nothing;

insert into absensi.mapel (name, active) values
    ('Bahasa Arab', true), ('Fikih', true), ('Iqra', true), ('Tahsin', true), ('Tahfidz', true)
on conflict (name) do nothing;

-- Pengaturan default (koordinat madrasah sengaja kosong: isi lewat Admin → Pengaturan).
insert into absensi.settings (key, value) values
    ('madrasah_name', 'Madrasah'), ('lat', ''), ('lng', ''), ('radius_m', '100'),
    ('max_accuracy_m', '75'), ('qr_rotate_sec', '30'), ('grace_min', '5'), ('early_open_min', '20'),
    ('timezone', 'Asia/Jakarta')
on conflict (key) do nothing;
