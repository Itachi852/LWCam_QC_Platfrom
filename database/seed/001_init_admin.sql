INSERT INTO roles(rolecode, rolename, rolepermission) VALUES
    ('admin', '管理员', '{"user_management":true,"settings":true,"statistics":true}'::jsonb),
    ('qc', 'Metadata QC', '{"metadata_review":true}'::jsonb)
ON CONFLICT(rolecode) DO UPDATE SET
    rolename = EXCLUDED.rolename,
    rolepermission = EXCLUDED.rolepermission;

INSERT INTO users(userid, username, password, isactive, roleid)
SELECT 'admin', 'Administrator', crypt('admin123', gen_salt('bf', 12)), TRUE, id
FROM roles
WHERE rolecode = 'admin'
ON CONFLICT(userid) DO NOTHING;

INSERT INTO system_settings(setting_key, setting_value)
VALUES('shared_image_root', '')
ON CONFLICT(setting_key) DO NOTHING;
