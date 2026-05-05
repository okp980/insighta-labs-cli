# insighta

Insighta Labs command-line interface. Authenticate with GitHub and manage
profiles directly from your terminal.

```text
insighta login
insighta whoami
insighta profiles list --gender male --country NG
insighta profiles export --format csv
```

The CLI talks to the Insighta backend over HTTP, stores its session in
`~/.insighta/credentials.json` (with `0600` permissions), automatically
refreshes expired access tokens, and prompts you to re-login if the refresh
token has also expired.

---

## Requirements

* Python 3.10 or newer
* A running Insighta backend (default: `http://localhost:8000`)
* The backend must have CLI OAuth credentials configured (see
  [Backend setup](#backend-setup) below) before `insighta login` will succeed

## Install (global)

### Recommended: `pipx`

```bash
pipx install .
```

This installs the `insighta` command into an isolated environment and exposes
it on your `PATH`, so `insighta login` works from any directory.

### Alternative: `pip`

```bash
python3 -m pip install --user .
# make sure ~/.local/bin (or your user-base scripts dir) is on PATH
```

### Development install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify the install:

```bash
insighta --version
insighta --help
```

## Configuration

The CLI is zero-config for the default local setup. To point it at a different
backend, set:

| Variable                 | Default                  | Purpose                          |
| ------------------------ | ------------------------ | -------------------------------- |
| `INSIGHTA_API_URL`       | `http://localhost:8000`  | Backend base URL                 |
| `INSIGHTA_API_VERSION`   | `1`                      | Sent as `X-API-Version` header   |

Credentials are stored at `~/.insighta/credentials.json` and re-created on each
`insighta login`.

## Authentication

`insighta login` runs a standard OAuth 2.0 authorization-code + PKCE flow for
native apps (RFC 8252):

1. The CLI asks the backend for the GitHub `client_id` and registered
   loopback `redirect_uri` via `GET /auth/cli/start`.
2. The CLI generates a fresh `state` and a PKCE `code_verifier` /
   `code_challenge` (SHA-256), then binds an HTTP server on the loopback port
   from the redirect URI.
3. The CLI opens the GitHub authorize page in your browser. After you approve,
   GitHub redirects back to the CLI's loopback server with `?code=&state=`.
4. The CLI verifies `state`, then `POST`s `{ code, code_verifier, state }` to
   `/auth/cli/exchange`. The backend exchanges the code with GitHub
   (using its own client secret + the verifier), creates or finds the user,
   mints JWTs, and returns them in the JSON body.
5. The CLI writes the tokens to `~/.insighta/credentials.json` (`0600`).

Subsequent commands send the JWTs as `access_token` / `refresh_token` cookies
and a CSRF double-submit pair (`csrf_token` cookie + `X-CSRF-Token` header) on
state-changing requests. On a `401`, the CLI calls `POST /auth/refresh`,
persists the new tokens, and retries once. If refresh also fails, it wipes
the credentials and prompts you to run `insighta login` again.

## Command reference

```text
insighta login        Authenticate via GitHub
insighta logout       Revoke session and remove ~/.insighta/credentials.json
insighta whoami       Show the currently signed-in user
insighta profiles list [options]
insighta profiles get <ID>
insighta profiles search "<query>"
insighta profiles create --name "<full name>"
insighta profiles export --format csv [filters] [--output <path>]
```

### `profiles list`

```bash
insighta profiles list
insighta profiles list --gender male
insighta profiles list --country NG --age-group adult
insighta profiles list --min-age 25 --max-age 40
insighta profiles list --sort-by age --order desc
insighta profiles list --page 2 --limit 20
```

Available options:

| Option        | Values                              |
| ------------- | ----------------------------------- |
| `--gender`    | `male`, `female`                    |
| `--country`   | ISO-3166 alpha-2 (`NG`, `US`, ...)  |
| `--age-group` | `child`, `teenager`, `adult`, `senior` |
| `--min-age`   | integer                             |
| `--max-age`   | integer                             |
| `--sort-by`   | `age`, `created_at`, `gender_probability` |
| `--order`     | `asc`, `desc`                       |
| `--page`      | integer (1-indexed, default `1`)    |
| `--limit`     | integer up to `50` (default `10`)   |

### `profiles get`

```bash
insighta profiles get 019ddf19-9a7f-73dd-8e4b-a9a6fba2c4fd
```

### `profiles search`

```bash
insighta profiles search "young males from nigeria"
insighta profiles search "senior women" --limit 20
```

### `profiles create`

```bash
insighta profiles create --name "Harriet Tubman"
```

Requires the `admin` role. The backend enriches the name via external
genderize / agify / nationalize APIs; the result is stored and returned.

### `profiles export`

```bash
insighta profiles export --format csv
insighta profiles export --format csv --gender male --country NG
insighta profiles export --format csv --output ./ng-males.csv
```

The CSV is streamed and written to the **current working directory** under the
filename provided by the server's `Content-Disposition` header (or a
timestamped fallback). Use `--output` to override.

## Backend setup (CLI OAuth)

`insighta login` requires the backend to be configured for the CLI flow.
Register a separate GitHub OAuth app whose authorization callback URL points
at the loopback redirect (default `http://127.0.0.1:42069/callback`), then add
to the backend's `.env`:

```env
GITHUB_CLI_CLIENT_ID=...
GITHUB_CLI_CLIENT_SECRET=...
GITHUB_CLI_REDIRECT_URI=http://127.0.0.1:42069/callback
```

Until those are set, `insighta login` will surface a clear error from
`/auth/cli/start`.

## Troubleshooting

* **"Could not bind loopback callback on 127.0.0.1:42069"** \u2014 another process
  is using that port. Stop it, or change the port in
  `GITHUB_CLI_REDIRECT_URI` on the backend (and update the GitHub OAuth app's
  callback URL to match).
* **"Session expired or invalid."** \u2014 your refresh token also expired. Run
  `insighta login` again.
* **"Forbidden: only admins can create profiles."** \u2014 GitHub sign-ups default
  to the `analyst` role. Ask an admin to promote your account.

## License

MIT
