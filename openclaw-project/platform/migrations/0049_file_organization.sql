-- File organization (roadmap #30). Additive: an older release ignores all of it.
-- Folders belong to a project. A folder's name is unique among its siblings, whatever its letter case.
CREATE TABLE file_folders (
 account_id TEXT NOT NULL, id TEXT NOT NULL, project_id TEXT NOT NULL, parent_id TEXT,
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120), created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id),
 FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id),
 FOREIGN KEY(account_id,parent_id) REFERENCES file_folders(account_id,id)
);
CREATE UNIQUE INDEX file_folders_sibling ON file_folders(account_id,project_id,coalesce(parent_id,''),lower(name));
-- Where the customer put a file, and what they named it. One row per file they organized; a file with no row is where it was made, under its own name. `kind` says which
-- table holds the file: an upload (project_files) or a file the assistant made (artifacts, every version of it together). The files themselves are never rewritten.
CREATE TABLE file_places (
 account_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('upload','made')), object_id TEXT NOT NULL,
 folder_id TEXT, name TEXT CHECK(name IS NULL OR length(name) BETWEEN 1 AND 128), updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,kind,object_id),
 FOREIGN KEY(account_id,folder_id) REFERENCES file_folders(account_id,id)
);
CREATE INDEX file_places_folder ON file_places(account_id,folder_id);
-- An upload that has the same content as one already kept shares its bytes: `shares_with` is the upload whose bytes it uses (never stored twice).
ALTER TABLE project_files ADD COLUMN shares_with TEXT;
CREATE INDEX project_files_hash ON project_files(account_id,sha256);
