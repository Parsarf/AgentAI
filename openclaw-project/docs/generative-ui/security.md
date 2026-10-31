# Security and authority

Documents are declarative data. Zod validates at the renderer boundary; the server validates the generated JSON Schema plus shared cross-field constraints. Unknown components/properties/actions, excessive payloads/nesting, unsafe links, traversal, invalid dates, dangling graph references and invalid quantitative shapes are rejected. Streaming mounts complete validated blocks only. Markdown skips HTML; executable URLs and external image auto-loading are blocked.

Events bind to stored artifact/node/action definitions. Clients cannot submit an arbitrary action body. Every write reauthorizes the principal, scopes the conversation, checks document version, and records the event. Local state has a separate compare-and-swap revision. Event idempotency and deterministic request keys prevent duplicate request execution; native phase guards protect consequential approvals/retries. Rendering an approval never grants permission.

Generated code/terminal/API/diff displays remain literal. Decision tools use named finite operations only. Mermaid rejects configuration/click/resource directives and renders strict library output inside an opaque-origin sandbox with a no-network CSP. KaTeX uses untrusted strict bounded rendering to MathML. Files are resolved through the existing scanned uploads and artifact-ticket pipeline; active file types cannot be previewed. PDF iframes have no script or same-origin access. GLB viewers block external model resources.

The database retains historical messages, artifacts and images. Removal of the old producer and renderer does not delete user data. New tables are explicitly classified in backup/restore; restored events do not automatically resume execution. Account deactivation and ownership checks still gate every access.
