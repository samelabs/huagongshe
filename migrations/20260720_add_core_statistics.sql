BEGIN;

CREATE TABLE chemistry.statistics (
    metric text PRIMARY KEY,
    exact_count bigint NOT NULL CHECK (exact_count >= 0),
    calculated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE chemistry.statistics IS '首页和 API 使用的核心实体准确计数，避免在线扫描大型事实表';

INSERT INTO chemistry.statistics(metric, exact_count)
VALUES
    ('chemicals', 124111235),
    ('reactions', 2428291);

COMMIT;
