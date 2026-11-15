-- A draft can be a reply: reply_to_id is the local id of the message it answers (its thread
-- and Gmail message id are read from that row when the approved draft is sent).
ALTER TABLE email_messages ADD COLUMN reply_to_id INTEGER REFERENCES email_messages(id);
