-- Which code, rules, tools and runtime served a request (roadmap #5). Written once, when the request is first handed to the runtime.
-- Additive: an older release ignores the column.
ALTER TABLE customer_requests ADD COLUMN versions_json TEXT;
