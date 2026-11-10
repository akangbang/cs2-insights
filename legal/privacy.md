# Privacy policy

*Draft, last updated November 9, 2026. Have a lawyer review before public launch.*

Getleanpeek analyzes CS2 match demos to grade players' decisions. This page explains what we collect and what we do with it.

## What we collect

When you upload a demo or choose one from your CS2 replays folder, Getleanpeek reads it and keeps **match data** from it:

- the map, server name, score and how each round ended;
- for each of the 10 players: their Steam ID, in-game name, team, side, and each round's money, equipment value, armor, helmet and defuse kit;
- every kill: who killed whom, with which weapon, where on the map, and when;
- at the moment of each kill, where each player stood and which way they were aiming;
- grenades thrown, who flashes blinded and for how long, and grenade damage.

If you link your Steam match history, we also store your **Steam ID**, your **match history authentication code** and the **share codes** of your matches, so we can show which matches are ready to analyze. The authentication code is stored **encrypted**, with a key kept outside the database.

We do **not** collect your Steam password, payment details (handled by our payment provider if you subscribe), chat messages, voice or anything outside the demo file.

## How you use Getleanpeek

To improve the product, Getleanpeek records **which features are used**: for example that a report was opened, a demo uploaded, a round clicked or the habits page viewed, with the time, a random session ID, a scrambled ID for your account if you're logged in, and the Steam ID and match being reviewed. It does **not** record your IP address, device, browser, or anything you type. These records stay in the same database as your matches, are never shown to other users, and are only used for aggregate product numbers (such as how many reports are opened per day).

If you press **Disagree** on a verdict, we keep which verdict it was (match, round and player), the reason you picked, and a scrambled ID for your account, to find where Getleanpeek gets things wrong.

## What we don't keep

The demo file itself is read and then discarded. We don't store or share demo files.

## How we use it

- To produce your match report.
- To compute **pooled win rates**: how often each kind of buy wins against each other kind across all matches analyzed. Pooled rates are aggregate numbers and never show another player's identity.

We don't sell your data, use it for advertising, or send you marketing you didn't ask for.

## Other players in your match

A demo contains information about all 10 players. Getleanpeek only shows the match data needed for your report. Any player who wants their data removed can ask us (see below), whether or not they uploaded anything.

## Where it's stored

The app runs on Streamlit Community Cloud, operated by Snowflake. Match data is stored in a PostgreSQL database hosted by Neon in the United States (Ohio). Steam data is only stored in the places listed here.

## Your choices

- **Delete your data yourself** on the **Your data** page:
  - *Forget my player* replaces your Steam ID in every stored match with a random ID and removes your name. The match numbers themselves stay, anonymous, because the other nine players' reports depend on them; nothing links them back to you. It also removes a linked Steam match history.
  - *Delete my account data* removes your settings, your usage history, your disagreements and any match only you added.
- **Ask us instead:** email andrewwkangg@gmail.com with your Steam ID, for example if you never used Getleanpeek but appear in someone else's match.
- **Unlink match history:** ask us, or change your match history authentication code in Steam, which stops any further access.

## Services we use

When you sign in through Steam, Getleanpeek receives only your public Steam ID. It turns it into a scrambled account ID and saves the Steam ID as "This is me", so your reports open on you. When you sign in with Google, Getleanpeek receives your email address and turns it into a scrambled ID; the address itself isn't stored in our database. Getleanpeek uses the Steam Web API to look up profiles and match share codes when you ask it to. Getleanpeek is not affiliated with or endorsed by Valve Corporation.

## Contact

andrewwkangg@gmail.com
