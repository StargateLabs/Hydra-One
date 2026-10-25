"""Exact-profile dispatch; historical evidence never grants a new campaign."""
from serve import hydra_acceptance_v18 as old,hydra_acceptance_v19 as new
template_request=old.template_request
sampling_payload=old.sampling_payload
def module(body):
 if body.get('profile') in new.PROFILES:return new
 if body.get('profile') in old.PROFILES:return old
 raise ValueError('UNKNOWN_FINITE_CAMPAIGN_PROFILE')
def selected(body,cfg):return module(body).selected(body,cfg)
def allow_spawn(request,argv):return module(request).allow_spawn(request,argv)
def required_controls(body):return module(body).required_controls(body)
def available():return new.available() or old.available()
def RequestGate(body,key,item,forward):return module(body).RequestGate(body,key,item,forward)
def finish(body,row):return module(body).finish(body,row)
def bind_comparison(row):return module(row).bind_comparison(row)
