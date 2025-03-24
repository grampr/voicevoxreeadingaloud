from discord.ext import commands
import discord

class ReadyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        latency = self.bot.latency * 1000
        await self.bot.tree.sync()
        await self.bot.change_presence(activity=discord.Game(name=f"ping値{latency:.2f}ms"))

        print(f"{self.bot.user.name} がログインしました！")
        invite_link = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=discord.Permissions(administrator=True),
            scopes=("bot", "applications.commands")
        )
        print(f"Invite link: {invite_link}")


async def setup(bot):
    await bot.add_cog(ReadyCog(bot))