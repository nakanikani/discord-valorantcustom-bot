import os
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands

# --- Render対策: Webサーバー（ポート開放用） ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Discord Bot 本体の設定 ---
intents = discord.Intents.default()
intents.message_content = True  # メッセージ内容の取得を許可

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")

@bot.command()
async def ping(ctx):
    await ctx.send("pong!")

# --------------------------------------------------
# ↓ 追加: !custom コマンドの処理
# --------------------------------------------------
@bot.command()
async def custom(ctx):
    # ここにカスタムパネル作成やチーム分けなどの処理を書きます
    await ctx.send("VALORANTカスタム募集を開始します！")

# Webサーバーを起動
keep_alive()

# 環境変数からトークンを取得してBotを起動
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN is not set.")
