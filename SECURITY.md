# Security

## Reporting a problem

If you find a security problem in Getleanpeek, such as a way to see another player's matches, sign in as someone else, or reach data you shouldn't, please **don't open a public issue**. Email andrewwkangg@gmail.com instead, with:

- what you found and where (page, URL, or file and line);
- how to reproduce it;
- what someone could do with it.

You'll get a reply within 7 days. Please give a reasonable time to fix it before telling anyone else.

## What's in scope

- The live site, <https://getleanpeek.streamlit.app>, and the code in this repository.
- Sign-in (Steam OpenID, Google), keeping each account's matches separate, the stored Steam auth codes (encrypted), and the read-only Power BI login.

Not in scope: Streamlit Community Cloud, Neon, Steam and Google themselves (report those to them), and denial of service.

## How data is protected

The [Privacy policy](legal/privacy.md) describes what's stored. In short: guests' demos aren't stored, account IDs are scrambled hashes rather than emails, Steam auth codes are encrypted with a key kept outside the database, and dashboards log in with a role that can only read the `analytics` schema. Secrets live in `.env` or Streamlit's secrets settings, never in the repository.
