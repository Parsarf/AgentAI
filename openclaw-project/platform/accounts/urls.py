from django.urls import path
from . import views as v
from . import chat as ch
from . import telegram as tg
from . import streams as st
from . import api as api
from . import hub as hubv
from . import uishell as shell
from . import genui as gen
from . import app_views
from . import media
from . import browse as br
from . import devices as dvc
from . import model_key as mkv
from . import longterm as ltm
from . import vault as vt
from . import safety as sfy
from . import signup as su
from . import panel as pnl
urlpatterns=[
 path('healthz',v.health),path('readyz',v.ready),path('',v.account_page),path('account/',v.account_page),
 path('account/ui',v.assets),path('account/ui/',v.assets),path('account/chat/',ch.chat_page),path('account/<str:page>/',v.account_page),path('auth/login',v.signin),path('auth/logout',v.signout),
 path('auth/recovery',v.recovery),path('auth/reset',v.finish,{'purpose':'recovery'}),
 path('auth/activate',v.finish,{'purpose':'onboarding'}),path('auth/signup',su.signup),path('auth/signup/verify',su.verify),path('v1/signup/config',su.config),path('auth/mfa',v.mfa),path('auth/revoke-sessions',v.revoke_sessions),
 path('v1/me',v.me),path('v1/csrf',api.csrf),path('v1/app',api.app),path('app/',shell.serve),path('app/<path:path>',shell.serve),path('v1/projects',v.projects),path('v1/projects/<str:project_id>',v.projects),
 path('internal/accounts/<str:account>/invite',v.invite),path('internal/accounts/<str:account>/revoke',v.operator_revoke),
 path('internal/accounts/<str:account>/suspend',v.suspend),path('internal/accounts/<str:account>/audit',v.operator_audit),
 path('internal/accounts/<str:account>/impersonate',v.forbidden_support),path('internal/accounts/<str:account>/export',v.forbidden_support),
]
for kind in ['streams','memory','schedules']:      # 'exports', 'integrations' and 'controls' are real routes now (roadmap Phase 2-3, below)
 urlpatterns += [path('v1/'+kind,v.disabled,{'kind':kind}),path('v1/'+kind+'/<str:object_id>',v.disabled,{'kind':kind}),path('v1/'+kind+'/<str:object_id>/<str:action>',v.disabled,{'kind':kind})]
# Task list/creation stays disabled; single-task reads and cancel are chat-scoped.
urlpatterns += [path('v1/tasks',v.disabled,{'kind':'tasks'})]
from . import files as fl
urlpatterns += [
 path('v1/projects/<str:project_id>/files',fl.files_route),
 path('v1/projects/<str:project_id>/files/<str:file_id>/preview',fl.preview),
 path('v1/projects/<str:project_id>/bundle',fl.bundle),
 path('v1/files',fl.account_files),path('v1/files/bundle',fl.account_bundle),path('v1/export/table',fl.export_table),
 path('v1/conversations/<str:conversation_id>/export',fl.export_conversation),
 path('v1/artifacts/<str:artifact_id>/delete',fl.delete_artifact),
 path('v1/artifacts/<str:artifact_id>/versions/<str:version>/preview',fl.artifact_preview),
 path('v1/apps/player', app_views.player),
 path('v1/artifacts/<str:artifact_id>/versions/<str:version>/app', app_views.source),
 path('v1/artifacts/<str:artifact_id>/versions/<str:version>/ticket',fl.ticket),
 path('v1/artifacts/<str:artifact_id>/versions/<str:version>/download',fl.download),
]
from . import lifecycle as l
from . import usage as u
from . import spending as sp
from . import objectives as ob
from . import estimates as es
from . import requests as r
from . import connections as cn
urlpatterns += [
 path('v1/costs',u.usage),
 path('v1/spending-limits',sp.limits),
 path('v1/estimates/<str:kind>',es.estimate),
 path('v1/objectives',ob.listing),path('v1/objectives/<str:objective_id>',ob.detail),path('v1/objectives/<str:objective_id>/cancel',ob.cancel),
 path('v1/operations', l.operations),
 path('v1/operations/<str:operation_id>', l.operations),
 path('internal/accounts/<str:account>/deployment/operations',l.provision),
 path('internal/accounts/<str:account>/deployment/operations/<str:operation_id>/retry',l.retry),
]
urlpatterns += [path('v1/requests',r.requests),path('v1/requests/<str:request_id>',r.requests),path('v1/requests/<str:request_id>/cancel',r.cancel)]
urlpatterns += [
 path('v1/tasks/<str:request_id>/events',st.events),path('v1/tasks/<str:request_id>/stream',st.stream),
]
urlpatterns += [
 path('v1/conversations',ch.chat_conversations),path('v1/conversations/<str:conversation_id>',ch.chat_conversations),
 path('v1/conversations/<str:conversation_id>/messages',ch.chat_messages),path('v1/conversations/<str:conversation_id>/archive',ch.chat_archive),
 path('v1/conversations/<str:conversation_id>/send',ch.chat_send),path('v1/conversations/<str:conversation_id>/goal',ch.chat_goal),
 path('v1/conversations/<str:conversation_id>/restore',ch.chat_restore),
 path('v1/conversations/<str:conversation_id>/blocks',gen.blocks),
 path('v1/media/<str:image_id>',media.card_image),path('v1/blocks/<str:block_id>/state',gen.block_state),path('v1/blocks/<str:block_id>/submit',gen.block_submit),path('v1/blocks/<str:block_id>/launch',gen.block_launch),
 path('v1/genui/artifacts/<str:artifact_id>/asset',fl.gen_asset),
 path('v1/genui/artifacts/<str:artifact_id>/diagnostics',gen.artifact_diagnostic),path('v1/genui/registry',gen.component_registry),path('v1/genui/artifacts/<str:artifact_id>/state',gen.artifact_state),path('v1/genui/artifacts/<str:artifact_id>/events',gen.artifact_event),path('v1/genui/artifacts/<str:artifact_id>/update',gen.artifact_update),
 path('v1/blocks/<str:block_id>/live',gen.block_live),path('v1/blocks/<str:block_id>/phase',gen.block_phase),path('v1/blocks/<str:block_id>/stop',gen.block_stop),
 path('v1/blocks/<str:block_id>/replan',gen.block_replan),path('v1/blocks/<str:block_id>/proposal',gen.block_proposal),path('v1/blocks/<str:block_id>/auto-replan',gen.block_auto_replan),
 path('v1/conversations/<str:conversation_id>/rename',ch.chat_rename),
 path('v1/browse',br.runs),path('v1/browse/<str:request_id>',br.run),path('v1/browse/<str:request_id>/control',br.control),
 path('v1/browse/<str:request_id>/release',br.release),path('v1/browse/<str:request_id>/pause',br.pause),path('v1/browse/<str:request_id>/resume',br.resume),path('v1/browse/<str:request_id>/answer',br.answer),path('v1/saved',br.saved_list),path('v1/vault',vt.items),path('v1/devices',dvc.listing),path('v1/devices/pair',dvc.pair),path('v1/devices/use',dvc.use),path('v1/longterm-memory',ltm.state),path('v1/longterm-memory/forget-all',ltm.forget_all),path('v1/longterm-memory/<str:entry_id>/forget',ltm.forget),path('v1/model-key',mkv.state),path('v1/model-key/save',mkv.save),path('v1/model-key/remove',mkv.remove),path('v1/devices/<str:device_id>/revoke',dvc.revoke),path('v1/safety',sfy.state),path('v1/safety/change',sfy.change),path('v1/safety/access',sfy.access),path('v1/safety/access/change',sfy.access_change),path('v1/vault/add',vt.add),path('v1/vault/<str:item_id>/delete',vt.remove),path('v1/saved/<str:field>/forget',br.saved_forget),path('v1/browse/<str:request_id>/live',br.live),path('v1/browse/<str:request_id>/shot/<str:name>',br.shot),
 path('v1/assistant/presence',api.presence),
 path('v1/tasks/<str:request_id>',ch.chat_task),path('v1/tasks/<str:request_id>/cancel',ch.chat_cancel),
 path('v1/requests/<str:request_id>/pause',ch.chat_pause),path('v1/requests/<str:request_id>/resume',ch.chat_resume),path('v1/requests/<str:request_id>/retry',ch.chat_retry),
 path('v1/account/telegram/link',tg.link),path('v1/account/telegram/unlink',tg.unlink),
 path('v1/account/telegram',tg.bindings),path('v1/telegram/webhook',tg.webhook),
]
urlpatterns.insert(0,path('account/requests/',r.page))
urlpatterns.insert(0,path('account/usage/',u.usage,{'page':True}))
handler404='accounts.views.missing'
handler500='accounts.views.failed'
urlpatterns += [path('v1/account/connections',cn.connections),path('v1/account/connections/link',cn.link),
 path('v1/account/connections/callback',cn.callback),path('v1/account/connections/disconnect',cn.disconnect),
 path('v1/account/drafts',cn.drafts)]
urlpatterns.insert(0,path('account/connections/',cn.connections,{'page':True}))
from . import billing as bl
urlpatterns += [path('v1/account/billing',bl.billing),path('v1/account/billing/checkout',bl.checkout),
 path('v1/account/billing/portal',bl.portal),path('v1/billing/webhook',bl.webhook)]
urlpatterns.insert(0,path('account/billing/',bl.billing,{'page':True}))

from . import mcp_connections as mcp
urlpatterns += [path('v1/account/mcp', mcp.connections),
                path('v1/account/mcp/callback', mcp.callback),
                path('v1/account/mcp/<str:connection_id>/<str:action>', mcp.change),
                path('v1/account/mcp-approvals/<str:call_id>', mcp.approve)]
urlpatterns += [path('v1/panel/session', pnl.session), path('v1/panel/state', pnl.state), path('v1/panel/events', pnl.events), path('v1/panel/history', pnl.history), path('v1/panel/send', pnl.send), path('v1/panel/stop', pnl.stop)]

from . import location as loc
urlpatterns += [path('v1/location', loc.pending), path('v1/location/<str:location_id>', loc.answer)]


urlpatterns += [path('v1/model-key/select', mkv.select)]
from . import work as wk
urlpatterns += [path('v1/work', wk.listing), path('v1/work/ticket', wk.ticket), path('v1/work/<str:request_id>', wk.detail)]

# ---- roadmap Phase 2 and 3: permissions, connected services, the action pipeline, data lifecycle ----
from . import access as acc
from . import actions as act
from . import organization as org
from . import lifecycle_data as ld
urlpatterns += [
 path('v1/hub', hubv.overview), path('v1/hub/ask', hubv.ask), path('v1/hub/link', hubv.link), path('v1/hub/link/callback', hubv.link_callback), path('v1/hub/refresh', hubv.refresh), path('v1/hub/settings', hubv.settings),
 path('v1/hub/mail/threads', hubv.threads), path('v1/hub/mail/labels', hubv.labels), path('v1/hub/mail/thread', hubv.thread), path('v1/hub/mail/message', hubv.message),
 path('v1/hub/mail/search-older', hubv.search_older), path('v1/hub/calendars', hubv.calendars), path('v1/hub/events', hubv.events), path('v1/hub/event', hubv.event),
 path('v1/hub/events/search', hubv.search_events),
 path('v1/controls', acc.controls),
 path('v1/integrations', acc.integrations), path('v1/integrations/synthetic/connect', acc.synthetic_connect),
 path('v1/integrations/<str:connection_id>', acc.integrations), path('v1/integrations/<str:connection_id>/resources', acc.resources),
 path('v1/integrations/<str:connection_id>/grants', acc.grants), path('v1/integrations/<str:connection_id>/remove', acc.remove),
 path('v1/integrations/<str:connection_id>/auto-approve', acc.auto_approve),
 path('v1/actions', act.listing), path('v1/actions/<str:action_id>', act.detail), path('v1/actions/<str:action_id>/approve', act.approve),
 path('v1/actions/<str:action_id>/decline', act.decline), path('v1/actions/<str:action_id>/undo', act.undo), path('v1/actions/<str:action_id>/compensate', act.compensate),
 path('v1/workflows/<str:workflow_id>', act.workflow), path('v1/workflows/<str:workflow_id>/approve', act.workflow_approve), path('v1/workflows/<str:workflow_id>/decline', act.workflow_decline),
 path('v1/handoffs', act.handoffs), path('v1/handoffs/<str:handoff_id>/answer', act.handoff_answer),
 path('v1/organization', org.organization), path('v1/organization/policy', org.policy),
 path('v1/organization/members/<str:actor_id>/role', org.member_role), path('v1/organization/members/<str:actor_id>/remove', org.member_remove),
 path('v1/retention', ld.retention),
 path('v1/exports', ld.exports), path('v1/exports/<str:export_id>', ld.exports), path('v1/exports/<str:export_id>/ticket', ld.export_ticket),
 path('v1/exports/<str:export_id>/download', ld.export_download),
 path('v1/conversations/<str:conversation_id>/delete', ld.delete_conversation),
 path('v1/account/offboarding', ld.offboarding), path('v1/account/offboarding/<str:action>', ld.offboarding),
]
