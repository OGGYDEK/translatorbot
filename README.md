# Setup Guide: LibreTranslate Discord Bot

Follow these steps to get your Discord Translation Bot up and running.

## Prerequisites
1. **Python 3.8+** installed.
2. **Discord Bot Token**: Create an application on the [Discord Developer Portal](https://discord.com/developers/applications).
    - Enable **Message Content Intent** in the "Bot" section.
3. **LibreTranslate Instance**: A local clone of the LibreTranslate repository.

## Step 1: Start LibreTranslate
Open a terminal in your `LibreTranslate` folder and run:
```bash
pip install .
libretranslate --port 5000
```
Keep this terminal open while the bot is running.

## Step 2: Configure the Bot
1. Navigate to the `translatorbot` folder.
2. Open `main.py` and replace `'YOUR_BOT_TOKEN_HERE'` with your actual bot token.
3. (Optional) If your LibreTranslate runs on a different port, update `LIBRETRANSLATE_URL`.

## Step 3: Install Dependencies
Run the following command to install required libraries:
```bash
pip install -r requirements.txt
```

## Step 4: Run the Bot
```bash
python main.py
```

## Usage Commands
- **Translate**: `!translate [lang] [text]` (e.g., `!translate es Hello world`)
- **Translate via Reply**: Reply to any message with `!translate [lang]`
- **Whitelist Channel/Role**: `!botfree #channel` or `!botfree @role` (Admin only)
- **Restrict Channel/Role**: `!botrestrict #channel` or `!botrestrict @role` (Admin only)
