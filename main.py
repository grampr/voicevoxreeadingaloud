from discord.ext import commands
from dotenv import load_dotenv
import os
import discord
import asyncio
import glob
import traceback

# 環境変数のロード
load_dotenv()

# トークンの取得
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# トークンが存在しない場合、ユーザーに入力を促す
if not DISCORD_TOKEN:
    DISCORD_TOKEN = input("Discord Botのトークンを入力してください: ").strip()
    # 新しいトークンを.envファイルに保存
    with open('.env', 'a') as env_file:
        env_file.write(f'\nDISCORD_TOKEN={DISCORD_TOKEN}\n')

# Discordのインテント設定
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.voice_states = True

class MyBot(commands.Bot): 
    async def setup_hook(self):
        for filepath in glob.glob(os.path.join("cogs", "*.py")):
            if os.path.basename(filepath) == "__init__.py": 
                continue

            cog = filepath.replace(os.sep, ".").replace(".py", "")
            try:
                await self.load_extension(cog)
                print(f"{cog}を読み込みました。")
            except Exception as e:
                print(f"{cog}の読み込みに失敗しました: {e}")
                traceback.print_exc() 

        await self.tree.sync(guild=None)  

bot = MyBot(command_prefix='!m', intents=intents, heartbeat_timeout=60, case_insensitive=True)

async def main():
    try:
        await bot.start(DISCORD_TOKEN)  # 環境変数またはコンソールから取得したトークンを使用
    finally:
        await bot.close()

if __name__ == '__main__':
    # トークンが空白かどうかの検証
    if not DISCORD_TOKEN:
        print("トークンが提供されていません。スクリプトを終了します。")
    else:
        asyncio.run(main())