from typing import TYPE_CHECKING

from .moderation import Moderation

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Moderation(bot))
