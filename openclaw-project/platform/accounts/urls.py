from django.urls import path
from . import views as v
urlpatterns=[
 path('healthz',v.health),path('readyz',v.ready),path('',v.account_page),path('account/',v.account_page),
 path('account/<str:page>/',v.account_page),path('auth/login',v.signin),path('auth/logout',v.signout),
 path('auth/recovery',v.recovery),path('auth/reset',v.finish,{'purpose':'recovery'}),
 path('auth/activate',v.finish,{'purpose':'onboarding'}),path('auth/mfa',v.mfa),path('auth/revoke-sessions',v.revoke_sessions),
 path('v1/me',v.me),path('v1/projects',v.projects),path('v1/projects/<str:project_id>',v.projects),
 path('internal/accounts/<str:account>/invite',v.invite),path('internal/accounts/<str:account>/revoke',v.operator_revoke),
 path('internal/accounts/<str:account>/suspend',v.suspend),path('internal/accounts/<str:account>/audit',v.operator_audit),
 path('internal/accounts/<str:account>/impersonate',v.forbidden_support),path('internal/accounts/<str:account>/export',v.forbidden_support),
]
for kind in ['tasks','streams','artifacts','conversations','exports','memory','schedules','integrations','controls']:
 urlpatterns += [path('v1/'+kind,v.disabled,{'kind':kind}),path('v1/'+kind+'/<str:object_id>',v.disabled,{'kind':kind}),path('v1/'+kind+'/<str:object_id>/<str:action>',v.disabled,{'kind':kind})]
from . import lifecycle as l
from . import usage as u
from . import requests as r
urlpatterns += [
 path('v1/costs',u.usage),
 path('v1/operations', l.operations),
 path('v1/operations/<str:operation_id>', l.operations),
 path('internal/accounts/<str:account>/deployment/operations',l.provision),
 path('internal/accounts/<str:account>/deployment/operations/<str:operation_id>/retry',l.retry),
]
urlpatterns += [path('v1/requests',r.requests),path('v1/requests/<str:request_id>',r.requests),path('v1/requests/<str:request_id>/cancel',r.cancel)]
urlpatterns.insert(0,path('account/requests/',r.page))
urlpatterns.insert(0,path('account/usage/',u.usage,{'page':True}))
handler404='accounts.views.missing'
handler500='accounts.views.failed'
