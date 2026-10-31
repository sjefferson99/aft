# AFT

Aim, Focus, Track - AFT is an Application For Tasks. It provides an Adaptive Flow Toolkit to let you organise your tasks in the way that makes sense for you and then get them done.

It is fully open source and is self hosted using a simple docker deployment approach.

> Looking for the latest features and changes? Check the [GitHub Releases page](https://github.com/sjefferson99/aft/releases).

![A board in AFT](www/images/docs/board.png)

## Features

### Work the way you want

- **[Kanban boards](www/docs/user-guide.md#working-style)** - Custom columns, with cards you drag between them to reflect your work
- **[Agile boards](www/docs/user-guide.md#working-style)** - A board for each epic or group of tasks, with columns for features you tick off card by card, and done counts showing how far along each one is
- **[Keyboard shortcuts](www/docs/user-guide.md#keyboard-shortcuts)** - Add, archive and reorder cards and add columns without leaving the keyboard
- **[Compact cards](www/docs/user-guide.md#compact-cards)** and **[card actions](www/docs/user-guide.md#card-actions)** - Shrink a busy board to titles, and choose which buttons appear on your cards

### Never forget the regular jobs

I wrote AFT because I couldn't find self hosted Kanban software that let you schedule tasks to appear in your to do list, for things like regular maintenance, bin day and monthly accounts.

- **[Scheduled cards](www/docs/user-guide.md#scheduled-cards)** - Create a card every so many minutes, hours, days, weeks, months or years, with a preview of the next runs
- **[Planner](www/docs/user-guide.md#planner-view)** - See a board's cards and upcoming schedules on a year or month calendar, and move them to a new date

<table>
  <tr>
    <td><img src="www/images/docs/scheduled_cards.png" alt="The Scheduled View, listing recurring cards in a column"></td>
    <td><img src="www/images/docs/card_detail.png" alt="The edit card modal, with a description and checklist"></td>
  </tr>
  <tr>
    <td align="center">Recurring jobs in the Scheduled View</td>
    <td align="center">Everything about a card, saved as you go</td>
  </tr>
</table>

### Everything a card needs

- **[Cards](www/docs/user-guide.md#cards)** - Autosaving edits, dates, assignees, and move to top that works even in a filtered view
- **[Checklists and comments](www/docs/user-guide.md#checklists-and-comments)** - Break work down and discuss it on the card
- **[Search and filters](www/docs/user-guide.md#searching-and-filtering)** - Find cards by text, ID or assignee
- **[Archiving](www/docs/user-guide.md#archiving-cards)** - Clear cards off the board and keep their history

### Share it and bring your data

- **[Multi-user](www/docs/administration.md#security-and-access-control)** - Roles, custom permissions and per-board sharing as viewer or editor, with real-time updates
- **[Public boards](www/docs/user-guide.md#public-boards)** - Share a read-only link, or embed a board in your website
- **[Import](www/docs/user-guide.md#importing-boards)** - Bring boards in from Trello, CSV or another AFT instance

### Make it yours

- **[Themes](www/docs/user-guide.md#themes)** - Build your own colour themes, with background images
- **[Install as an app](www/docs/user-guide.md#install-as-an-app)** - On your phone, tablet or computer, with a touchscreen mode for kiosks

### Run it yourself

- **Self hosted** - A simple docker deployment that runs happily on a Raspberry Pi
- **[Backups](www/docs/administration.md#backups)** - Scheduled database backups with retention, and restores from the app
- **[Secure by default](www/docs/administration.md#security-and-access-control)** - HTTPS, passkey sign-in, sign-in rate limits and regular patching. Security reviews are in the [docs folder](docs)
- **[API](www/docs/administration.md#api)** - The server exposes all functionality via API and the UI is a separate container on top of it, so you can work with AFT programmatically or replace the UI altogether

AFT should be easy to use without reading manuals. If it isn't, [log an issue](https://github.com/sjefferson99/aft/issues) and we'll fix it up.

**Want to see more?** The [user guide](www/docs/user-guide.md) walks through all of this with screenshots.

## Documentation

- [User guide](www/docs/user-guide.md)
- [Administration](www/docs/administration.md)

The same guides are in the app on the Docs page, in the user menu, so they always match your installed version. API Docs in the user menu opens the interactive Swagger page.

## Quick start

No repo clone needed. Images are published to GitHub Container Registry on each release.

```sh
curl -O https://raw.githubusercontent.com/sjefferson99/aft/main/compose.example.yml
curl -O https://raw.githubusercontent.com/sjefferson99/aft/main/.env.example
mv .env.example .env
mv compose.example.yml compose.yml
```

- Edit `.env` with your passwords, CORS config and any other options. See the comments in the file and [Administration](www/docs/administration.md)
- `docker compose pull`
- `docker compose up -d`
- [Adjust the backup folder permissions](www/docs/administration.md#backup-storage)
- Navigate to `http(s)://<docker-host>`

To update later, see [Upgrading](www/docs/administration.md#upgrading).

## Development

Build from source with `compose.yml`, and always include `--build` so current source changes are applied. `compose.example.yml` is the GHCR deployment template.

```sh
git clone https://github.com/sjefferson99/aft.git
cd aft
docker compose up --build -d
```

If you are contributing code (human or AI-assisted), start with [CONTRIBUTING.md](CONTRIBUTING.md). Agent context that should be available across machines is in [AGENT_CONTEXT.md](AGENT_CONTEXT.md).

### Testing

For the backend test suite:

```powershell
cd server
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Tests automatically handle authentication by creating a test admin user. For fresh database setup and more, see [server/docs/SERVER_TESTING.md](server/docs/SERVER_TESTING.md).

For browser-driven UI tests (Playwright, via pytest):

```bash
cd ui-tests
pip install -r requirements-dev.txt
playwright install chromium
pytest
```

See [ui-tests/docs/UI_TESTING.md](ui-tests/docs/UI_TESTING.md) for details.

For measuring board performance at scale, see [perf-tests/README.md](perf-tests/README.md).

#### Testing WebSocket Disconnection

To test the WebSocket disconnection scenario (for development/debugging):

1. Edit [server/app.py](server/app.py) and set `REJECT_SOCKETIO_CONNECTIONS` to `True`
2. Rebuild: `docker compose down ; docker compose up -d --build`
3. Open board page - header shows "WebSocket Disconnected" within 5 seconds
4. Real-time updates will not work
5. Revert `REJECT_SOCKETIO_CONNECTIONS` to `False` and rebuild to restore connectivity

### Docs and screenshots

The docs are Markdown in [www/docs](www/docs), and `www/docs.html` renders them in the app. To change them, edit those files. Screenshots are in `www/images/docs`, and [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) explains how to retake them.

### Architecture and implementation notes

- [docs/Architecture.MD](docs/Architecture.MD)
- [server/docs/AUTHENTICATION.md](server/docs/AUTHENTICATION.md)
- [server/docs/PERMISSION_MODEL.md](server/docs/PERMISSION_MODEL.md)
- [docs/PERMISSION_UI_SYSTEM.md](docs/PERMISSION_UI_SYSTEM.md)
