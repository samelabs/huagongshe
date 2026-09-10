-- Skills 配额校准：按 kdense 158 实测修正（2026-08-17）。
--   * file_count 64 → 128：database-lookup 实测 81 个 references 文件。
--   * 二进制放行目录 assets/ → assets/ + examples/：
--     timesfm-forecasting 实证二进制在 examples/*/output/，不在 assets/。
BEGIN;

ALTER TABLE community.skills
  DROP CONSTRAINT skills_file_count_range;
ALTER TABLE community.skills
  ADD CONSTRAINT skills_file_count_range CHECK (file_count BETWEEN 0 AND 128);

ALTER TABLE community.skill_files
  DROP CONSTRAINT skill_files_text_only;
ALTER TABLE community.skill_files
  ADD CONSTRAINT skill_files_text_only CHECK (
    is_text OR path LIKE 'assets/%' OR path LIKE 'examples/%'
  );

COMMIT;
