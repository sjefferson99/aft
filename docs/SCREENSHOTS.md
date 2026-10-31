# Docs screenshots

The images in `www/images/docs` are taken by `scripts/screenshots.py`, from a throwaway stack running generic demo data.

**Retake only what a change visibly altered.** Every image stays in git history for good, so don't regenerate the set for a small change. Retake an image when a major change alters what that screen looks like, and look at the result before committing it.

## Taking screenshots

1. Stop the dev stack, then start the throwaway one. `down` first matters: if the containers are recreated in place, `aft-db` keeps its `./data` mount underneath the in-memory one. Your `./data` isn't touched either way.

   ```sh
   docker compose down
   docker compose -f compose.yml -f compose.screenshots.yml up -d --build
   ```

2. Take the images you need. The first run seeds the empty database.

   ```sh
   .venv\Scripts\python.exe scripts/screenshots.py board card_detail
   .venv\Scripts\python.exe scripts/screenshots.py --list
   ```

3. Check each image, then go back to the dev stack. The demo data is lost when the containers stop.

   ```sh
   docker compose -f compose.yml -f compose.screenshots.yml down
   docker compose up -d --build
   ```

The script refuses to run against a database it didn't seed, so it can't photograph real data. To use another address, set `AFT_SCREENSHOT_URL`.

## Adding an image

Add a function with the `@shot` decorator to `scripts/screenshots.py`. Its name is the image name. Use the board and card names from the seed functions there, and keep any new demo data generic. Then reference the image from the guide beside what it shows, as `../images/docs/<name>.png`.
