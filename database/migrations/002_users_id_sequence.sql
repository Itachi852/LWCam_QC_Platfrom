BEGIN;

-- The shared LWCam schema defines users.id as a plain BIGINT primary key.
-- This platform creates users, so give that column a concurrency-safe default
-- without changing any other table (in particular, qc_status).
CREATE SEQUENCE IF NOT EXISTS public.users_id_seq AS BIGINT;

SELECT setval(
    'public.users_id_seq',
    COALESCE((SELECT MAX(id) FROM public.users), 0) + 1,
    false
);

ALTER TABLE public.users
    ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

COMMIT;
