-- A client that dies mid-transaction (dropped pooler connection, killed process) must not hold row locks indefinitely.
-- Observed during testing: an orphaned "idle in transaction" session held a lock on a report row for 16+ minutes.
-- Role-level settings apply to new sessions of the role our backend connects with; no schema or data is touched.
alter role postgres set idle_in_transaction_session_timeout = '60s';
alter role postgres set lock_timeout = '15s';
