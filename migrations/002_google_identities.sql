-- Additive migration for Google OpenID Connect sign-in.
-- Apply manually to the existing database; do not run schema initialization.
CREATE TABLE user_identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (provider, provider_subject),
    UNIQUE (user_id, provider)
);

CREATE INDEX idx_user_identities_user_id ON user_identities(user_id);
