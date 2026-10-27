# Component catalog

_Generated from `lumina/src/gen/manifest.ts` by `GEN_WRITE=1 npx vitest run src/gen/export.test.ts`. Do not edit by hand; a test fails when this file drifts._

**187 entries: 86 implemented, 5 adapter, 89 planned, 7 unsupported.**

- **implemented**: a renderer exists, either directly or *via* another implemented component with specific props or a variant. Only these are ever shown to the model.
- **adapter**: code exists (a renderer or a bridge) but a host capability or provider is missing, so it is not offered. The reason is in the Purpose column.
- **planned**: designed, not built. **unsupported**: deliberately not offered.

Kind: primitive (one control or text element), composite (built from primitives), widget (a specialised display), adapter (needs external data). "Live provider" says whether the entry needs a data provider that does not exist yet.

## Text and content

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `text` | Plain text | primitive | implemented | `text` | A paragraph of prose. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `markdown` | Markdown | primitive | implemented | `text` (format: markdown) | Prose with lists, emphasis and links; raw HTML is skipped. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `rich_text` | Rich text (read-only) | composite | implemented | `text` (format: markdown) | Formatted prose; authoring is not offered. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `heading` | Heading | primitive | implemented | `heading` | A section heading (levels 2-4). | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `list` | List | primitive | implemented | `list` | Bulleted or numbered items. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `checklist` | Checklist | composite | implemented | `list` (items[].checked) | Items with a checked state. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `quote` | Quote | primitive | implemented | `quote` | A quotation with its source. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `callout` | Callout | primitive | implemented | `callout` | A tip, warning or note set apart from the prose. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `citation_list` | Citations | composite | implemented | `citation_list` | Numbered sources with links and snippets. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `source_preview` | Source preview | composite | planned | — | Needs a server-side page fetch; links are shown instead. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `math` | Math | widget | planned | — | Needs a typesetting library (KaTeX). | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `code_block` | Code block | primitive | implemented | `code_block` | Monospaced code with a copy button. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `syntax_highlighting` | Syntax highlighting | composite | planned | — | Code is shown monospaced without colours; needs a highlighter. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `diff_viewer` | Diff viewer | widget | implemented | `diff_viewer` | A unified diff with added and removed lines marked. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `json_viewer` | JSON viewer | widget | implemented | `json_viewer` | Pretty-printed, collapsible-by-scroll JSON text. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `terminal_output` | Terminal output | widget | implemented | `terminal_output` | Command output lines. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `expandable_text` | Expandable text | composite | implemented | `text` (expansion: collapsed) | Long text collapsed to a few lines. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |
| `copyable_snippet` | Copyable snippet | composite | implemented | `code_block` (copyable) | A short code or command with a copy button. | text or markdown | none, except copy on code and output, and collapse on long text | plain text | no |

## Cards and results

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `info_card` | Information card | composite | implemented | `info_card` | One entity: title, subtitle, facts, link, actions. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `metric_card` | KPI / metric | composite | implemented | `metric_card` | One number with unit, change and optional trend line. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `profile_card` | Profile card | composite | implemented | `info_card` (facts) | A person or organisation. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `product_card` | Product card | composite | implemented | `info_card` (facts + link) | A product with price and link as facts. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `business_card` | Business card | composite | implemented | `info_card` (facts) | A place of business with address and hours as facts. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `comparison_card` | Comparison card | composite | implemented | `card_grid` (variant horizontal) | Options side by side. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `status_card` | Status card | composite | implemented | `status_card` | A state with a label and detail. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `progress_card` | Progress card | composite | implemented | `progress` | A bounded value or steps. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `file_card` | File card | composite | planned | — | Needs the file.download host adapter (files are served by artifact id behind a ticket). | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `media_card` | Media card | composite | planned | — | Needs an asset resolver for the customer files. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `recommendation_card` | Recommendation card | composite | implemented | `info_card` (badge + facts) | A suggested option with the reasons as facts. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `summary_card` | Summary card | composite | implemented | `info_card` (body + facts) | A short summary with key facts. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `action_card` | Action card | composite | implemented | `info_card` (actions: agent.request) | A card whose buttons send a request. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `expandable_card` | Expandable card | composite | implemented | `info_card` (variant expandable) | A card that opens to show detail. | title plus a few facts | expand, optional actions | plain text list of the facts | no |
| `result_collection` | Result collection | composite | implemented | `card_grid` | A group of cards. | title plus a few facts | expand, optional actions | plain text list of the facts | no |

## Tables and data

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `table` | Table | composite | implemented | `table` | Rows and typed columns; sortable, searchable and paginated in the browser. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `sortable_table` | Sortable table | composite | implemented | `table` (sortable) | Click a header to sort. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `filterable_table` | Filterable table | composite | implemented | `table` (searchable) | Filter rows by text. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `searchable_table` | Searchable table | composite | implemented | `table` (searchable) | Search across all cells. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `editable_table` | Editable table | composite | planned | — | Needs cell-edit validation and a save path. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `paginated_table` | Paginated table | composite | implemented | `table` (pageSize) | Pages of rows. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `pivot_table` | Pivot table | composite | planned | — | Pivot table | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `data_grid` | Data grid | composite | planned | — | Virtualised grid for very large data; needs a backend dataRef provider. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `tree_table` | Tree table | composite | planned | — | Tree table | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `comparison_matrix` | Comparison matrix | composite | implemented | `table` (rowHeader) | Options as columns, criteria as rows. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `leaderboard` | Leaderboard | composite | implemented | `table` (defaultSort) | Ranked rows. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |
| `spreadsheet_preview` | Spreadsheet preview | composite | implemented | `table` (dataRef) | A read-only paged grid of a dataset. | columns plus rows, or a dataset reference | sort, filter, paginate (local) | plain text rows | no |

## Charts and analytics

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `line_chart` | Line chart | widget | implemented | `line_chart` | A trend over an ordered axis. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `bar_chart` | Bar chart | widget | implemented | `bar_chart` | Compare categories. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `stacked_bar_chart` | Stacked bar chart | widget | implemented | `bar_chart` (variant stacked) | Parts of a whole across categories. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `area_chart` | Area chart | widget | implemented | `area_chart` | A trend with volume. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `pie_chart` | Pie chart | widget | implemented | `pie_chart` | Shares of one whole. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `donut_chart` | Donut chart | widget | implemented | `pie_chart` (donut) | Shares with a centre total. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `scatter_chart` | Scatter plot | widget | implemented | `scatter_chart` | The relationship between two measures. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `bubble_chart` | Bubble chart | widget | planned | — | Bubble chart | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `histogram` | Histogram | widget | implemented | `histogram_chart` | Distribution of one numeric measure in equal-width bins. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `heatmap` | Heatmap | widget | planned | — | Heatmap | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `radar_chart` | Radar chart | widget | planned | — | Radar chart | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `funnel_chart` | Funnel | widget | planned | — | Funnel | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `waterfall_chart` | Waterfall | widget | planned | — | Waterfall | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `candlestick_chart` | Candlestick | widget | planned | — | Candlestick | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `box_plot` | Box plot | widget | planned | — | Box plot | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `gauge` | Gauge | widget | implemented | `gauge` | One value on a scale, with optional status zones. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `progress_chart` | Progress chart | widget | implemented | `progress` | A bar showing a value out of a maximum. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `treemap` | Treemap | widget | planned | — | Treemap | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `sankey` | Sankey | widget | unsupported | — | Needs a layout library and rarely beats a table; not offered. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `network_graph` | Network graph | widget | planned | — | Network graph | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `timeline_chart` | Timeline | widget | implemented | `timeline` | Events in order. | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |
| `gantt` | Gantt chart | widget | planned | — | Gantt chart | dataset with a category key and numeric series | legend toggle, data-table alternative | data table | no |

## Inputs and forms

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `button` | Button | primitive | implemented | `button_group` | Sends a validated action. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `icon_button` | Icon button | primitive | planned | — | Icon button | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `text_input` | Text input | primitive | implemented | `form` (field type text) | One line of text. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `textarea` | Textarea | primitive | implemented | `form` (field type textarea) | Several lines of text. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `checkbox` | Checkbox | primitive | implemented | `form` (field type checkbox) | A yes/no choice. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `radio` | Radio group | primitive | implemented | `form` (field type radio) | One of a few options. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `select` | Select | primitive | implemented | `form` (field type select) | One of many options. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `multiselect` | Multi-select | primitive | planned | — | Multi-select | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `segmented_control` | Segmented control | primitive | implemented | `form` (field type segmented) | One of two to four options. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `slider` | Slider | primitive | implemented | `form` (field type slider) | A number in a range. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `range_slider` | Range slider | primitive | planned | — | Range slider | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `switch` | Switch | primitive | implemented | `form` (field type toggle) | An on/off setting. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `date_picker` | Date picker | primitive | implemented | `form` (field type date) | A calendar date (the browser control). | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `time_picker` | Time picker | primitive | implemented | `form` (field type time) | A time of day (the browser control). | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `date_range` | Date range | composite | planned | — | Date range | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `number_stepper` | Number stepper | primitive | implemented | `form` (field type number) | A number with steps. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `search_input` | Search input | primitive | planned | — | Search input | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `upload` | Upload | primitive | unsupported | — | File upload from generated UI would bypass the files pipeline checks. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `color_picker` | Color picker | primitive | unsupported | — | No task needs it. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `rating` | Rating input | primitive | planned | — | Rating input | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `tags` | Tags input | primitive | planned | — | Tags input | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `autocomplete` | Autocomplete | primitive | planned | — | Autocomplete | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `grouped_form` | Grouped form | composite | implemented | `form` (variant grouped, field group) | Fields in labelled groups. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `conditional_form` | Conditional form | composite | implemented | `form` (showIf) | Fields that appear depending on earlier answers. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |
| `confirmation` | Confirmation | composite | implemented | `approval_request` (internal confirm dialog) | Asks before a consequential action; built into every action. | field definitions | local edit, submit as an agent request | plain text asking for the values | no |

## Navigation and layout

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `tabs` | Tabs | composite | implemented | `tabs` | Switch between groups of blocks. | child blocks | local switch/expand | children shown in order | no |
| `accordion` | Accordion | composite | implemented | `accordion` | Sections that open and close. | child blocks | local switch/expand | children shown in order | no |
| `collapsible` | Collapsible | composite | implemented | `accordion` (one item) | One section that opens and closes. | child blocks | local switch/expand | children shown in order | no |
| `popover` | Popover | widget | planned | — | Popover | child blocks | local switch/expand | children shown in order | no |
| `tooltip` | Tooltip | widget | planned | — | Tooltip | child blocks | local switch/expand | children shown in order | no |
| `modal` | Modal (generated) | widget | planned | — | Modal (generated) | child blocks | local switch/expand | children shown in order | no |
| `drawer` | Drawer | widget | planned | — | Drawer | child blocks | local switch/expand | children shown in order | no |
| `carousel` | Carousel | widget | planned | — | Carousel | child blocks | local switch/expand | children shown in order | no |
| `pagination` | Pagination | composite | implemented | `table` (pageSize) | Page through rows; part of the table. | child blocks | local switch/expand | children shown in order | no |
| `breadcrumb` | Breadcrumb | composite | planned | — | Breadcrumb | child blocks | local switch/expand | children shown in order | no |
| `stepper` | Stepper | composite | implemented | `timeline` (events[].state) | Steps with a state each. | child blocks | local switch/expand | children shown in order | no |
| `split_view` | Split view | widget | planned | — | Split view | child blocks | local switch/expand | children shown in order | no |
| `resizable_panels` | Resizable panels | widget | planned | — | Resizable panels | child blocks | local switch/expand | children shown in order | no |
| `tree_navigation` | Tree navigation | widget | planned | — | Tree navigation | child blocks | local switch/expand | children shown in order | no |
| `command_palette` | Command palette | widget | unsupported | — | An app-level control, not part of an answer. | child blocks | local switch/expand | children shown in order | no |
| `context_menu` | Context menu | widget | unsupported | — | An app-level control, not part of an answer. | child blocks | local switch/expand | children shown in order | no |
| `dropdown_menu` | Dropdown menu | widget | planned | — | Dropdown menu | child blocks | local switch/expand | children shown in order | no |
| `divider` | Divider | primitive | implemented | `divider` | A quiet separator. | child blocks | local switch/expand | children shown in order | no |
| `section` | Section container | composite | implemented | `section` | Groups blocks with a title and a grid. | child blocks | local switch/expand | children shown in order | no |

## Media and documents

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `image` | Image | primitive | adapter | — | Renderer exists; not offered until the host can turn a file reference into a loadable URL (never an arbitrary address). | file reference in the customer files | open | link or caption | no |
| `gallery` | Gallery | composite | adapter | — | Same as image: renderer exists, host asset resolver missing. | file reference in the customer files | open | link or caption | no |
| `image_carousel` | Image carousel | composite | planned | — | Image carousel | file reference in the customer files | open | link or caption | no |
| `image_comparison` | Image comparison | widget | planned | — | Image comparison | file reference in the customer files | open | link or caption | no |
| `video` | Video | widget | planned | — | Needs a safe playback policy for customer files. | file reference in the customer files | open | link or caption | no |
| `audio` | Audio | widget | planned | — | Audio | file reference in the customer files | open | link or caption | no |
| `waveform` | Waveform | widget | unsupported | — | No task needs it. | file reference in the customer files | open | link or caption | no |
| `pdf_viewer` | PDF / document viewer | adapter | adapter | — | Files already have a preview endpoint; embedding it in a document is not wired. | file reference in the customer files | open | link or caption | no |
| `annotation` | Annotation | widget | unsupported | — | Needs write paths that do not exist. | file reference in the customer files | open | link or caption | no |
| `zoom` | Zoom | widget | planned | — | Zoom | file reference in the customer files | open | link or caption | no |
| `3d_model` | 3D model | widget | planned | — | three is bundled for the Lumina orb only. | file reference in the customer files | open | link or caption | no |
| `mermaid` | Mermaid diagram | widget | planned | — | Mermaid diagram | file reference in the customer files | open | link or caption | no |
| `flowchart` | Flowchart | widget | planned | — | Flowchart | file reference in the customer files | open | link or caption | no |
| `mind_map` | Mind map | widget | planned | — | Mind map | file reference in the customer files | open | link or caption | no |

## Maps and location

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `map` | Map | widget | planned | — | Map: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `pins` | Pins | widget | planned | — | Pins: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `clustering` | Clustering | widget | planned | — | Clustering: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `route` | Route | widget | planned | — | Route: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `itinerary` | Multi-stop itinerary | widget | planned | — | Multi-stop itinerary: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `geo_heatmap` | Geo heatmap | widget | planned | — | Geo heatmap: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `region_comparison` | Region comparison | widget | planned | — | Region comparison: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `distance` | Distance | widget | planned | — | Distance: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `map_layers` | Map layers | widget | planned | — | Map layers: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |
| `location_search` | Location search | widget | planned | — | Location search: needs a map provider and tile source (none configured). Places can already be shown as cards with map links. | coordinates from a provider | pan, zoom | table of places with links | yes |

## Agent-native

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `task_progress` | Task progress | widget | implemented | `execution_timeline` (variant inline) | Where a task is, read from its real events. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `execution_timeline` | Execution timeline | widget | implemented | `execution_timeline` | The real tool calls and notes of a task, in order. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `live_activity` | Live activity | widget | implemented | `execution_timeline` (live) | The same timeline, refreshed while the task runs. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `tool_call_inspector` | Tool-call inspector | widget | implemented | `tool_call_inspector` | One tool call: label, detail and output. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `agent_status` | Agent status | widget | implemented | `agent_status` | Queued, working, done or failed, from the request record. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `plan_viewer` | Plan viewer | widget | implemented | `plan_viewer` | The phases of a plan and where each is. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `plan_editor` | Plan editor | adapter | adapter | — | Exists as the standalone task_plan block (PlanBlock); not embeddable in a document yet. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `execution_tree` | Execution tree | widget | planned | — | Execution tree | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `subagent_panel` | Subagent panel | widget | planned | — | Subagent panel | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `dependency_graph` | Dependency graph | widget | planned | — | Dependency graph | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `error_retry` | Error and retry | widget | implemented | `error_retry` | A failed step or request with a retry. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `approval_request` | Approval request | widget | implemented | `approval_request` | Approve or skip a gated phase; pending, approved, skipped, failed and expired states. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `evidence_viewer` | Evidence viewer | widget | implemented | `citation_list` (snippet) | Sources and the snippets that support a claim. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `logs` | Logs | widget | implemented | `terminal_output` | Output lines. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `checkpoints` | Checkpoints | widget | planned | — | Checkpoints | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `token_cost_monitor` | Token and cost monitor | widget | planned | — | No per-request token/cost record is exposed to the UI yet; nothing is invented. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |
| `completion_summary` | Completion summary | widget | implemented | `completion_summary` | What a finished request reported. | request or plan reference (state is read from Lumina records) | approve, deny, retry (validated server side) | plain status sentence | no |

## Decision tools

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `calculator` | Calculator | widget | planned | — | Calculator | inputs and rules | local recalculation | table of the options | no |
| `scenario_simulator` | Scenario simulator | widget | planned | — | Scenario simulator | inputs and rules | local recalculation | table of the options | no |
| `decision_matrix` | Decision matrix | widget | planned | — | Decision matrix | inputs and rules | local recalculation | table of the options | no |
| `weighted_scoring` | Weighted scoring | widget | planned | — | Weighted scoring | inputs and rules | local recalculation | table of the options | no |
| `questionnaire` | Questionnaire | composite | implemented | `form` | A few questions whose answers are sent as a request. | inputs and rules | local recalculation | table of the options | no |
| `wizard` | Wizard | widget | planned | — | Multi-step forms are not built. | inputs and rules | local recalculation | table of the options | no |
| `budget_allocator` | Budget allocator | widget | planned | — | Budget allocator | inputs and rules | local recalculation | table of the options | no |
| `filter_builder` | Filter builder | widget | planned | — | Filter builder | inputs and rules | local recalculation | table of the options | no |
| `rule_builder` | Rule builder | widget | planned | — | Rule builder | inputs and rules | local recalculation | table of the options | no |
| `parameter_configurator` | Parameter configurator | composite | implemented | `form` | Sliders and selects whose values are sent as a request. | inputs and rules | local recalculation | table of the options | no |
| `recommendation_selector` | Recommendation selector | composite | implemented | `follow_up` | Suggested next requests as buttons. | inputs and rules | local recalculation | table of the options | no |

## Scheduling and productivity

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `calendar` | Calendar | widget | planned | — | Calendar: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `agenda` | Agenda | widget | planned | — | Agenda: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `event` | Event | widget | planned | — | Event: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `availability_grid` | Availability grid | widget | planned | — | Availability grid: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `kanban` | Kanban | widget | planned | — | Kanban: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `reminder` | Reminder | widget | planned | — | Reminder: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `recurring_schedule` | Recurring schedule | widget | planned | — | Recurring schedule: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `time_tracker` | Time tracker | widget | planned | — | Time tracker: the Calendar and Automations pages exist but are not embeddable in a document. | dated items | select, drag | timeline list | no |
| `project_timeline` | Project timeline | composite | implemented | `timeline` | Dated steps in order. | dated items | select, drag | timeline list | no |
| `milestones` | Milestones | composite | implemented | `timeline` (events[].state) | Key dates with a state. | dated items | select, drag | timeline list | no |

## Domain adapters

| Id | Name | Kind | Status | Built from | Purpose | Data needed | Interactions | Fallback | Live provider |
|---|---|---|---|---|---|---|---|---|---|
| `weather` | Weather | adapter | planned | — | Weather: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `sports` | Sports | adapter | planned | — | Sports: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `stocks` | Stocks | adapter | planned | — | Stocks: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `financial_statement` | Financial statement | adapter | planned | — | Financial statement: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `currency_conversion` | Currency / unit conversion | adapter | planned | — | Currency / unit conversion: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `shopping_comparison` | Shopping comparison | adapter | planned | — | Shopping comparison: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `restaurants` | Restaurants | adapter | planned | — | Restaurants: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `reservations` | Reservations | adapter | planned | — | Reservations: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `travel_itinerary` | Travel itinerary | adapter | planned | — | Travel itinerary: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `health_trends` | Health trends | adapter | planned | — | Health trends: needs a data provider contract and permissions. Until then, compose metric_card, table and charts from real results the assistant fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `database_result` | Database result | adapter | adapter | — | Renders through the table with a dataRef; datasets embedded in the document work today, a server-side dataRef provider does not exist. | provider result | provider specific | metric cards and a table of the result | yes |
| `repository_tree` | Repository tree | adapter | planned | — | Repository tree | provider result | provider specific | metric cards and a table of the result | yes |
| `pull_request_diff` | Pull-request diff | adapter | implemented | `diff_viewer` | A diff the assistant already fetched. | provider result | provider specific | metric cards and a table of the result | yes |
| `api_inspector` | API inspector | adapter | planned | — | API inspector | provider result | provider specific | metric cards and a table of the result | yes |
