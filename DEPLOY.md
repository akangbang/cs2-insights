# Putting Getleanpeek online for free

This runs the app on Streamlit Community Cloud with a free Neon database. It costs $0 and gives you an address like `https://getleanpeek.streamlit.app`.

**This setup is for a free test with friends, not a paid product.** Streamlit's terms say an app that handles personal data can only be used for personal, non-commercial purposes such as evaluation, and you must be 18 or older. Move to a paid host (see the end) before you charge anyone or advertise it as a business.

## Before you invite anyone

- Have a lawyer review the privacy policy and terms before a public launch.

## 1. Create the database (Neon)

1. Sign up at <https://neon.com> and create a project. Pick the region closest to your players.
2. Copy the connection string. It looks like `postgresql://user:password@host/dbname?sslmode=require`.

The app creates its own tables the first time it connects. The free plan holds 1 GB, about 1,800 matches.

## 2. Create the Google sign-in

1. Go to <https://console.cloud.google.com> and create a project.
2. Under **Google Auth Platform**, set up the consent screen. Choose **External**. While it's in testing, add each friend's Gmail address as a test user.
3. Under **Clients**, create an **OAuth client** of type **Web application**.
4. Add this **Authorized redirect URI**, using the address you plan to use in step 4:
   `https://getleanpeek.streamlit.app/oauth2callback`
5. Copy the client ID and client secret.

## 3. Make your secrets

Copy `.streamlit/secrets.toml.example` and fill it in. Never commit the filled-in copy.

Create the two random values on your own PC:

```powershell
.venv\Scripts\python -m cs2_insights.secretbox --new-key   # HALFTIME_SECRET_KEY
.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"   # cookie_secret
```

Keep `HALFTIME_SECRET_KEY` somewhere safe. If it's lost, stored Steam auth codes can't be decrypted.

## 4. Deploy

1. Sign in at <https://share.streamlit.io> with GitHub.
2. Choose **Create app**, then deploy from the repository `akangbang/cs2-insights`, branch `main`, main file `app.py`.
3. Set the app URL to `getleanpeek`. If it's taken, choose another and change the redirect URI from step 2 to match.
4. Open **Advanced settings**, choose **Python 3.12**, and paste your secrets.
5. Deploy. The first build takes a few minutes.

Sign in through Steam needs no setup: it sends players back to the site address in `redirect_uri`. If your app's address is different, add `HALFTIME_PUBLIC_URL = "https://your-address/"` to the secrets.

## 5. Check it

- Without signing in, the site should show only the sign-in button.
- Sign in, upload a demo, and open the report.
- Sign in with a second account: it must not show the first account's matches.

## What to expect on the free plan

- **It sleeps** after 12 hours without visitors. The next visitor has to wake it.
- **Large demos may crash it.** Parsing a 405 MB demo used about 990 MB of memory here, and Streamlit lists 690 MB to 2.7 GB per app. Try your largest demo first.
- **The address stays on `streamlit.app`.** A custom domain such as `getleanpeek.com` needs a different host.

## When you outgrow it

Move before you charge money, or if large demos keep crashing. A Hetzner CX23 at about €6 a month has 4 GB of memory and can use your own domain.
