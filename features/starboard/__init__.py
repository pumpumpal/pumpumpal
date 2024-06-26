from typing import TYPE_CHECKING

from .starboard import Starboard

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Starboard(bot))
