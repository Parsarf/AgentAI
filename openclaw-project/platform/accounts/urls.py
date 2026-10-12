from django.urls import path
from . import views as v
from . import chat as ch
from . import telegram as tg
from . import streams as st
from . import api as api
from . import uishell as shell
urlpatterns=[
 path('healthz',v.health),path('readyz',v.ready),path('',v.account_page),path('account/',v.account_page),
 path('account/ui',v.assets),path('account/ui/',v.assets),path('account/chat/',ch.chat_page),path('account/<str:page>/',v.account_page),path('auth/login',v.signin),path('auth/logout',v.signout),
 path('auth/recovery',v.recovery),path('auth/reset',v.finish,{'purpose':'recovery'}),
 path('auth/activate',v.finish,{'purpose':'onboarding'}),path('auth/mfa',v.mfa),path('auth/revoke-sessions',v.revoke_sessions),
 path('v1/me',v.me),path('v1/csrf',api.csrf),path('v1/app',api.app),path('app/',shell.serve),path('app/<path:path>',shell.serve),path('v1/projects',v.projects),path('v1/projects/<str:project_id>',v.projects),
 path('internal/accounts/<str:account>/invite',v.invite),path('internal/accounts/<str:account>/revoke',v.operator_revoke),
 path('internal/accounts/<str:account>/suspend',v.suspend),path('internal/accounts/<str:account>/audit',v.operator_audit),
 path('internal/accounts/<str:account>/impersonate',v.forbidden_support),path('internal/accounts/<str:account>/export',v.forbidden_support),
]
for kind in ['streams','exports','memory','schedules','integrations','controls']:
 urlpatterns += [path('v1/'+kind,v.disabled,{'kind':kind}),path('v1/'+kind+'/<str:object_id>',v.disabled,{'kind':kind}),path('v1/'+kind+'/<str:object_id>/<str:action>',v.disabled,{'kind':kind})]
# Task list/creation stays disabled; single-task reads and cancel are chat-scoped.
urlpatterns += [path('v1/tasks',v.disabled,{'kind':'tasks'})]
from . import files as fl
urlpatterns += [
 path('v1/projects/<str:project_id>/files',fl.files_route),
 path('v1/projects/<str:project_id>/files/<str:file_id>/preview',fl.preview),
 path('v1/projects/<str:project_id>/bundle',fl.bundle),
 path('v1/artifacts/<str:artifact_id>/versions/<str:version>/ticket',fl.ticket),
 path('v1/artifacts/<str:artifact_id>/versions/<str:version>/download',fl.download),
]
from . import lifecycle as l
from . import usage as u
from . import requests as r
from . import connections as cn
urlpatterns += [
 path('v1/costs',u.usage),
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
 path('v1/conversations/<str:conversation_id>/send',ch.chat_send),
 path('v1/tasks/<str:request_id>',ch.chat_task),path('v1/tasks/<str:request_id>/cancel',ch.chat_cancel),
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
