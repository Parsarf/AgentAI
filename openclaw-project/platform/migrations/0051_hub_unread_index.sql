-- The Inbox's unread badges (agentai_platform/hub.py HubService.counts) scanned every thread of the account and the labels of each: about 60 ms for a mailbox of
-- 68,915 messages on the production host, on the first call of every Inbox page. This index holds only the unread threads. Additive: an older release ignores it.
CREATE INDEX hub_threads_unread ON hub_threads(account_id, connection_id) WHERE unread=1;
