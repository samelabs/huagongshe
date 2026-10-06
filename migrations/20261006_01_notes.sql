-- HGS v1.7.0 Notes domain.
-- Independent user context linked to HCID / HRID.
-- No feed/social coupling; references are real FKs.

CREATE TABLE community.notes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
    visibility text NOT NULL DEFAULT 'private',
    moderation_status text NOT NULL DEFAULT 'visible',
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notes_visibility_check CHECK (visibility IN ('private','public')),
    CONSTRAINT notes_moderation_status_check CHECK (moderation_status IN ('visible','hidden')),
    CONSTRAINT notes_content_length CHECK (char_length(content) BETWEEN 1 AND 30000)
);

CREATE INDEX notes_owner_updated_idx
    ON community.notes(owner_user_id, updated_at DESC, id DESC);

CREATE INDEX notes_public_updated_idx
    ON community.notes(updated_at DESC, id DESC)
    WHERE visibility='public' AND moderation_status='visible';

CREATE TABLE community.note_chemicals (
    note_id bigint NOT NULL REFERENCES community.notes(id) ON DELETE CASCADE,
    chemical_id integer NOT NULL REFERENCES chemistry.chemicals(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, chemical_id)
);

CREATE INDEX note_chemicals_chemical_idx
    ON community.note_chemicals(chemical_id, note_id DESC);

CREATE TABLE community.note_reactions (
    note_id bigint NOT NULL REFERENCES community.notes(id) ON DELETE CASCADE,
    reaction_id bigint NOT NULL REFERENCES chemistry.reactions(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, reaction_id)
);

CREATE INDEX note_reactions_reaction_idx
    ON community.note_reactions(reaction_id, note_id DESC);
